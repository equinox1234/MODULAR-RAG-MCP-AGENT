"""Dense index for the Modbus corpus, built on the framework's storage stack.

The BM25 index lives in ``data/db/bm25/modbus_domain`` and needs no network.
Dense retrieval needs vectors, so this module builds a Chroma collection with
the configured embedding provider:

    python -m scripts.build_modbus_dense_index [--force]

A fingerprint file records which corpus + embedding model produced the index,
so ``ModbusKnowledge`` can fail with a clear message instead of silently
searching stale vectors.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.core.settings import Settings, load_settings, resolve_path

COLLECTION_NAME = "modbus_domain"
FINGERPRINT_FILENAME = "modbus_domain.sha256"


def _fingerprint(corpus_path: Path, settings: Settings) -> str:
    """Identity of the indexed data: corpus bytes + collection + embedding model."""
    digest = hashlib.sha256()
    digest.update(corpus_path.read_bytes())
    model = settings.embedding.model
    digest.update(f"|{COLLECTION_NAME}|{settings.embedding.provider}|{model}".encode())
    return digest.hexdigest()


def fingerprint_path() -> Path:
    """Path of the fingerprint file next to the Chroma database."""
    return resolve_path("data/db/chroma") / FINGERPRINT_FILENAME


def dense_index_status(
    corpus_path: Path, settings: Settings
) -> tuple[bool, str]:
    """Check whether the dense index matches *corpus_path*.

    Args:
        corpus_path: Path to the corpus used for retrieval.
        settings: Settings providing the embedding model identity.

    Returns:
        ``(ready, reason)``; *reason* is ``"ok"`` when ready.
    """
    path = fingerprint_path()
    if not path.is_file():
        return False, "dense index has not been built"
    expected = _fingerprint(corpus_path, settings)
    actual = path.read_text(encoding="utf-8").strip()
    if actual != expected:
        return False, "dense index is stale (corpus or embedding model changed)"
    return True, "ok"


def build_dense_index(
    corpus_path: Path | None = None,
    settings: Settings | None = None,
    *,
    batch_size: int = 20,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Embed every chunk of the corpus and upsert it into Chroma.

    Args:
        corpus_path: Corpus JSON. Defaults to ``data/modbus/processed/knowledge.json``.
        settings: Application settings. Loaded from the default config if omitted.
        batch_size: Chunks per embedding request. DashScope's compatible-mode
            embeddings endpoint rejects batches larger than 20.
        force: Clear the collection before writing (full rebuild).
        progress: Optional ``(done, total)`` callback.

    Returns:
        Report with chunk count, dimension, batch count and elapsed time.

    Raises:
        ValueError: If the corpus is missing/empty or the embedding response is
            inconsistent with the input size.
    """
    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory

    settings = settings or load_settings()
    corpus_path = corpus_path or resolve_path("data/modbus/processed/knowledge.json")
    if not corpus_path.exists():
        raise ValueError("Domain corpus not built. Run python -m scripts.ingest_modbus_docs")

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    chunks: list[dict[str, Any]] = corpus.get("chunks") or []
    if not chunks:
        raise ValueError("Empty knowledge corpus")

    embedding = EmbeddingFactory.create(settings)
    store = VectorStoreFactory.create(settings, collection_name=COLLECTION_NAME)
    if force:
        store.clear()

    started = time.perf_counter()
    dimension = 0
    batches = 0
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset:offset + batch_size]
        vectors = embedding.embed([chunk["text"] for chunk in batch])
        if len(vectors) != len(batch):
            raise ValueError(
                f"Embedding count mismatch: expected {len(batch)}, got {len(vectors)}"
            )
        dimension = len(vectors[0])
        records = []
        for chunk, vector in zip(batch, vectors):
            metadata = {
                key: value
                for key, value in chunk.items()
                if key != "text" and value is not None
            }
            metadata["text"] = chunk["text"]  # ChromaStore stores this as the document
            records.append({"id": chunk["id"], "vector": vector, "metadata": metadata})
        store.upsert(records)
        batches += 1
        if progress is not None:
            progress(min(offset + batch_size, len(chunks)), len(chunks))

    fingerprint_path().parent.mkdir(parents=True, exist_ok=True)
    fingerprint_path().write_text(
        _fingerprint(corpus_path, settings), encoding="utf-8"
    )

    return {
        "collection": COLLECTION_NAME,
        "chunks": len(chunks),
        "dimension": dimension,
        "batches": batches,
        "batch_size": batch_size,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "embedding_provider": settings.embedding.provider,
        "embedding_model": settings.embedding.model,
        "corpus": str(corpus_path),
        "force": force,
    }
