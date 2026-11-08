import pytest

from src.core.modbus_knowledge import normalize_query, query_phrases
from src.core.modbus_facts import validate_analysis_scope
from src.core.modbus_facts import broadcast_answer, transaction_facts
from src.core.modbus_log import analyze_rtu_log
from src.core.modbus_agent import ModbusAgent
from tests.unit.test_modbus_agent import ScriptedLLM, Knowledge
from types import SimpleNamespace


@pytest.mark.parametrize("query,expected", [
    ("exception code 2", "exception code 0x02"),
    ("异常码02", "exception code 0x02"),
    ("异常代码：0x02", "exception code 0x02"),
    ("exception code 10", "exception code 0x0A"),
    ("exception code 0x10", "exception code 0x10"),
    ("function code 3 address 2", "function code 3 address 2"),
    ("exception code 0x102", "exception code 0x102"),
])
def test_context_bound_code_normalization(query, expected):
    assert normalize_query(query) == expected
    assert normalize_query(normalize_query(query)) == expected


def test_function_code_is_not_mistaken_for_exception_code():
    phrases = query_phrases("Modbus function code 3 exception code 2")
    assert "illegal data address" in phrases
    assert "illegal data value" not in phrases
    assert "gateway path unavailable" in query_phrases("exception code 10")


@pytest.mark.parametrize("text", ["无需排查物理故障。", "无缺失信息。", "写入已成功。", "系统完全正常。"])
def test_known_unsupported_broadcast_absolutes_are_rejected(text):
    with pytest.raises(ValueError):
        validate_analysis_scope(text, [{"status": "broadcast"}])


@pytest.mark.parametrize("text", ["不能确认写入已成功。", "无法确认系统完全正常。", "没有响应符合广播规则，但需要核对写入结果。"])
def test_qualified_broadcast_explanations_are_not_rejected(text):
    validate_analysis_scope(text, [{"status": "broadcast"}])


def test_negative_statement_does_not_hide_absolute_in_next_clause():
    with pytest.raises(ValueError):
        validate_analysis_scope("不能确认写入，但无缺失信息。", [{"status": "broadcast"}])


def test_broadcast_rule_requires_original_retrieved_evidence():
    fact = {"event": "L0", "status": "broadcast", "slave_address": 0, "function_code": 6}
    assert broadcast_answer("广播没响应", [fact], [], []) is None
    assert broadcast_answer("广播没响应", [fact], [], [{"id": "D1", "kind": "synthetic", "text": "No response is returned to broadcast"}]) is None
    text = broadcast_answer("广播没响应", [fact], [], [{"id": "D1", "kind": "official_pdf", "text": "No response is returned to broadcast requests"}])
    assert "[D1]" in text
    assert "不能确认从站已接收或执行写入" in text


def test_broadcast_agent_does_not_need_a_freeform_generation_call():
    model = ScriptedLLM([{"action": "analyze_log"}, {"action": "search_docs", "query": "broadcast"}, {"action": "finish"}])
    knowledge = SimpleNamespace(answer=lambda *a, **kw: {"citations": [{"id": "D1", "chunk_id": "serial-p7", "page": 7,
        "kind": "official_pdf", "text": "No response is returned to broadcast requests"}]})
    result = ModbusAgent(model, knowledge).run("广播没回复", events=[
        {"timestamp_ms": 0, "direction": "TX", "hex_frame": "00 06 00 01 00 05 19 D8"}])
    assert result["status"] == "completed"
    assert result["answer_source"] == "retrieved_protocol_rule"
    assert len(model.prompts) == 3
    assert "pending" not in result["answer"]


def test_clarification_after_evidence_keeps_known_facts_in_answer():
    events = [{"timestamp_ms": 0, "direction": "TX", "hex_frame": "01 03 00 00 00 02 C4 0B"}]
    facts = transaction_facts(analyze_rtu_log(events))
    model = ScriptedLLM([{"action": "analyze_log"}, {"action": "search_docs", "query": "timeout"},
        {"action": "ask_user", "question": "请补充设备型号。"},
        {"log_claims": facts, "analysis": "当前观察不足以判定超时，建议延长记录并补充设备型号。[D1]"}])
    result = ModbusAgent(model, Knowledge()).run("解释日志并说明还需什么", events=events)
    assert result["status"] == "completed"
    assert result["follow_up_question"] == "请补充设备型号。"
    assert result["verified_log_claims"][0]["status"] == "pending"
    assert "suggested_follow_up" in model.prompts[-1][-1].content
