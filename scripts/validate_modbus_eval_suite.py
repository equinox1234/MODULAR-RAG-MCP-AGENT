"""Validate a Modbus retrieval suite against the indexed corpus.

Every labelled anchor must be findable in the cited page (or chunk), otherwise
the label is unverifiable and the metric silently measures the label, not the
retriever.

The check uses the *same* predicate as ``modbus_eval.evidence_matches``: a plain
case-insensitive substring of the chunk text (no whitespace folding).  An anchor
that only matches after folding line breaks would pass a naive check and then
fail at evaluation time, so it is reported as a problem.

Usage:
    python -m scripts.validate_modbus_eval_suite
    python -m scripts.validate_modbus_eval_suite --suite tests/fixtures/modbus_eval_v2.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED = ROOT / "data/modbus/processed"


def validate_suite(
    suite_path: Path, processed_dir: Path = DEFAULT_PROCESSED
) -> list[str]:
    """Return a list of problems; an empty list means every label is verified."""
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = suite["retrieval_cases"]
    corpus = json.loads((processed_dir / "knowledge.json").read_text(encoding="utf-8"))
    pages = [
        json.loads(line)
        for line in (processed_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    page_text = {(p["source"], p["page"]): p["text"].lower() for p in pages}
    page_text_folded = {
        (p["source"], p["page"]): " ".join(p["text"].lower().split()) for p in pages
    }
    chunk_text = {c["id"]: c["text"].lower() for c in corpus["chunks"]}
    chunks_by_page: dict[tuple[str, int], list[str]] = {}
    for chunk in corpus["chunks"]:
        if chunk.get("page") is not None:
            chunks_by_page.setdefault((chunk["source"], chunk["page"]), []).append(chunk["id"])

    problems: list[str] = []
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        problems.append("duplicate case IDs")

    valid_splits = set(suite.get("split_policy", {}))
    for case in cases:
        if case.get("split") not in valid_splits:
            problems.append(f"{case['id']}: unknown split {case.get('split')!r}")
        if case.get("scope_only"):
            if not case.get("forbid_kinds"):
                problems.append(f"{case['id']}: scope_only without forbid_kinds")
            continue
        if not case.get("evidence"):
            problems.append(f"{case['id']}: no evidence and not scope_only")
            continue
        for target in case["evidence"]:
            anchor = target.get("anchor", "").lower()
            if not anchor:
                problems.append(f"{case['id']}: empty anchor")
                continue
            if "chunk_id" in target:
                text = chunk_text.get(target["chunk_id"])
                if text is None:
                    problems.append(f"{case['id']}: unknown chunk_id {target['chunk_id']}")
                elif anchor not in text:
                    problems.append(
                        f"{case['id']}: anchor not in chunk {target['chunk_id']}: {anchor!r}"
                    )
                continue
            key = (target["source"], target.get("page"))
            if key not in page_text:
                problems.append(f"{case['id']}: unknown page {key}")
                continue
            if anchor in page_text[key]:
                continue
            # Table chunks re-render the same cells with " | "; accept either form.
            if any(anchor in chunk_text[cid] for cid in chunks_by_page.get(key, [])):
                continue
            if anchor in page_text_folded[key]:
                problems.append(
                    f"{case['id']}: anchor spans a line break on {key[0]} p{key[1]}, "
                    f"so it can never match at evaluation time: {anchor!r}"
                )
                continue
            problems.append(f"{case['id']}: anchor not found on {key[0]} p{key[1]}: {anchor!r}")
    return problems


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate Modbus eval suite labels")
    parser.add_argument("--suite", type=Path, default=ROOT / "tests/fixtures/modbus_eval_v3.json")
    args = parser.parse_args()
    suite_path = args.suite if args.suite.is_absolute() else (Path.cwd() / args.suite)
    suite_path = suite_path.resolve()

    problems = validate_suite(suite_path)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = suite["retrieval_cases"]
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.get("split", "?")] = counts.get(case.get("split", "?"), 0) + 1

    try:
        display = str(suite_path.relative_to(ROOT))
    except ValueError:
        display = str(suite_path)

    print(json.dumps({
        "suite": display,
        "version": suite.get("version"),
        "retrieval_cases": len(cases),
        "splits": counts,
        "agent_cases": len(suite.get("agent_cases", [])),
        "problems": problems,
    }, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
