"""Real LangGraph execution with scripted LLM decisions; no API calls."""
import json
from types import SimpleNamespace

import pytest

from src.core.modbus_agent import ModbusAgent, parse_action


class ScriptedLLM:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages)
        reply = next(self.actions)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(content=json.dumps(reply, ensure_ascii=False) if isinstance(reply, dict) else reply)


class Knowledge:
    def answer(self, query, **kwargs):
        return {"citations": [{"id": "D1", "chunk_id": "exception-p48", "page": 48,
                               "kind": "official_pdf", "text": "02 ILLEGAL DATA ADDRESS"}]}


def test_document_agent_selects_search_then_finishes():
    model = ScriptedLLM([{"action": "search_docs", "query": "异常码02"},
                         {"action": "finish"}, "异常码02表示非法数据地址。[D1]"])
    result = ModbusAgent(model, Knowledge()).run("异常码02是什么")
    assert result["status"] == "completed"
    assert [x["node"] for x in result["trace"]] == ["decide", "tools", "decide", "respond"]
    assert "ILLEGAL DATA ADDRESS" in model.prompts[1][-1].content


def test_log_tool_then_search_then_answer():
    model = ScriptedLLM([{"action": "analyze_log"}, {"action": "search_docs", "query": "响应超时"},
                         {"action": "finish"}, {"log_claims": [{"event": "L0", "status": "pending", "slave_address": 1,
                             "function_code": 3, "start_address": 0, "quantity": 2}],
                             "analysis": "建议延长观察窗口。请核对协议资料。[D1]"}])
    result = ModbusAgent(model, Knowledge()).run("分析日志", events=[
        {"timestamp_ms": 0, "direction": "TX", "hex_frame": "01 03 00 00 00 02 C4 0B"}])
    assert result["status"] == "completed"
    assert result["log_analysis"]["transactions"][0]["status"] == "pending"
    assert [x["tool"] for x in result["observations"]] == ["analyze_log", "search_docs"]


def test_missing_log_can_trigger_clarification():
    model = ScriptedLLM([{"action": "ask_user", "question": "请提供收发日志和双方串口配置。"}])
    result = ModbusAgent(model, Knowledge()).run("我的通信为什么超时")
    assert result["status"] == "needs_input"
    assert not result["observations"]


def test_finish_without_evidence_is_blocked():
    result = ModbusAgent(ScriptedLLM([{"action": "finish"}]), Knowledge()).run("故障是什么")
    assert result["status"] == "insufficient_evidence"


def test_duplicate_action_stops_without_extra_model_call():
    search = {"action": "search_docs", "query": "异常码02"}
    result = ModbusAgent(ScriptedLLM([search, search]), Knowledge()).run("异常码02是什么")
    assert result["status"] == "duplicate_action"


def test_budget_stops_unbounded_search():
    result = ModbusAgent(ScriptedLLM([{"action": "search_docs", "query": "异常码02"}]),
                         Knowledge(), max_steps=1).run("异常码02是什么")
    assert result["status"] == "budget_exhausted"


@pytest.mark.parametrize("reply", ["not json", '{"action":"shell"}', '{"action":"search_docs","query":""}',
                                    '{"action":"analyze_log","path":"secret"}', '[]'])
def test_invalid_action_never_executes(reply):
    with pytest.raises((ValueError, TypeError)):
        parse_action(reply)


def test_provider_error_does_not_leak_message():
    result = ModbusAgent(ScriptedLLM([RuntimeError("secret-credential")]), Knowledge()).run("异常码02")
    assert result["status"] == "decision_error"
    assert "secret-credential" not in json.dumps(result)


def test_invalid_log_is_tool_error_not_hallucinated_fact():
    result = ModbusAgent(ScriptedLLM([{"action": "analyze_log"}, {"action": "finish"}]),
                         Knowledge()).run("分析日志", events=[{"bad": "event"}])
    assert result["status"] == "insufficient_evidence"
    assert result["observations"][0]["error"] == "ValueError"
    assert result["log_analysis"] is None


def test_bad_final_citations_rejected():
    result = ModbusAgent(ScriptedLLM([{"action": "search_docs", "query": "异常码02"},
                                    {"action": "finish"}, "虚构证据 [D999]"]), Knowledge()).run("异常码02")
    assert result["status"] == "answer_error"


def test_empty_search_prevents_generated_answer():
    knowledge = SimpleNamespace(answer=lambda *args, **kwargs: {"citations": []})
    result = ModbusAgent(ScriptedLLM([{"action": "search_docs", "query": "未知"},
                                    {"action": "finish"}]), knowledge).run("未知")
    assert result["status"] == "insufficient_evidence"


def test_search_cannot_skip_provided_log_analysis():
    result = ModbusAgent(ScriptedLLM([{"action": "search_docs", "query": "超时"},
                                    {"action": "finish"}]), Knowledge()).run("分析日志", events=[])
    assert result["observations"][0]["error"] == "ValueError"
    assert result["status"] == "insufficient_evidence"


def test_duplicate_document_ids_keep_stable_citations():
    result = ModbusAgent(ScriptedLLM([{"action": "search_docs", "query": "异常码"},
                                    {"action": "search_docs", "query": "地址"},
                                    {"action": "finish"}, "参考 [D1]"]), Knowledge()).run("异常码02")
    assert result["status"] == "completed"
    assert len(result["citations"]) == 1


def test_invalid_decision_has_one_bounded_format_repair():
    model = ScriptedLLM(['{"action":"finish","answer":"untrusted"}',
                         {"action": "search_docs", "query": "异常码02"},
                         {"action": "finish"}, "参考 [D1]"])
    result = ModbusAgent(model, Knowledge()).run("异常码02")
    assert result["status"] == "completed"
    assert result["trace"][0]["format_repairs"] == 1


def test_two_invalid_decisions_stop_instead_of_looping():
    model = ScriptedLLM(["invalid", "still invalid"])
    result = ModbusAgent(model, Knowledge()).run("异常码02")
    assert result["status"] == "decision_error"
    assert not result["observations"]
