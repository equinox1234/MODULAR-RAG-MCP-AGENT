import pytest

from src.ingestion.modbus_pdf import (
    clean_page_text,
    page_chunk_spans,
    render_table,
    repeated_line_keys,
    section_spans,
    split_page,
    split_table_text,
    table_texts,
)


def test_page_split_covers_every_character_and_preserves_offsets():
    text = ("Header\nAddress Value Meaning\n02 Illegal data address\n" * 90)
    pieces = list(split_page(text))
    covered = set()
    for start, end, value in pieces:
        assert value == text[start:end]
        assert end - start <= 1500
        covered.update(range(start, end))
    assert covered == set(range(len(text)))
    assert len(pieces) > 1


@pytest.mark.parametrize("size,overlap", [(10, 10), (10, -1), (0, 0)])
def test_bad_chunk_configuration(size, overlap):
    with pytest.raises(ValueError):
        list(split_page("test", size, overlap))


# ============================================================================
# Header / footer detection
# ============================================================================

def _letters(value):
    """Digit-free unique token so normalisation cannot collapse body lines."""
    out = ""
    while True:
        out = chr(97 + value % 26) + out
        value //= 26
        if value == 0:
            return out


def _stamped_pages(count=12, footer="April 26, 2012 http://www.modbus.org {n}/12"):
    pages = []
    for number in range(1, count + 1):
        body = "\n".join(
            f"{_letters(number * 10 + index)} body text content" for index in range(6)
        )
        pages.append(
            f"MODBUS Application Protocol Specification V1.1b3 Modbus\n"
            f"{_letters(number)} opening paragraph\n"
            f"{body}\n"
            f"request\n"
            f"{footer.format(n=number)}"
        )
    return pages


def test_repeated_footer_is_detected_but_mid_page_words_are_not():
    keys = repeated_line_keys(_stamped_pages())

    assert any("http://www.modbus.org" in key for key in keys)
    assert any("modbus application protocol specification" in key for key in keys)
    # "request" repeats on every page but sits mid-page: it is content.
    assert "request" not in keys


def test_strip_repeated_lines_keeps_content():
    keys = repeated_line_keys(_stamped_pages())
    text = _stamped_pages(1)[0]
    cleaned, removed_footer, removed_toc = clean_page_text(text, keys)

    assert len(removed_footer) == 2  # title line + date/URL/page footer
    assert removed_toc == []
    assert "request" in cleaned
    assert "body text content" in cleaned
    assert "http://www.modbus.org" not in cleaned


def test_table_of_contents_lines_are_dropped():
    text = "CONTENTS\n1 Introduction ........................ 2\n2 Abbreviations ..... 3\n"
    cleaned, removed_footer, removed_toc = clean_page_text(text, set())

    assert len(removed_toc) == 2
    assert removed_footer == []
    assert "CONTENTS" in cleaned
    assert "Introduction" not in cleaned


def test_too_few_pages_means_no_detection():
    assert repeated_line_keys(["same line\nbody"] * 3) == set()


# ============================================================================
# Section-aware chunking
# ============================================================================

def test_section_spans_split_at_numbered_headings():
    text = "1 Introduction\nIntro body\n2 Scope\nScope body\n"
    spans = section_spans(text)

    assert [heading for _, _, heading in spans] == ["1 Introduction", "2 Scope"]
    assert [text[start:end] for start, end, _ in spans] == [
        "1 Introduction\nIntro body\n",
        "2 Scope\nScope body\n",
    ]


def test_table_of_contents_lines_are_not_sections():
    text = "1 Introduction .......................... 2\nreal body\n"
    assert section_spans(text) == [(0, len(text), None)]


@pytest.mark.parametrize(
    "line",
    [
        "6.3 03 (0x03) Read Holding Registers",
        "1 Introduction",
        "4.4 MODBUS Addressing model",
    ],
)
def test_real_headings_are_recognised(line):
    from src.ingestion.modbus_pdf import is_heading

    assert is_heading(line)


@pytest.mark.parametrize(
    "line",
    [
        # Zero-padded exception code with a sentence tail from a linearised table
        "01 ILLEGAL FUNCTION The function code received in the query is not an",
        "02 ILLEGAL DATA ADDRESS The data address received in the query is not an",
        # Function-code table row
        "16 bits Write Single Register 06 06 6.6",
        # Wrapped prose from a table cell
        "100 registers, the PDU addresses the first register",
        # Table of contents entry
        "1 Introduction .......................... 2",
    ],
)
def test_table_rows_and_toc_are_not_headings(line):
    from src.ingestion.modbus_pdf import is_heading

    assert not is_heading(line)


def test_bare_parent_heading_merges_into_its_subsection():
    body = "Body text that is long enough. " * 20
    text = f"1 Introduction\n1.1 Scope\n{body}"

    spans = page_chunk_spans(text)

    assert len(spans) == 1
    start, end, heading = spans[0]
    assert heading == "1 Introduction"
    assert "1.1 Scope" in text[start:end]
    assert body.strip()[:20] in text[start:end]


# ============================================================================
# Tables
# ============================================================================

class _FakePage:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables


def test_figure_fragments_are_not_treated_as_tables():
    diagram = [["slave", None, None], ["request", None, None]]
    real = [
        ["Code", "Name", "Meaning"],
        ["01", "ILLEGAL FUNCTION", "The function code received is not allowed."],
        ["02", "ILLEGAL DATA ADDRESS", "The data address received is not allowed."],
        ["03", "ILLEGAL DATA VALUE", "A value in the request is not allowed."],
    ]

    texts = table_texts(_FakePage([diagram, real]))

    assert len(texts) == 1
    assert "02 | ILLEGAL DATA ADDRESS" in texts[0]


def test_nested_duplicate_tables_are_deduplicated():
    table = [
        ["Code", "Name"],
        ["01", "ILLEGAL FUNCTION"],
        ["02", "ILLEGAL DATA ADDRESS"],
        ["03", "ILLEGAL DATA VALUE"],
    ]
    assert len(table_texts(_FakePage([table, [row[:] for row in table]]))) == 1


def test_render_table_skips_empty_cells():
    rendered = render_table([["a", None, "b"], [None, None, None]])
    assert rendered == "a | b"


def test_split_table_text_repeats_title_and_column_header():
    rows = [f"0{i:02d} | CODE {i} | meaning text number {i}" for i in range(1, 61)]
    text = "MODBUS Exception Codes\nCode | Name | Meaning\n" + "\n".join(rows)

    parts = split_table_text(text, size=600)

    assert len(parts) > 1
    for part in parts:
        assert part.startswith("MODBUS Exception Codes\nCode | Name | Meaning")
    rejoined = "\n".join(parts)
    for row in rows:
        assert row in rejoined
