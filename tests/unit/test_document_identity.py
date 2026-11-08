"""Document identity: chunk IDs, stale-chunk cleanup, and collection-scoped skip."""

import sqlite3
from unittest.mock import Mock, patch

import pytest

from src.core.ids import document_scope
from src.core.query_engine.query_processor import QueryProcessor
from src.core.settings import Settings
from src.core.types import Chunk
from src.ingestion.storage.vector_upserter import VectorUpserter
from src.libs.loader.file_integrity import SQLiteIntegrityChecker

# ============================================================================
# document_scope / chunk IDs
# ============================================================================

def _chunk(source_path="data/documents/test.pdf", index=0, text="hello world"):
    return Chunk(
        id="tmp",
        text=text,
        metadata={"source_path": source_path, "chunk_index": index},
    )


@pytest.fixture
def upserter():
    settings = Mock(spec=Settings)
    settings.vector_store = Mock()
    store = Mock()
    store.upsert = Mock()
    store.delete_by_metadata = Mock(return_value=2)
    with patch("src.ingestion.storage.vector_upserter.VectorStoreFactory") as factory:
        factory.create.return_value = store
        yield VectorUpserter(settings), store


def test_chunk_id_starts_with_document_scope(upserter):
    up, _ = upserter
    chunk = _chunk()
    assert up._generate_chunk_id(chunk).startswith(document_scope(chunk.metadata["source_path"]))


def test_upsert_records_doc_scope_so_stale_chunks_can_be_found(upserter):
    up, store = upserter
    up.upsert([_chunk()], [[0.1, 0.2]])
    record = store.upsert.call_args[0][0][0]
    chunk = _chunk()
    assert record["metadata"]["doc_scope"] == document_scope(chunk.metadata["source_path"])
    assert record["metadata"]["chunk_id"] == record["id"]


def test_delete_document_removes_both_new_and_legacy_layouts(upserter):
    up, store = upserter
    deleted = up.delete_document("data/documents/test.pdf")
    filters = [call[0][0] for call in store.delete_by_metadata.call_args_list]
    assert {"doc_scope": document_scope("data/documents/test.pdf")} in filters
    assert {"source_path": "data/documents/test.pdf"} in filters
    assert deleted == 4  # 2 per filter


def test_delete_document_failure_does_not_raise(upserter):
    up, store = upserter
    store.delete_by_metadata.side_effect = RuntimeError("chroma down")
    assert up.delete_document("data/documents/test.pdf") == 0


# ============================================================================
# FileIntegrityChecker: same bytes may live in several collections
# ============================================================================

@pytest.fixture
def checker(tmp_path):
    return SQLiteIntegrityChecker(str(tmp_path / "integrity.db"))


def test_skip_is_scoped_to_collection(checker):
    checker.mark_success("hash-1", "/a.pdf", collection="alpha")
    assert checker.should_skip("hash-1", "alpha") is True
    # The same file must still be ingestible into another collection.
    assert checker.should_skip("hash-1", "beta") is False
    # Callers that do not track collections keep the old any-collection rule.
    assert checker.should_skip("hash-1") is True


def test_two_collections_are_recorded_separately(checker):
    checker.mark_success("hash-1", "/a.pdf", collection="alpha")
    checker.mark_success("hash-1", "/a.pdf", collection="beta")
    assert len(checker.list_processed()) == 2
    assert checker.list_processed("beta")[0]["collection"] == "beta"


def test_failure_is_scoped_to_collection(checker):
    checker.mark_success("hash-1", "/a.pdf", collection="alpha")
    checker.mark_failed("hash-1", "/a.pdf", "boom", collection="beta")
    assert checker.should_skip("hash-1", "alpha") is True
    assert checker.should_skip("hash-1", "beta") is False


def test_remove_record_can_target_one_collection(checker):
    checker.mark_success("hash-1", "/a.pdf", collection="alpha")
    checker.mark_success("hash-1", "/a.pdf", collection="beta")
    assert checker.remove_record("hash-1", "alpha") is True
    assert checker.should_skip("hash-1", "alpha") is False
    assert checker.should_skip("hash-1", "beta") is True


