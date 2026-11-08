"""Generate a human-review worksheet for a Modbus evaluation suite.

Mechanical validation only proves an anchor exists in the corpus.  A human still
has to judge whether the question is unambiguous and whether the cited page is
the right evidence.  This script emits one section per case with the surrounding
page excerpt and the checks to fill in.

Usage:
    python -m scripts.make_modbus_review_sheet
    python -m scripts.make_modbus_review_sheet --suite tests/fixtures/modbus_eval_v3.json \
        --output data/modbus/evaluation/v3_review_sheet.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data/modbus/processed"
EXCERPT_BEFORE = 60
EXCERPT_AFTER = 240


def _excerpt(page_text: str, anchor: str) -> str:
    lowered = page_text.lower()
    position = lowered.find(anchor.lower())
    if position < 0:
        return "(anchor not found in page text — table rendering only)"
    start = max(0, position - EXCERPT_BEFORE)
    end = min(len(page_text), position + len(anchor) + EXCERPT_AFTER)
    return " ".join(page_text[start:end].split())


def _question_flags(question: str, others: list[str]) -> list[str]:
    flags = []
    if len(question) < 8:
        flags.append("问题过短")
    if re.search(r"[?？]{2,}", question):
        flags.append("多个问号")
    tokens = set(re.findall(r"[A-Za-z0-9]+", question.lower())) | set(re.findall(r"[\u4e00-\u9fff]{2,}", question))
    for other in others:
        if other == question:
            continue
        other_tokens = set(re.findall(r"[A-Za-z0-9]+", other.lower())) | set(re.findall(r"[\u4e00-\u9fff]{2,}", other))
        if not tokens or not other_tokens:
            continue
        overlap = len(tokens & other_tokens) / len(tokens | other_tokens)
        if overlap >= 0.8:
            flags.append(f"与另一题高度相似（{overlap:.0%}）")
            break
    return flags


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build a human review worksheet")
    parser.add_argument("--suite", type=Path, default=ROOT / "tests/fixtures/modbus_eval_v3.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/modbus/evaluation/v3_review_sheet.md")
    args = parser.parse_args()

    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    cases = suite["retrieval_cases"]
    pages = [
        json.loads(line)
        for line in (PROCESSED / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    page_text = {(p["source"], p["page"]): p["text"] for p in pages}
    chunks = {
        c["id"]: c
        for c in json.loads((PROCESSED / "knowledge.json").read_text(encoding="utf-8"))["chunks"]
    }
    questions = [case["question"] for case in cases]

    with_pages = [c for c in cases if not c.get("scope_only")]
    stats = {
        "total": len(cases),
        "tuning": sum(1 for c in cases if c.get("split") == "tuning"),
        "test": sum(1 for c in cases if c.get("split") == "test"),
        "with_evidence": len(with_pages),
        "auto_flagged": 0,
    }

    lines = [
        f"# 人工复核工作表：{args.suite.name}",
        "",
        f"- 用例总数：{stats['total']}（调参 {stats['tuning']} / 留出 {stats['test']}）",
        "- 机械校验只能证明 anchor 存在于语料，**不能证明问题清晰、证据页正确**。",
        "- 每题的判定请填最后一列：`通过` / `改问题` / `改证据` / `删除`，并在备注写原因。",
        "- 留出集（test）在冻结变更前不要看逐题检索结果，只看本表中的问题与证据。",
        "- 若本题已有 `复核记录`，表示助手已完成一次自审并给出改动；仍建议他人抽查。",
        "",
        "| 字段 | 含义 |",
        "|---|---|",
        "| 问题清晰 | 问法是否唯一指向一个事实，不含歧义 |",
        "| 证据页正确 | 标注页确实是答案所在页 |",
        "| 可推出答案 | 仅凭摘录能回答该问题 |",
        "",
    ]

    for split in ("tuning", "test"):
        lines.extend([f"## {split}", ""])
        for case in cases:
            if case.get("split") != split:
                continue
            flags = _question_flags(case["question"], questions)
            lines.append(f"### {case['id']}　{case['question']}")
            lines.append("")
            if case.get("scope_only"):
                lines.append("- 范围题（无证据页），仅检查是否应拒答 / 不应引用虚构设备。")
                lines.append(f"- 禁止来源类型：{', '.join(case.get('forbid_kinds', []))}")
                lines.append("")
                continue
            for target in case["evidence"]:
                if "chunk_id" in target:
                    chunk = chunks.get(target["chunk_id"], {})
                    excerpt = " ".join(str(chunk.get("text", ""))[:300].split())
                    lines.append(f"- 证据：chunk `{target['chunk_id']}`（{chunk.get('device', 'generic')}）")
                else:
                    key = (target["source"], target["page"])
                    excerpt = _excerpt(page_text.get(key, ""), target.get("anchor", ""))
                    lines.append(
                        f"- 证据：{target['source']} p{target['page']}，anchor `{target.get('anchor', '')}`"
                    )
                lines.append(f"- 摘录：{excerpt}")
            if flags:
                stats["auto_flagged"] += 1
                lines.append(f"- 自动提示：{'；'.join(flags)}")
            review = case.get("review") or {}
            if review:
                note = f"，备注：{review['note']}" if review.get("note") else ""
                lines.append(f"- 复核记录：{review.get('status')}（{review.get('by')}，{review.get('date')}）{note}")
            lines.append("")
            lines.append("| 问题清晰 | 证据页正确 | 可推出答案 | 判定 | 备注 |")
            lines.append("|---|---|---|---|---|")
            lines.append("| ☐ | ☐ | ☐ |  |  |")
            lines.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "suite": args.suite.name,
        "output": str(args.output),
        **stats,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
