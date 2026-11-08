"""Stable identifiers shared by ingestion, retrieval, and deletion.

Two different identifiers describe a document and they must not be confused:

``document_scope(source_path)``
    Short, path-derived prefix.  Every chunk ID of that file starts with it,
    so it is the key used to remove *stale* chunks when a file at the same
    path is re-ingested with different content.

``doc_hash`` (SHA-256 of file bytes)
    Content identity, computed by the integrity checker.  It changes whenever
    the file changes, so it is used for deduplication and image ownership, not
    for prefix-style deletion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def document_scope(source_path: str | Path) -> str:
    """Return the chunk-ID prefix for a document.

    The value is derived from the source path *exactly as stored in chunk
    metadata* (no resolution or normalisation), so existing chunk IDs and
    BM25 postings keep matching after this helper was introduced.

    Args:
        source_path: The ``source_path`` recorded on chunks for this document.

    Returns:
        First 8 hex characters of ``SHA256(source_path)``.
    """
    return hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:8]
