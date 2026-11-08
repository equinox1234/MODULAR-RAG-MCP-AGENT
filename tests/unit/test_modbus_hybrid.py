"""Hybrid retrieval mode: query expansion, weighted RRF, and mode plumbing."""

import json
from pathlib import Path

import pytest

from src.core.modbus_knowledge import ModbusKnowledge, _WeightedRRF
from src.core.types import RetrievalResult


def _write_corpus(tmp_path: Path) -> Path:
    corpus = {
        "version": "test",
        "sources": {
            "app": {"kind": "official_pdf", "title": "Protocol", "version": "1", "url": "u"},
            "guide": {"kind": "guide", "title": "Guide", "version": "1", "url": "u"},
        },
        "chunks": [
            {
                "id": "app-p1",
                "source": "app",
                "page": 1,
                "section": "Broadcast",
                "title": "Protocol / page 1",
                "kind": "text",
                "device": "generic",
                "text": "broadcast requests no response is returned from the slaves",
            },
            {
                "id": "app-p2",
                "source": "app",
                "page": 2,
                "section": "Addressing",
                "title": "Protocol / page 2",
                "kind": "text",
                "device": "generic",
                "text": "the address zero is reserved for broadcast framing",
            },
            {
                "id": "guide-1",
                "source": "guide",
                "page": 3,
                "section": "Notes",
                "title": "Guide / page 3",
                "kind": "text",
                "device": "VT-100",
                "text": "virtual device note about broadcast",
            },
        ],
    }
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    return path


def _knowledge(tmp_path, **kwargs):
    # Tests must not depend on the ambient config default: pin bm25 unless the
    # case explicitly exercises hybrid (or passes retrieval_mode=None).
    kwargs.setdefault("retrieval_mode", "bm25")
    return ModbusKnowledge(
        corpus_path=_write_corpus(tmp_path),
        index_dir=tmp_path / "bm25",
        **kwargs,
    )


class _FakeHybrid:
    """Stands in for the framework HybridSearch; records the queries it sees."""

    def __init__(self, results):
        self._results = results
        self.queries = []

    def search(self, query, top_k=None, **kwargs):
        self.queries.append(query)
        return self._results[: (top_k or len(self._results))]


# ============================================================================
# Mode selection
# ============================================================================

def test_explicit_mode_wins_over_settings(tmp_path):
    assert _knowledge(tmp_path, retrieval_mode="bm25").retrieval_mode == "bm25"


def test_missing_modbus_section_falls_back_to_bm25(tmp_path):
    """An old config without a `modbus` block must stay offline-capable."""
    from types import SimpleNamespace

    knowledge = _knowledge(tmp_path, retrieval_mode=None, settings=SimpleNamespace(modbus=None))
    assert knowledge.retrieval_mode == "bm25"


def test_mode_is_read_from_settings_when_not_given(tmp_path):
    from types import SimpleNamespace

    settings = SimpleNamespace(modbus=SimpleNamespace(retrieval_mode="hybrid", dense_top_k=20,
                                                      sparse_top_k=20, fusion_top_k=20,
                                                      hybrid_sparse_weight=1.0))
    knowledge = _knowledge(tmp_path, retrieval_mode=None, settings=settings)
    assert knowledge.retrieval_mode == "hybrid"


def test_explicit_mode_is_validated(tmp_path):
    with pytest.raises(ValueError, match="retrieval_mode"):
        _knowledge(tmp_path, retrieval_mode="semantic")


def test_hybrid_without_index_fails_with_actionable_message(tmp_path, monkeypatch):
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid")
    monkeypatch.setattr(
        "src.core.modbus_knowledge.dense_index_status",
        lambda corpus, settings: (False, "dense index is stale"),
    )
    with pytest.raises(ValueError) as excinfo:
        knowledge.retrieve("broadcast")
    assert "build_modbus_dense_index" in str(excinfo.value)
    assert "stale" in str(excinfo.value)


# ============================================================================
# Query expansion is shared by both paths
# ============================================================================

def test_expansion_normalises_exception_codes_and_adds_english_terms(tmp_path):
    knowledge = _knowledge(tmp_path)
    expanded = knowledge.expand_query("异常码02是什么意思")

    assert "exception code 0x02" in expanded
    assert "illegal data address" in expanded  # EXCEPTION_NAMES[2]
    assert "exception" in expanded


def test_query_processor_feeds_the_expanded_query_to_retrieval(tmp_path):
    from src.core.modbus_knowledge import _ModbusQueryProcessor

    knowledge = _knowledge(tmp_path)
    processed = _ModbusQueryProcessor(knowledge).process("广播")

    assert "broadcast" in processed.original_query
    assert processed.keywords
    assert processed.filters == {}


# ============================================================================
# Weighted RRF
# ============================================================================

def test_weighted_rrf_boosts_the_weighted_list():
    dense = [RetrievalResult(chunk_id="d1", score=1.0, text="a")]
    sparse = [RetrievalResult(chunk_id="s1", score=1.0, text="b")]

    equal = _WeightedRRF(k=60, dense_weight=1.0, sparse_weight=1.0).fuse([dense, sparse], top_k=2)
    boosted = _WeightedRRF(k=60, dense_weight=1.0, sparse_weight=2.0).fuse([dense, sparse], top_k=2)

    assert equal[0].score > 0
    assert boosted[0].chunk_id == "s1"
    assert boosted[0].score == pytest.approx(2.0 / 61)


