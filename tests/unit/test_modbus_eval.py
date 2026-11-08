import json
from types import SimpleNamespace

from src.core.modbus_knowledge import ROOT
from src.core.modbus_log import analyze_rtu_log
from src.observability.evaluation.modbus_eval import MeteredLLM, evidence_matches, score_agent, score_retrieval


def test_page_alone_does_not_establish_evidence_match():
    assert not evidence_matches({"source": "serial", "page": 7, "text": "unrelated text"},
                                {"source": "serial", "page": 7, "anchor": "broadcast"})


def test_reciprocal_rank_and_miss():
    case = {"evidence": [{"source": "serial", "page": 7, "anchor": "broadcast"}]}
    hits = [{"source": "application", "page": 7, "text": "broadcast"},
            {"source": "serial", "page": 7, "text": "broadcast"}]
    assert score_retrieval(case, hits)["reciprocal_rank"] == 0.5
    assert score_retrieval(case, [])["evidence_hit_at_k"] is False


def test_scope_only_has_no_fabricated_retrieval_metric():
    result = score_retrieval({"scope_only": True, "forbid_kinds": ["synthetic"]},
                             [{"kind": "synthetic"}])
    assert result == {"scope_ok": False}


def test_agent_checks_do_not_assign_semantic_accuracy():
    result = score_agent({"expected_status": ["needs_input"], "required_tools": []},
                          {"status": "needs_input", "answer": "补充日志", "observations": []})
    assert result["mechanical_pass"]
    assert result["human_review"]["status"] == "pending"
    assert result["human_review"]["factual_correctness"] is None


def test_failed_tools_do_not_count_as_successful_calls():
    result = score_agent({"expected_status": ["completed"], "required_tools": ["analyze_log"]},
                          {"status": "completed", "observations": [{"tool": "analyze_log", "error": "ValueError"}]})
    assert not result["checks"]["required_tools_in_order"]
    assert not result["mechanical_pass"]


def test_required_tool_order_matters():
    result = score_agent({"expected_status": ["needs_input"], "required_tools": ["analyze_log", "search_docs"]},
                          {"status": "needs_input", "observations": [{"tool": "search_docs"}, {"tool": "analyze_log"}]})
    assert not result["mechanical_pass"]


def test_actual_call_and_usage_meter():
    llm = MeteredLLM(SimpleNamespace(chat=lambda: SimpleNamespace(usage={"total_tokens": 12})))
    llm.chat()
    llm.chat()
    assert llm.calls == 2
    assert llm.usage == {"total_tokens": 24}


def test_frozen_log_inputs_match_labels():
    suite = json.loads((ROOT / "tests/fixtures/modbus_eval_v1.json").read_text(encoding="utf-8"))
    assert len({c["id"] for c in suite["agent_cases"] + suite["retrieval_cases"]}) == 18
    for case in suite["agent_cases"]:
        if "events" not in case:
            continue
        analysis = analyze_rtu_log(case["events"])
        assert [x["status"] for x in analysis["transactions"]] == case["transaction_statuses"]
        assert [x["kind"] for x in analysis["issues"]] == case.get("issue_kinds", [])
