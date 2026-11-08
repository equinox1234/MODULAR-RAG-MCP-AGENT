"""Persist per-run metadata, without prompts, logs, answers or credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

from src.observability.evaluation.modbus_eval import MeteredLLM
from src.observability.dashboard.services.modbus_cost import estimate_calls


def recorded_run(execute, record_dir: Path, action: str | None = None):
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    meters = []

    def instrument(llm, model, provider):
        meter = MeteredLLM(llm)
        meters.append((meter, model, provider))
        return meter

    try:
        result = execute(instrument)
    except Exception as exc:
        result = {"status": "execution_error", "answer": "本次执行失败，请检查本地配置与输入。", "error_type": type(exc).__name__}
    calls = sum(m.calls for m, _, _ in meters)
    failures = sum(m.failed_calls for m, _, _ in meters)
    complete = not failures and all(m.calls_without_complete_usage == 0 for m, _, _ in meters)
    usage = {k: sum(m.usage.get(k, 0) for m, _, _ in meters) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    # Missing usage is unknown, never silently presented as zero consumption.
    for key in usage:
        if calls and not any(key in m.usage for m, _, _ in meters):
            usage[key] = None
    metrics = {"run_id": uuid4().hex, "started_utc": started, "action": action,
               "elapsed_ms": round((time.perf_counter() - clock) * 1000),
               "status": result.get("status", result.get("mode", "unknown")), "execution_path": result.get("execution_path"),
               "model_calls": calls, "failed_model_calls": failures, "token_usage": usage,
               "usage_complete": complete, "model": meters[0][1] if meters else None,
               "provider": meters[0][2] if meters else None,
               "monetary_cost": None, "cost_status": "not_estimated", "quality_review": "unreviewed"}
    records = [record for m, _, _ in meters for record in m.call_records]
    metrics["model_call_details"] = records
    if len(meters) == 1:
        meter, model, _ = meters[0]
        pricing = estimate_calls(model, getattr(meter.llm, "base_url", None), records)
        metrics.update(cost_estimate=pricing, monetary_cost=pricing["amount"], cost_status=pricing["status"])
    elif not calls:
        metrics.update(monetary_cost=0.0, cost_status="no_model_calls")
    try:
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / f"{metrics['run_id']}.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        result["recording_error"] = type(exc).__name__
    result["run_metrics"] = metrics
    return result