def test_legacy_database_is_migrated(tmp_path):
    """A database created with the old file_hash-only primary key keeps its rows."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE ingestion_history (
            file_hash TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL,
            collection TEXT,
            error_msg TEXT,
            processed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO ingestion_history VALUES (?, ?, 'success', NULL, NULL, ?, ?)",
        ("legacy-hash", "/legacy.pdf", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    checker = SQLiteIntegrityChecker(str(db_path))

    assert checker.list_processed()[0]["file_hash"] == "legacy-hash"
    # Legacy NULL collection became '', so the composite key stays unique.
    assert checker.should_skip("legacy-hash") is True
    assert checker.should_skip("legacy-hash", "") is True
    assert checker.should_skip("legacy-hash", "other") is False


# ============================================================================
# QueryProcessor: filters must not swallow URLs, times, or paths
# ============================================================================

@pytest.mark.parametrize(
    "query",
    [
        "https://dashscope.aliyuncs.com/compatible-mode/v1 是什么",
        "错误发生在 10:00:00 左右",
        r"文件在 C:\data\docs\a.pdf 里",
    ],
)
def test_non_filter_colon_spans_stay_in_query(query):
    result = QueryProcessor().process(query)
    assert result.filters == {}
    assert result.keywords, "the specific part of the query must stay searchable"


def test_explicit_filters_are_still_parsed():
    result = QueryProcessor().process("collection:docs type:pdf 如何配置")
    assert result.filters == {"collection": "docs", "doc_type": "pdf"}
    assert "collection" not in result.keywords
    assert "docs" not in result.keywords


# ============================================================================
# Pipeline: identity propagation and stale-chunk cleanup
# ============================================================================

def _fake_pipeline():
    from unittest.mock import MagicMock

    from src.core.types import Chunk, Document
    from src.ingestion.pipeline import IngestionPipeline

    class FakePipeline:
        collection = "test"
        force = True

    fp = FakePipeline()
    fp.integrity_checker = MagicMock()
    fp.integrity_checker.compute_sha256.return_value = "hash123"
    fp.integrity_checker.should_skip.return_value = False

    fp.loader = MagicMock()
    fp.loader.load.return_value = Document(
        id="doc1",
        text="Hello world. " * 50,
        metadata={"source_path": "test.pdf", "images": []},
    )

    chunks = [
        Chunk(id=f"c{i}", text=f"Chunk {i} text. " * 5, metadata={"source_path": "test.pdf"})
        for i in range(3)
    ]
    fp.chunk_refiner = MagicMock()
    fp.chunk_refiner.transform.return_value = chunks
    fp.metadata_enricher = MagicMock()
    fp.metadata_enricher.transform.return_value = chunks
    fp.image_captioner = MagicMock()
    fp.image_captioner.transform.return_value = chunks
    fp.chunker = MagicMock()
    fp.chunker.split_document.return_value = chunks

    batch_result = MagicMock()
    batch_result.dense_vectors = [[0.1, 0.2]] * 3
    batch_result.sparse_stats = [{"chunk_id": f"c{i}", "doc_length": 3} for i in range(3)]
    fp.batch_processor = MagicMock()
    fp.batch_processor.process.return_value = batch_result

    fp.vector_upserter = MagicMock()
    fp.vector_upserter.delete_document.return_value = 2
    fp.vector_upserter.upsert.return_value = ["v0", "v1", "v2"]
    fp.bm25_indexer = MagicMock()
    fp.image_storage = MagicMock()
    return IngestionPipeline, fp, chunks


def test_pipeline_propagates_document_identity_and_cleans_stale_chunks():
    pipeline_cls, fp, chunks = _fake_pipeline()

    result = pipeline_cls.run(fp, "test.pdf")

    assert result.success is True
    scope = document_scope("test.pdf")
    for chunk in chunks:
        assert chunk.metadata["doc_hash"] == "hash123"
        assert chunk.metadata["doc_scope"] == scope

    # Old chunks from a previous ingestion of the same path are removed first.
    fp.vector_upserter.delete_document.assert_called_once_with("test.pdf", None)
    # BM25 receives the ID prefix that actually matches its postings.
    assert fp.bm25_indexer.add_documents.call_args.kwargs["doc_id"] == scope
    assert fp.integrity_checker.mark_success.call_args.args == ("hash123", "test.pdf", "test")
    assert result.stages["storage"]["stale_vectors_removed"] == 2


def test_pipeline_failure_records_failure_without_name_error():
    pipeline_cls, fp, _ = _fake_pipeline()
    fp.loader.load.side_effect = RuntimeError("pdf exploded")

    result = pipeline_cls.run(fp, "test.pdf")

    assert result.success is False
    assert "pdf exploded" in result.error
    fp.integrity_checker.mark_failed.assert_called_once_with(
        "hash123", "test.pdf", "pdf exploded", collection="test"
    )


def test_pipeline_failure_before_hash_does_not_record():
    pipeline_cls, fp, _ = _fake_pipeline()
    fp.integrity_checker.compute_sha256.side_effect = FileNotFoundError("gone")

    result = pipeline_cls.run(fp, "missing.pdf")

    assert result.success is False
    assert result.doc_id is None
    fp.integrity_checker.mark_failed.assert_not_called()
