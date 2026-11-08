import json

import pytest

from src.core.modbus_agent import ModbusAgent, simple_document_question
from tests.unit.test_modbus_agent import Knowledge, ScriptedLLM


def test_simple_question_uses_one_generation_call_in_langgraph():
    model = ScriptedLLM(["异常码02表示非法数据地址。[D1]"])
    state = ModbusAgent(model, Knowledge()).run("Modbus异常码02是什么意思", execution_mode="auto")
    assert state["status"] == "completed"
    assert state["execution_path"] == "simple_document"
    assert len(model.prompts) == 1
    assert [x["node"] for x in state["trace"]] == ["route", "tools", "respond"]


def test_empty_evidence_does_not_call_model():
    knowledge = Knowledge()
    knowledge.answer = lambda *a, **kw: {"citations": []}
    model = ScriptedLLM([])
    state = ModbusAgent(model, knowledge).run("Modbus异常码02是什么意思", execution_mode="auto")
    assert state["status"] == "insufficient_evidence"
    assert not model.prompts


@pytest.mark.parametrize("question,events", [
    ("我的Modbus设备为什么超时", None), ("解释Modbus功能码03", []),
    ("请定位现场故障根因", None), ("请排查Modbus通信", None)])
def test_uncertain_or_log_tasks_keep_full_agent(question, events):
    assert not simple_document_question(question, events)


def test_decision_gets_preview_and_answer_gets_one_copy_of_evidence():
    evidence = "BEGIN_EVIDENCE_" + "x" * 1000 + "_END_EVIDENCE"
    knowledge = Knowledge()
    knowledge.answer = lambda *a, **kw: {"citations": [{"id": "D1", "chunk_id": "one", "page": 48,
                                                      "kind": "official_pdf", "text": evidence}]}
    model = ScriptedLLM([{"action": "search_docs", "query": "q"}, {"action": "finish"}, "解释 [D1]"])
    result = ModbusAgent(model, knowledge).run("复杂问题", execution_mode="agent")
    assert result["status"] == "completed"
    assert "_END_EVIDENCE" not in model.prompts[1][-1].content
    assert evidence in result["observations"][0]["documents"][0]["text"]
    assert model.prompts[-1][-1].content.count(evidence) == 1
    context = json.loads(model.prompts[-1][-1].content)
    assert "text" not in context["observations"][0]["documents"][0]


# ============================================================================
# Decision preview must expose protocol code rows (Q-5)
# ============================================================================

def test_preview_includes_a_code_row_beyond_the_head():
    from src.core.modbus_agent import CODE_ROW_WINDOW, PREVIEW_CHARS, document_preview

    text = ("header line\n" * 20) + "02 | ILLEGAL DATA ADDRESS | The data address is not allowed.\n" + ("tail\n" * 20)
    preview = document_preview({"text": text})

    assert "02 | ILLEGAL DATA ADDRESS" in preview
    # Still bounded: head + one window, not the whole chunk.
    assert len(preview) <= PREVIEW_CHARS + CODE_ROW_WINDOW + 5
    assert len(preview) < len(text)


def test_preview_stays_a_head_when_there_is_no_code_row():
    from src.core.modbus_agent import PREVIEW_CHARS, document_preview

    text = "plain prose without any table rows. " * 40
    assert document_preview({"text": text}) == text[:PREVIEW_CHARS]


def test_short_document_is_not_truncated():
    from src.core.modbus_agent import document_preview

    assert document_preview({"text": "short"}) == "short"


def test_decision_prompt_shows_the_exception_code_row():
    """Regression for Q-5: the planner must see code 02, not only code 01."""
    evidence = ("01 ILLEGAL FUNCTION " + "x" * 400 + "\n"
                "02 ILLEGAL DATA ADDRESS The data address received is not allowed.\n")
    knowledge = Knowledge()
    knowledge.answer = lambda *a, **kw: {"citations": [{"id": "D1", "chunk_id": "p48", "page": 48,
                                                      "kind": "official_pdf", "text": evidence}]}
    model = ScriptedLLM([{"action": "search_docs", "query": "异常码02"}, {"action": "finish"}, "解释 [D1]"])

    ModbusAgent(model, knowledge).run("复杂问题", execution_mode="agent")

    decision_context = json.loads(model.prompts[1][-1].content)
    preview = decision_context["observations"][0]["documents"][0]["preview"]
    assert "02 ILLEGAL DATA ADDRESS" in preview
    assert "text" not in decision_context["observations"][0]["documents"][0]
