"""Frozen Modbus retrieval baseline and optional real-agent evaluation.

python -m scripts.evaluate_modbus --mode retrieval
python -m scripts.evaluate_modbus --mode agent --case-id A01 --case-id A02
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.core.modbus_knowledge import ROOT, ModbusKnowledge
from src.observability.evaluation.modbus_eval import MeteredLLM, score_agent, score_retrieval


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Versioned Modbus baseline evaluation")
    parser.add_argument("--mode", choices=["retrieval", "agent"], default="retrieval")
    parser.add_argument("--retrieval-mode", choices=["bm25", "hybrid"],
                        help="Override modbus.retrieval_mode for this run")
    parser.add_argument("--rerank", dest="rerank", action="store_true", default=None,
                        help="Force the second-stage rerank on (hybrid mode only)")
    parser.add_argument("--no-rerank", dest="rerank", action="store_false",
                        help="Force the second-stage rerank off")
    parser.add_argument("--suite", type=Path, default=ROOT / "tests/fixtures/modbus_eval_v3.json")
    parser.add_argument("--split", choices=["all", "tuning", "test"], default="all",
                        help="Evaluate one split of a versioned suite (retrieval mode only)")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    suite_bytes = args.suite.read_bytes()
    suite = json.loads(suite_bytes)
    all_cases = suite[args.mode + "_cases"]
    ids = [case["id"] for case in all_cases]
    if len(set(ids)) != len(ids):
        parser.error("Duplicate case IDs")
    if args.case_id and set(args.case_id) - set(ids):
        parser.error("Unknown case ID")
    if args.split != "all" and args.mode != "retrieval":
        parser.error("--split only applies to --mode retrieval")
    cases = [case for case in all_cases if not args.case_id or case["id"] in args.case_id]
    if args.split != "all":
        cases = [case for case in cases if case.get("split") == args.split]
    knowledge = ModbusKnowledge(retrieval_mode=args.retrieval_mode, rerank=args.rerank)
    output = args.output or ROOT / (
        f"data/modbus/evaluation/{args.mode}_baseline_v{suite['version'].split('.')[0]}.json"
    )
    report = {"version": suite["version"], "purpose": suite["purpose"], "mode": args.mode,
              "retrieval_mode": knowledge.retrieval_mode, "split": args.split,
              "rerank": knowledge.rerank_enabled,
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
              "corpus_sha256": hashlib.sha256(knowledge.corpus_path.read_bytes()).hexdigest(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                        for name in ["src/core/modbus_agent.py", "src/core/modbus_knowledge.py", "src/observability/evaluation/modbus_eval.py"]},
              "selected_cases": [c["id"] for c in cases], "not_selected": [c for c in ids if c not in {x["id"] for x in cases}],
              "results": [], "summary": {}}
    llm = None
    if args.mode == "agent":
        from src.core.settings import load_settings
        from src.libs.llm.llm_factory import LLMFactory
        settings = load_settings()
        llm = MeteredLLM(LLMFactory.create(settings))
        report["model"] = settings.llm.model
        report["provider"] = settings.llm.provider
    output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        started = time.perf_counter()
        before_calls = llm.calls if llm else 0
        before_usage = dict(llm.usage) if llm else {}
        row = {"id": case["id"], "question": case["question"]}
        try:
            if args.mode == "retrieval":
                hits = knowledge.retrieve(case["question"], top_k=3, device=case.get("device"))
                row.update(metrics=score_retrieval(case, hits), retrieved=[
                    {"chunk_id": h["id"], "source": h["source"], "page": h.get("page"), "text": h["text"]} for h in hits])
            else:
                from src.core.modbus_agent import ModbusAgent
                state = ModbusAgent(llm, knowledge).run(case["question"], events=case.get("events"), device=case.get("device"))
                state.pop("events", None)
                row.update(evaluation=score_agent(case, state), state=state)
        except Exception as exc:
            row["error_type"] = type(exc).__name__
        row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if llm:
            row["model_calls"] = llm.calls - before_calls
            row["token_usage"] = {k: v - before_usage.get(k, 0) for k, v in llm.usage.items()}
        report["results"].append(row)
        rows = report["results"]
        if args.mode == "retrieval":
            evidence_rows = [r for r in rows if not next(c for c in cases if c["id"] == r["id"]).get("scope_only")]
            report["summary"] = {"executed": len(rows), "selected": len(cases), "evidence_cases": len(evidence_rows),
                "evidence_hit_at_3": sum(r.get("metrics", {}).get("evidence_hit_at_k", False) for r in evidence_rows) / len(evidence_rows) if evidence_rows else None,
                "mrr_at_3": sum(r.get("metrics", {}).get("reciprocal_rank", 0) for r in evidence_rows) / len(evidence_rows) if evidence_rows else None,
                "scope_checks_passed": sum(r.get("metrics", {}).get("scope_ok", False) for r in rows)}
        else:
            report["summary"] = {"executed": len(rows), "selected": len(cases),
                "mechanical_passed": sum(r.get("evaluation", {}).get("mechanical_pass", False) for r in rows),
                "human_reviews_pending": len(rows), "model_calls": llm.calls, "token_usage": llm.usage,
                "semantic_accuracy": None, "monetary_cost": None}
        report["errors"] = sum("error_type" in row for row in rows)
        report["run_complete"] = len(rows) == len(cases)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": case["id"], "elapsed_ms": row["elapsed_ms"], "summary": report["summary"]}), flush=True)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
