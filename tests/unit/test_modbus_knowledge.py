import json
from types import SimpleNamespace

import pytest

from src.core.modbus_knowledge import ROOT, ModbusKnowledge

# data/ is gitignored, so a clean checkout (CI) has no legacy corpus.
pytestmark = pytest.mark.skipif(
    not (ROOT / "data/modbus/knowledge.json").exists(),
    reason="Legacy Modbus corpus not present (data/ is gitignored)",
)


@pytest.fixture
def knowledge(tmp_path):
    # Pin the mode: the default now follows config (hybrid) and this test uses
    # the legacy summaries corpus, which has no dense index of its own.
    return ModbusKnowledge(
        corpus_path=ROOT / "data/modbus/knowledge.json",
        index_dir=tmp_path,
        retrieval_mode="bm25",
    )


CASES = json.loads((ROOT / "tests/fixtures/modbus_retrieval_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES)
def test_domain_retrieval_smoke(knowledge, case):
    hits = knowledge.retrieve(case["question"], device=case.get("device"))
    assert case["expected"] in [h["id"] for h in hits]


def test_citations_preserve_provenance(knowledge):
    result = knowledge.answer("异常码02是什么意思")
    assert result["mode"] == "extractive"
    assert result["citations"][0]["chunk_id"] == "app-exception"
    assert result["citations"][0]["url"].startswith("https://www.modbus.org/")
    assert "[D1]" in result["answer"]


def test_fictional_device_requires_explicit_scope(knowledge):
    assert all(h["device"] == "generic" for h in knowledge.retrieve("温度串口倍率VT-100"))
    assert any(h["device"] == "VT-100" for h in knowledge.retrieve("温度倍率", device="VT-100"))


def test_unrelated_question_refused(knowledge):
    result = knowledge.answer("火星香蕉巧克力")
    assert result["mode"] == "insufficient_evidence"
    assert not result["citations"]


def test_log_evidence_connected_to_retrieval(knowledge):
    events = json.loads((ROOT / "tests/fixtures/modbus_simulated_log.json").read_text(encoding="utf-8"))
    result = knowledge.answer("帮我分析", events=events)
    assert any("timeout" in fact for fact in result["log_facts"])
    assert any(c["chunk_id"] == "serial-timeout" for c in result["citations"])
    assert result["log_analysis"]["transactions"][-1]["status"] == "pending"


def test_model_adapter_receives_evidence(knowledge):
    class FakeLLM:
        def chat(self, messages):
            assert "app-exception" in messages[-1].content
            return SimpleNamespace(content="异常码02表示数据地址不合法。[D1]")
    assert knowledge.answer("异常码02", llm=FakeLLM())["mode"] == "llm"


@pytest.mark.parametrize("answer", ["没有引用", "结论 [D999]", "只有日志 [L0]"])
def test_invalid_model_citations_rejected(knowledge, answer):
    fake = SimpleNamespace(chat=lambda messages: SimpleNamespace(content=answer))
    with pytest.raises(ValueError, match="citations"):
        knowledge.answer("异常码02", llm=fake)


@pytest.mark.parametrize("query,k", [("", 3), ("CRC", 0), ("CRC", 11), ("CRC", True)])
def test_bad_query(knowledge, query, k):
    with pytest.raises(ValueError):
        knowledge.retrieve(query, k)
