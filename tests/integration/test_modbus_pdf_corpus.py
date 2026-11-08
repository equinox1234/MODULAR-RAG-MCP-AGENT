"""Local original-PDF integration checks; no API calls or generated model answers."""
import hashlib
import json

import pytest

from src.core.modbus_knowledge import ROOT, ModbusKnowledge

PROCESSED = ROOT / "data/modbus/processed"
pytestmark = pytest.mark.skipif(not (PROCESSED / "knowledge.json").exists(),
                                reason="Run python -m scripts.ingest_modbus_docs first")


@pytest.fixture(scope="module")
def knowledge():
    # Corpus invariants are offline: pin bm25 so this test never calls the
    # embedding API, regardless of the configured default mode.
    return ModbusKnowledge(retrieval_mode="bm25")


@pytest.mark.parametrize("query,source,page", [
    ("异常码02是什么意思", "application", 48),
    ("CRC低字节先发送吗", "serial", 15),
    ("广播地址0需要响应吗", "serial", 7),
    ("响应超时timeout", "serial", 10),
    ("03读取保持寄存器的数量", "application", 15),
    ("PDU寄存器地址从0开始吗", "application", 7),
])
def test_chinese_question_finds_expected_original_page(knowledge, query, source, page):
    assert (source, page) in [(hit["source"], hit.get("page")) for hit in knowledge.retrieve(query)]


def test_every_pdf_chunk_is_an_exact_page_substring(knowledge):
    pages = [json.loads(line) for line in (PROCESSED / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    lookup = {(page["source"], page["page"]): page for page in pages}
    assert len(lookup) == 94
    for chunk in knowledge.chunks.values():
        source = knowledge.sources[chunk["source"]]
        if source["kind"] != "official_pdf":
            continue
        page = lookup[chunk["source"], chunk["page"]]
        if chunk.get("kind") == "table":
            # Tables are re-rendered from extracted cells, so they are not a
            # substring of the page text and carry no character offsets.
            assert chunk["start_offset"] is None and chunk["end_offset"] is None
            assert chunk["text"].strip()
            continue
        assert chunk["text"] == page["text"][chunk["start_offset"]:chunk["end_offset"]]
        assert page["sha256"] == source["sha256"]
    for source in knowledge.sources.values():
        if source["kind"] == "official_pdf":
            assert hashlib.sha256(__import__('pathlib').Path(source["local_path"]).read_bytes()).hexdigest() == source["sha256"]


def test_repeated_headers_and_footers_are_removed(knowledge):
    report = json.loads((PROCESSED / "ingestion_report.json").read_text(encoding="utf-8"))

    for stats in report["header_footer"]["per_source"].values():
        assert stats["removed_header_footer_lines"] > 0
    # Both official PDFs stamp this URL on every page; it must not be indexed.
    assert not any("http://www.modbus.org" in chunk["text"].lower()
                   for chunk in knowledge.chunks.values())


def test_tables_are_indexed_as_rows(knowledge):
    tables = [chunk for chunk in knowledge.chunks.values() if chunk.get("kind") == "table"]
    assert len(tables) >= 40, "the exception-code and PDU tables must be indexed"

    # The exception-code table on page 48 must expose code 02 as its own row,
    # which plain text extraction interleaved with prose.
    page_48 = [chunk for chunk in tables if chunk["source"] == "application" and chunk["page"] == 48]
    assert page_48
    assert any("02 | ILLEGAL DATA ADDRESS" in chunk["text"] for chunk in page_48)


def test_text_chunks_start_at_section_headings(knowledge):
    chunks = [chunk for chunk in knowledge.chunks.values()
              if knowledge.sources[chunk["source"]]["kind"] == "official_pdf"
              and chunk.get("kind") != "table"]
    with_heading = [chunk for chunk in chunks if chunk["section"] and chunk["section"] != f"PDF page {chunk['page']}"]
    assert len(with_heading) >= len(chunks) // 2
    # No chunk may be nothing but a bare heading: those merge into a neighbour.
    assert not any(len(chunk["text"].strip()) < 20 for chunk in chunks)


def test_answer_cites_local_pdf_page(knowledge):
    result = knowledge.answer("异常码02是什么意思")
    for citation in result["citations"]:
        assert citation["kind"] == "official_pdf"
        assert citation["page"] > 0
        assert citation["local_path"].endswith(".pdf")
        assert citation["text"]


def test_cached_index_is_loaded_without_rebuilding(knowledge, monkeypatch):
    def unexpected_build(*args, **kwargs):
        raise AssertionError("Unchanged corpus must reuse index")
    monkeypatch.setattr("src.core.modbus_knowledge.BM25Indexer.build", unexpected_build)
    assert ModbusKnowledge(retrieval_mode="bm25").retrieve("异常码02")
