"""Page-preserving ingestion of local official Modbus PDFs.

The corpus is the retrieval substrate, so the extractor does three things
beyond a plain ``extract_text`` dump:

1. **Drops repeated headers/footers** – both official PDFs stamp a title line
   and a date/URL/page-number line on every page.  Left in, they dominate term
   frequencies and BM25 IDF for no retrieval value.
2. **Splits by in-page headings** – numbered sections ("6.3 03 (0x03) Read
   Holding Registers") become chunk boundaries, so a chunk talks about one
   topic and citations can name the section.
3. **Keeps tables as rendered rows** – ``extract_tables`` output is rendered one
   row per line ("01 | ILLEGAL FUNCTION | ...").  The plain text extraction
   interleaves table cells with prose and loses row structure, which is exactly
   what protocol questions ask about.

Everything stays offline: no model calls, no network.  Offsets of text chunks
remain exact page substrings so citations can point at the original page.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

# --- chunking -------------------------------------------------------------
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 250
MIN_CHUNK_CHARS = 120

# --- header / footer detection -------------------------------------------
# Section headings include the function-code form "6.3 03 (0x03) Read Holding
# Registers", which a plain "number + letter" pattern would miss.
HEADING_LINE = re.compile(
    r"^\d+(?:\.\d+)*\s+(?:\d+\s+)?(?:\(0x[0-9A-Fa-f]+\)\s+)?[A-Za-z].*$",
    re.MULTILINE,
)
TOC_DOTS = re.compile(r"\.{3,}")
HEADING_MAX_WORDS = 7
HEADING_MAX_CHARS = 60
REPEAT_LINE_RATIO = 0.5
REPEAT_LINE_MIN_PAGES = 8
EDGE_LINES = 3
# Pages shorter than this are almost entirely "edge", so a repeated body line
# on such a page would be misread as a header/footer.
MIN_PAGE_LINES_FOR_EDGES = 8

# --- table extraction -----------------------------------------------------
TABLE_MIN_ROWS = 3
TABLE_MIN_CELLS = 4
TABLE_MIN_CHARS = 80


def split_page(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Return exact substrings and offsets, never crossing a PDF page boundary."""
    if not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < size")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        if text[start:end].strip():
            yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


# ---------------------------------------------------------------------------
# Header / footer removal
# ---------------------------------------------------------------------------

def normalize_line(line: str) -> str:
    """Normalise a line so page numbers and dates compare equal across pages."""
    key = re.sub(r"\d+", "#", line.strip().lower())
    key = re.sub(r"\s+", " ", key)
    return key.strip(" .-|_")


def repeated_line_keys(
    page_texts: list[str],
    *,
    ratio: float = REPEAT_LINE_RATIO,
    min_pages: int = REPEAT_LINE_MIN_PAGES,
    edge: int = EDGE_LINES,
) -> set[str]:
    """Keys of lines stamped on most pages **near the top or bottom edge**.

    The edge requirement is what separates a running header from a word that
    merely appears often ("request", "error", "response" all repeat across
    mid-page table cells and must be kept).
    """
    present: Counter[str] = Counter()
    near_edge: Counter[str] = Counter()
    usable_pages = 0

    for text in page_texts:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        usable_pages += 1
        present.update({normalize_line(line) for line in lines} - {""})
        if len(lines) >= MIN_PAGE_LINES_FOR_EDGES:
            near_edge.update(
                {normalize_line(line) for line in lines[:edge] + lines[-edge:]} - {""}
            )

    if usable_pages < min_pages:
        return set()

    threshold = max(min_pages, math.ceil(usable_pages * ratio))
    return {
        key
        for key, count in present.items()
        if count >= threshold
        and near_edge.get(key, 0) >= threshold
        and len(key) >= 8
    }


def clean_page_text(
    text: str, repeated: set[str]
) -> tuple[str, list[str], list[str]]:
    """Drop running headers/footers and table-of-contents lines from one page.

    TOC lines ("1 Introduction ........ 2") are navigation, not answers; they
    were matching questions and crowding the top hits on the first page.

    Returns:
        ``(cleaned_text, removed_footer_lines, removed_toc_lines)``.
    """
    kept: list[str] = []
    removed_footer: list[str] = []
    removed_toc: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if normalize_line(stripped) in repeated:
            removed_footer.append(stripped)
            continue
        if TOC_DOTS.search(stripped):
            removed_toc.append(stripped)
            continue
        kept.append(line)
    return "\n".join(kept), removed_footer, removed_toc


