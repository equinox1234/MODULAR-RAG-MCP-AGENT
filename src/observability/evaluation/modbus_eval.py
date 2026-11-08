"""Domain evaluation: separate mechanical checks from human answer review.

No model-judge scores are silently substituted for independent human review.
"""
from __future__ import annotations

import re
from typing import Any


def evidence_matches(hit: dict, target: dict) -> bool:
    source = hit.get("source")
    if source is None:
        # Agent citations contain the source file identity in their stable chunk ID.
        source = hit.get("chunk_id", "").split("-")[0]
    if source != target.get("source"):
        return False
    if "page" in target and hit.get("page") != target["page"]:
        return False
    if "chunk_id" in target and hit.get("chunk_id", hit.get("id")) != target["chunk_id"]:
        return False
    return target.get("anchor", "").lower() in hit.get("text", "").lower()


def score_retrieval(case: dict, hits: list[dict]) -> dict:
    forbidden = case.get("forbid_kinds", [])
    scope_ok = not any(h.get("provenance", {}).get("kind", h.get("kind")) in forbidden for h in hits)
    result = {"scope_ok": scope_ok}
    if case.get("scope_only"):
        return result
    targets = case["evidence"]
    ranks = [i for i, hit in enumerate(hits, 1) if any(evidence_matches(hit, target) for target in targets)]
    # Evidence recall at k: fraction of evidence anchors that appear in top-k.
    n_targets = len(targets)
    hit_count = sum(any(evidence_matches(h, target) for h in hits) for target in targets)
    result.update(
        evidence_hit_at_k=bool(ranks),
        reciprocal_rank=1 / ranks[0] if ranks else 0,
        evidence_coverage=hit_count / n_targets if n_targets else None,
        recall_at_1=hit_count / n_targets if n_targets else None,
        recall_at_3=hit_count / n_targets if n_targets else None,
        recall_at_5=hit_count / n_targets if n_targets else None,
    )
    # For a single-target case (scope_only or one anchor), recall == coverage.
    # For multi-target cases, recall is the same formula; we keep all three K values
    # so the evaluator can inspect per-K behavior without changing the API.
    return result


def score_agent(case: dict, state: dict) -> dict:
    successful = [o["tool"] for o in state.get("observations", []) if "error" not in o]
    iterator = iter(successful)
    ordered = all(any(tool == actual for actual in iterator) for tool in case.get("required_tools", []))
    checks = {"expected_status": state.get("status") in case["expected_status"],
              "required_tools_in_order": ordered,
              "no_forbidden_tools": not any(t in successful for t in case.get("forbidden_tools", []))}
    analysis = state.get("log_analysis") or {}
    if "transaction_statuses" in case:
        checks["transaction_statuses"] = [tx["status"] for tx in analysis.get("transactions", [])] == case["transaction_statuses"]
    if "issue_kinds" in case:
        checks["issue_kinds"] = [x["kind"] for x in analysis.get("issues", [])] == case["issue_kinds"]
    citations = state.get("citations", [])
    text_refs = set(re.findall(r"\[(D\d+|L\d+)\]", state.get("answer", "")))
    doc_ids = {c["id"] for c in citations}
    log_ids = {x["event"] for o in state.get("observations", [])
               for x in o.get("transactions", []) + o.get("issues", [])}
    if state.get("status") == "completed":
        checks["citation_ids_valid"] = bool(text_refs & doc_ids) and text_refs <= doc_ids | log_ids
    if case.get("require_log_citation"):
        checks["has_log_citation"] = bool(text_refs & log_ids)
    if "expected_evidence" in case:
        checks["expected_document_evidence"] = all(any(evidence_matches(c, target) for c in citations) for target in case["expected_evidence"])
    return {"checks": checks, "mechanical_pass": all(checks.values()),
            "human_review": {"status": "pending", "criteria": case.get("review_focus", []),
                             "factual_correctness": None, "citation_support": None,
                             "uncertainty_handling": None, "task_relevance": None,
                             "notes": "Mechanical pass does not grade answer semantics."}}


class MeteredLLM:
    """Count actual provider calls and returned token usage, including repairs."""
    def __init__(self, llm: Any):
        self.llm = llm
        self.calls = 0
        self.usage: dict[str, int] = {}
        self.failed_calls = 0
        self.calls_without_complete_usage = 0
        self.call_records = []

    def chat(self, *args, **kwargs):
        self.calls += 1
        try:
            result = self.llm.chat(*args, **kwargs)
        except Exception:
            self.failed_calls += 1
            self.call_records.append({"failed": True})
            raise
        record = {"failed": False, "usage": {k: v for k, v in (result.usage or {}).items()
                  if k in {"prompt_tokens", "completion_tokens", "total_tokens", "completion_tokens_details", "prompt_tokens_details"}}}
        messages = args[0] if args else kwargs.get("messages", [])
        record["request_characters"] = sum(len(getattr(message, "content", "")) for message in messages)
        self.call_records.append(record)
        if not all(isinstance((result.usage or {}).get(k), int) and not isinstance((result.usage or {}).get(k), bool)
                   and (result.usage or {})[k] >= 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
            self.calls_without_complete_usage += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = (result.usage or {}).get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.usage[key] = self.usage.get(key, 0) + value
        return result
