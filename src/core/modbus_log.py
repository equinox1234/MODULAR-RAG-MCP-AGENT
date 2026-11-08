"""Analyze normalized master-side RTU logs without inferring physical causes."""
from __future__ import annotations

import math
from typing import Any

from src.core.modbus import parse_rtu_frame


def analyze_rtu_log(events: list[dict[str, Any]], timeout_ms: float = 1000) -> dict[str, Any]:
    """Events use monotonic timestamp_ms, TX/RX, and hex_frame.

    One complete frame per event, one master and one outstanding request assumed.
    Capture end alone is not evidence of timeout. RTU has no transaction IDs;
    late responses to identical retried reads cannot be disambiguated.
    """
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)) or not math.isfinite(timeout_ms) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a finite positive number")
    transactions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    pending = None
    previous = -1.0
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Event {index} must be an object")
        timestamp = event.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < previous or timestamp < 0:
            raise ValueError(f"Event {index} requires nonnegative monotonic timestamp_ms")
        previous = timestamp
        direction = event.get("direction")
        if direction not in ("TX", "RX"):
            raise ValueError(f"Event {index} direction must be TX or RX")
        if pending is not None and timestamp - pending["timestamp_ms"] > timeout_ms:
            pending["status"] = "timeout"
            pending = None
        parsed = parse_rtu_frame(event.get("hex_frame"), "request" if direction == "TX" else "response")
        if not parsed["valid"]:
            issues.append({"event_index": index, "kind": "invalid_frame", "frame": parsed})
            continue
        if direction == "TX":
            if pending is not None:
                pending["status"] = "interrupted_by_new_request"
                issues.append({"event_index": index, "kind": "overlapping_request"})
            transaction = {"request_event": index, "timestamp_ms": timestamp,
                           "request": parsed, "status": "broadcast" if parsed["address"] == 0 else "pending"}
            transactions.append(transaction)
            pending = None if parsed["address"] == 0 else transaction
            continue
        if pending is None:
            issues.append({"event_index": index, "kind": "unmatched_response", "frame": parsed})
            continue
        request = pending["request"]
        matches = parsed["address"] == request["address"] and (parsed["function_code"] & 0x7F) == request["function_code"]
        if matches and not parsed["function_code"] & 0x80:
            if request["function_code"] in (3, 4):
                matches = parsed["fields"]["byte_count"] == request["fields"]["quantity"] * 2
            elif request["function_code"] == 6:
                matches = parsed["fields"] == request["fields"]
            else:
                matches = all(parsed["fields"][key] == request["fields"][key] for key in ("start_address", "quantity"))
        if not matches:
            issues.append({"event_index": index, "kind": "response_mismatch", "frame": parsed})
            continue
        pending.update(status="exception_response" if parsed["function_code"] & 0x80 else "response_received",
                       response_event=index, response=parsed, latency_ms=timestamp - pending["timestamp_ms"])
        pending = None
    return {"transactions": transactions, "issues": issues,
            "limitations": ["One master, complete frames, one outstanding request assumed",
                            "RTU response pairing is best effort; identical retries may be ambiguous",
                            "Pending at capture end does not establish timeout",
                            "Communication symptoms do not establish physical root causes"]}