# ---------------------------------------------------------------------------
# Section-aware chunking
# ---------------------------------------------------------------------------

def is_heading(line: str) -> bool:
    """True for a real numbered heading, not a table row starting with a number.

    Linearised table rows ("01 ILLEGAL FUNCTION The function code received in
    the query is not an ...") also start with digits, so the shape alone is not
    enough.  Real headings in these documents are short, unpadded, and contain
    no sentence tail.
    """
    stripped = line.strip()
    if not HEADING_LINE.match(stripped) or TOC_DOTS.search(stripped):
        return False
    first_token = stripped.split()[0]
    if first_token.startswith("0"):
        return False  # zero-padded codes are exception/function codes
    return (
        len(stripped.split()) <= HEADING_MAX_WORDS
        and len(stripped) <= HEADING_MAX_CHARS
    )


def section_spans(text: str) -> list[tuple[int, int, str | None]]:
    """Split *text* at numbered headings into ``(start, end, heading)`` spans."""
    starts: list[tuple[int, str]] = []
    for match in HEADING_LINE.finditer(text):
        line = match.group(0)
        if not is_heading(line):
            continue
        starts.append((match.start(), " ".join(line.split())))

    if not starts:
        return [(0, len(text), None)]

    spans: list[tuple[int, int, str | None]] = []
    if starts[0][0] > 0:
        spans.append((0, starts[0][0], None))
    for index, (start, heading) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        spans.append((start, end, heading))

    # A tiny preamble is page furniture, not a section: fold it into the first
    # real section so it does not become a stub chunk of its own.
    if (
        len(spans) > 1
        and spans[0][2] is None
        and spans[0][1] - spans[0][0] < MIN_CHUNK_CHARS
    ):
        _, first_end, first_heading = spans[1]
        spans = [(0, first_end, first_heading)] + spans[2:]
    return spans


def _is_heading_only(snippet: str) -> bool:
    """True when a span contains nothing but one numbered heading line."""
    lines = [line for line in snippet.splitlines() if line.strip()]
    return len(lines) == 1 and is_heading(lines[0])


def page_chunk_spans(text: str) -> list[tuple[int, int, str | None]]:
    """Chunk spans for one cleaned page: sections first, then size windows.

    Undersized fragments are merged with a neighbour so a bare parent heading
    ("1 Introduction" followed by "1.1 Scope") never becomes its own chunk:

    * heading-only fragments merge **forward** into the subsection they title;
    * other fragments merge **backward** into the preceding chunk.
    """
    spans: list[tuple[int, int, str | None]] = []
    for section_start, section_end, heading in section_spans(text):
        section_text = text[section_start:section_end]
        if not section_text.strip():
            continue
        for start, end, _ in split_page(section_text):
            spans.append((section_start + start, section_start + end, heading))

    max_join = CHUNK_SIZE + CHUNK_OVERLAP
    merged: list[tuple[int, int, str | None]] = []
    index = 0
    while index < len(spans):
        start, end, heading = spans[index]
        too_small = len(text[start:end].strip()) < MIN_CHUNK_CHARS

        if (
            too_small
            and index + 1 < len(spans)
            and _is_heading_only(text[start:end])
            and spans[index + 1][0] == end
            and spans[index + 1][1] - start <= max_join
        ):
            next_end, next_heading = spans[index + 1][1], spans[index + 1][2]
            merged.append((start, next_end, heading or next_heading))
            index += 2
            continue

        if too_small and merged and merged[-1][1] == start and end - merged[-1][0] <= max_join:
            previous_start, _, previous_heading = merged[-1]
            merged[-1] = (previous_start, end, previous_heading or heading)
            index += 1
            continue

        merged.append((start, end, heading))
        index += 1
    return merged


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def render_table(table: list[list[str | None]]) -> str:
    """Render one extracted table as ``row | cells`` lines."""
    rows = [[(cell or "").strip() for cell in row] for row in table]
    rows = [row for row in rows if any(row)]
    return "\n".join(" | ".join(cell for cell in row if cell) for row in rows)