def test_weighted_rrf_falls_back_to_plain_fuse_for_other_shapes():
    fusion = _WeightedRRF(k=60, dense_weight=1.0, sparse_weight=2.0)
    only = [RetrievalResult(chunk_id="a", score=1.0, text="x")]
    assert fusion.fuse([only], top_k=1)[0].chunk_id == "a"


# ============================================================================
# Hybrid candidates: re-ranking and provenance
# ============================================================================

def test_hybrid_candidates_use_corpus_records_not_retriever_payload(tmp_path):
    fake = _FakeHybrid([
        RetrievalResult(chunk_id="app-p2", score=1.0, text="WRONG TEXT", metadata={"page": 999}),
        RetrievalResult(chunk_id="app-p1", score=0.9, text="WRONG TEXT", metadata={}),
    ])
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", hybrid_search=fake)

    hits = knowledge.retrieve("address zero", top_k=2)

    assert [hit["id"] for hit in hits] == ["app-p2", "app-p1"]
    # Page/text come from the authoritative corpus, never from the retriever.
    assert hits[0]["page"] == 2
    assert "WRONG TEXT" not in hits[0]["text"]
    assert hits[0]["provenance"]["kind"] == "official_pdf"


def test_hybrid_candidates_apply_phrase_bonus(tmp_path):
    """A near-tied candidate matching a protocol phrase should win."""
    fake = _FakeHybrid([
        RetrievalResult(chunk_id="app-p2", score=1.0, text="", metadata={}),
        RetrievalResult(chunk_id="app-p1", score=0.96, text="", metadata={}),
    ])
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", hybrid_search=fake)

    hits = knowledge.retrieve("广播为什么没有响应", top_k=2)

    assert hits[0]["id"] == "app-p1"
    assert hits[0]["phrase_boost"] > 0


def test_hybrid_respects_device_scope(tmp_path):
    fake = _FakeHybrid([
        RetrievalResult(chunk_id="guide-1", score=1.0, text="", metadata={}),
        RetrievalResult(chunk_id="app-p1", score=0.9, text="", metadata={}),
    ])
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", hybrid_search=fake)

    generic_hits = knowledge.retrieve("broadcast", top_k=3)
    device_hits = knowledge.retrieve("broadcast", top_k=3, device="VT-100")

    assert "guide-1" not in [hit["id"] for hit in generic_hits]
    assert "guide-1" in [hit["id"] for hit in device_hits]


def test_hybrid_reports_mode_in_answer(tmp_path):
    knowledge = _knowledge(tmp_path, retrieval_mode="bm25")
    result = knowledge.answer("broadcast")
    assert result["retrieval"] == "bm25"


# ============================================================================
# Second-stage rerank (injected provider: no model calls)
# ============================================================================

class _FakeReranker:
    """Returns explicit per-id scores so tests can assert ordering and ties."""

    def __init__(self, scores, error=None):
        self._scores = scores
        self._error = error
        self.calls = []

    def rerank(self, query, candidates, **kwargs):
        self.calls.append((query, [c["id"] for c in candidates]))
        if self._error is not None:
            raise self._error
        ordered = []
        for candidate in candidates:
            item = dict(candidate)
            item["rerank_score"] = self._scores.get(candidate["id"], 0)
            ordered.append(item)
        ordered.sort(key=lambda item: item["rerank_score"], reverse=True)
        return ordered


def _fused_three():
    return _FakeHybrid([
        RetrievalResult(chunk_id="app-p2", score=1.0, text="", metadata={}),
        RetrievalResult(chunk_id="app-p1", score=0.9, text="", metadata={}),
        RetrievalResult(chunk_id="guide-1", score=0.8, text="", metadata={}),
    ])


def test_rerank_reorders_the_fused_candidates(tmp_path):
    reranker = _FakeReranker({"app-p2": 0.1, "app-p1": 3.0, "guide-1": 0.0})
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", rerank=True,
                           hybrid_search=_fused_three(), reranker=reranker)

    hits = knowledge.retrieve("broadcast", top_k=2)

    assert hits[0]["id"] == "app-p1"
    assert hits[0]["rerank_score"] == 3.0


def test_rerank_keeps_provider_order_for_ties(tmp_path):
    """Equal coarse scores must not fall back to chunk_id ordering."""
    reranker = _FakeReranker({"app-p2": 2.0, "app-p1": 2.0, "guide-1": 0.0})
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", rerank=True,
                           hybrid_search=_fused_three(), reranker=reranker)

    hits = knowledge.retrieve("broadcast", top_k=2)

    # Provider order was app-p2 then app-p1; sorting by id alone would flip it.
    assert [hit["id"] for hit in hits] == ["app-p2", "app-p1"]


def test_rerank_failure_falls_back_to_fused_order(tmp_path):
    reranker = _FakeReranker({}, error=RuntimeError("provider down"))
    knowledge = _knowledge(tmp_path, retrieval_mode="hybrid", rerank=True,
                           hybrid_search=_fused_three(), reranker=reranker)

    # "address zero" carries no protocol phrase, so the fused order is untouched.
    hits = knowledge.retrieve("address zero", top_k=3)

    assert [hit["id"] for hit in hits] == ["app-p2", "app-p1"]
    assert hits[0]["rerank_score"] is None


def test_rerank_is_not_called_in_bm25_mode(tmp_path):
    reranker = _FakeReranker({"app-p2": 3.0})
    knowledge = _knowledge(tmp_path, retrieval_mode="bm25", rerank=True, reranker=reranker)

    knowledge.retrieve("broadcast", top_k=2)

    assert reranker.calls == []