def table_texts(page) -> list[str]:
    """Rendered tables that look like real tables rather than figure fragments.

    ``extract_tables`` is noisy on these PDFs: state diagrams and callouts are
    returned as one- or two-row "tables".  Requiring 3+ rows, 4+ cells and 80+
    characters keeps the real protocol/exception tables and drops the fragments.
    """
    kept: list[str] = []
    seen: list[str] = []
    for table in page.extract_tables() or []:
        rows = [[(cell or "").strip() for cell in row] for row in table]
        rows = [row for row in rows if any(row)]
        cells = [cell for row in rows for cell in row if cell]
        text = render_table(table)
        if len(rows) < TABLE_MIN_ROWS or len(cells) < TABLE_MIN_CELLS:
            continue
        if len(text) < TABLE_MIN_CHARS:
            continue
        normalised = re.sub(r"\s+", " ", text).strip().lower()
        if any(normalised in other or other in normalised for other in seen):
            continue  # same table detected twice (nested detection)
        seen.append(normalised)
        kept.append(text)
    return kept


def split_table_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split a long table by rows, repeating its header rows in each part.

    A table title line ("MODBUS Exception Codes") followed by a column row
    ("Code | Name | Meaning") is the common layout, so both are repeated.
    """
    lines = text.splitlines()
    if len(text) <= size or len(lines) <= 1:
        return [text]

    header_lines = 1
    if len(lines) > 2 and " | " not in lines[0] and " | " in lines[1]:
        header_lines = 2
    header = "\n".join(lines[:header_lines])
    body = lines[header_lines:]

    parts: list[str] = []
    current = header
    for line in body:
        candidate = f"{current}\n{line}"
        if len(candidate) > size and current != header:
            parts.append(current)
            current = f"{header}\n{line}"
        else:
            current = candidate
    parts.append(current)
    return parts


# ---------------------------------------------------------------------------
# Corpus build
# ---------------------------------------------------------------------------

def build_corpus(raw_dir: Path, output_dir: Path, summaries_path: Path) -> dict:
    """Extract every page with pdfplumber; preserve provenance and source hashes.

    No LLM summarization or external calls. Keep original PDFs unchanged.
    Diagrams are still not reconstructed; tables are rendered row-per-line but
    their visual layout must be verified in the source PDF.
    """
    import pdfplumber

    summaries = json.loads(summaries_path.read_text(encoding="utf-8"))
    downloads = json.loads((raw_dir / "sources.json").read_text(encoding="utf-8"))
    specs = [
        ("application", "modbus_application_v1_1b3.pdf"),
        ("serial", "modbus_serial_v1_02.pdf"),
    ]

    sources: dict = {}
    chunks: list[dict] = []
    pages: list[dict] = []
    documents: list[dict] = []
    stats: dict = {}

    for source_id, filename in specs:
        path = raw_dir / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = next(item for item in downloads if item["filename"] == filename)
        if digest != record["sha256"]:
            raise ValueError(f"PDF hash differs from download manifest: {filename}")

        sources[source_id] = {
            **summaries["sources"][source_id],
            "kind": "official_pdf",
            "local_path": str(path.resolve()),
            "sha256": digest,
            "url": record["url"],
            "note": (
                "Extracted original English PDF text with repeated headers/footers "
                "removed and tables rendered row-per-line; verify layouts in the "
                "source PDF"
            ),
        }

        extracted: list[tuple[int, str, list[str]]] = []
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                if not text.strip():
                    raise ValueError(f"Empty text page {number} in {filename}; OCR required")
                extracted.append((number, text, table_texts(page)))

        repeated = repeated_line_keys([text for _, text, _ in extracted])
        text_chunks = 0
        table_chunk_count = 0
        removed_lines = 0
        removed_toc_lines = 0

        for number, raw_text, tables in extracted:
            clean_text, removed_footer, removed_toc = clean_page_text(raw_text, repeated)
            removed_lines += len(removed_footer)
            removed_toc_lines += len(removed_toc)

            headings = [
                line.strip() for line in clean_text.splitlines() if is_heading(line)
            ]
            page_section = " | ".join(headings[:5]) or f"PDF page {number}"
            # Only a real, single heading may be used as a table prefix; the
            # "PDF page N" fallback must never leak into chunk text.
            table_heading = headings[0] if len(headings) == 1 else None
            pages.append(
                {
                    "source": source_id,
                    "page": number,
                    "text": clean_text,
                    "sha256": digest,
                    "section": page_section,
                    "removed_lines": len(removed_footer),
                    "toc_lines_removed": len(removed_toc),
                    "table_count": len(tables),
                }
            )
            title = f"{sources[source_id]['title']} / page {number}"

            for index, (start, end, heading) in enumerate(page_chunk_spans(clean_text)):
                chunks.append(
                    {
                        "id": f"{source_id}-{digest[:10]}-p{number:03d}-c{index:02d}",
                        "source": source_id,
                        "page": number,
                        "section": heading or page_section,
                        "title": title,
                        "kind": "text",
                        "protocol": "modbus_rtu",
                        "device": "generic",
                        "text": clean_text[start:end],
                        "start_offset": start,
                        "end_offset": end,
                    }
                )
                text_chunks += 1

            for table_index, table in enumerate(tables):
                parts = split_table_text(table)
                for part_index, part in enumerate(parts):
                    suffix = f"t{table_index:02d}"
                    if len(parts) > 1:
                        suffix += f"-{part_index}"
                    # A table on a single-heading page is otherwise context
                    # free ("Function code | 1 Byte | 0x04 ...").  Prefixing
                    # that heading keeps the table self-describing for search.
                    if table_heading and not part.lstrip().startswith(table_heading):
                        part = f"{table_heading}\n{part}"
                    chunks.append(
                        {
                            "id": f"{source_id}-{digest[:10]}-p{number:03d}-{suffix}",
                            "source": source_id,
                            "page": number,
                            "section": page_section,
                            "title": title,
                            "kind": "table",
                            "protocol": "modbus_rtu",
                            "device": "generic",
                            "text": part,
                            "start_offset": None,
                            "end_offset": None,
                        }
                    )
                    table_chunk_count += 1

        documents.append(
            {
                "source": source_id,
                "filename": filename,
                "pages": len(extracted),
                "chunks": text_chunks,
                "table_chunks": table_chunk_count,
                "sha256": digest,
            }
        )
        stats[source_id] = {
            "pages": len(extracted),
            "text_chunks": text_chunks,
            "table_chunks": table_chunk_count,
            "removed_header_footer_lines": removed_lines,
            "removed_toc_lines": removed_toc_lines,
            "repeated_line_keys": sorted(repeated),
        }

    # Keep fictional device and tool behavior docs, not the superseded protocol summaries.
    extras = [item for item in summaries["chunks"] if item["source"] in ("virtual", "guide")]
    for item in extras:
        sources[item["source"]] = summaries["sources"][item["source"]]
    chunks.extend(extras)

    corpus = {"version": "0.3.0", "sources": sources, "chunks": chunks}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pages.jsonl").write_text(
        "".join(json.dumps(page, ensure_ascii=False) + "\n" for page in pages),
        encoding="utf-8",
    )
    (output_dir / "knowledge.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "documents": documents,
        "page_count": len(pages),
        "chunk_count": len(chunks),
        "text_chunks": sum(item["text_chunks"] for item in stats.values()),
        "table_chunks": sum(item["table_chunks"] for item in stats.values()),
        "supplemental_chunks": len(extras),
        "extractor": "pdfplumber",
        "chunking": {
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "min_chunk_chars": MIN_CHUNK_CHARS,
            "section_aware": True,
        },
        "header_footer": {
            "edge_lines": EDGE_LINES,
            "ratio": REPEAT_LINE_RATIO,
            "per_source": stats,
        },
        "toc_lines_removed": sum(item["removed_toc_lines"] for item in stats.values()),
        "limitations": [
            "Text only: diagrams are not indexed",
            "Tables are rendered row-per-line; column alignment needs visual verification",
            "Page numbers are 1-based physical PDF pages",
            "Table chunks are not exact page substrings (offsets are None)",
        ],
    }
    (output_dir / "ingestion_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
