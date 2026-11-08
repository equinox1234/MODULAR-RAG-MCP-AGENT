"""Canonical log facts: keep device and register addresses distinct."""
from __future__ import annotations

import json
import re


def validate_analysis_scope(text: str, facts: list[dict]) -> None:
    """Reject a narrow set of known unsupported absolutes in broadcast-only tasks.

    This is a regression guard, not a general semantic entailment verifier.
    """
    if facts and all(fact["status"] == "broadcast" for fact in facts):
        clauses = re.split(r"[，,。；;\n]", text)
        for clause in clauses:
            if re.search(r"不能|无法|不代表|不意味着|并非|不可", clause):
                continue
            if re.search(r"(?:无|没有)(?:任何)?缺失信息|无需排查|不需要排查|(?:系统|设备)(?:完全|一切)正常|已(?:经)?排除(?:所有|其他|全部)故障|写入(?:已经|已)成功", clause):
                raise ValueError("Unsupported broadcast certainty")


def transaction_facts(analysis: dict) -> list[dict]:
    facts = []
    for tx in analysis["transactions"][:50]:
        request = tx["request"]
        fact = {"event": f"L{tx['request_event']}", "status": tx["status"],
                "slave_address": request["address"], "function_code": request["function_code"]}
        # Include only actual parsed fields, never invent a register address.
        fact.update(request["fields"])
        if "latency_ms" in tx:
            fact["latency_ms"] = tx["latency_ms"]
        if tx["status"] == "exception_response":
            fact["exception_code"] = tx["response"]["fields"]["exception_code"]
        facts.append(fact)
    return facts


def validate_log_claims(claims, expected: list[dict]) -> None:
    """Require a complete typed copy of observed transaction facts, order independent.

    Validates structured claims only; free-form explanations still need review.
    """
    if not isinstance(claims, list) or len(claims) != len(expected):
        raise ValueError("Incomplete log claims")
    if any(not isinstance(item, dict) or not isinstance(item.get("event"), str) for item in claims):
        raise ValueError("Invalid log claim")
    if len({item["event"] for item in claims}) != len(claims):
        raise ValueError("Duplicate event claim")
    # JSON serialization distinguishes true from 1 and rejects extra fields.
    actual = {item["event"]: json.dumps(item, sort_keys=True, ensure_ascii=False) for item in claims}
    required = {item["event"]: json.dumps(item, sort_keys=True, ensure_ascii=False) for item in expected}
    if actual != required:
        raise ValueError("Log claims contradict parsed facts")


def render_log_facts(facts: list[dict], issues: list[dict]) -> str:
    labels = {"response_received": "正常响应", "timeout": "超过阈值未匹配有效响应",
              "pending": "捕获结束时待响应，不能据此判超时", "broadcast": "广播写请求，不期待响应",
              "exception_response": "异常响应", "interrupted_by_new_request": "被新请求打断"}
    lines = ["### 已确认日志事实（程序解析）"]
    for fact in facts:
        values = [f"从站地址={fact['slave_address']}", f"功能码=0x{fact['function_code']:02X}"]
        for key, label in [("start_address", "寄存器起始地址"), ("quantity", "寄存器数量"),
                           ("register_address", "写入寄存器地址"), ("register_value", "写入值"),
                           ("latency_ms", "响应延迟ms"), ("exception_code", "异常码")]:
            if key in fact:
                values.append(f"{label}={fact[key]}")
        values.append(f"状态={fact['status']}（{labels.get(fact['status'], fact['status'])}）")
        lines.append(f"- [{fact['event']}] " + "；".join(values))
    for issue in issues:
        lines.append(f"- [{issue['event']}] {issue['kind']}：" + "; ".join(issue.get("errors", [])))
    return "\n".join(lines)


def broadcast_answer(question: str, facts: list[dict], issues: list[dict], citations: list[dict]) -> str | None:
    """Explain a broadcast task deterministically only with retrieved original evidence.

    Does not claim the remote device received or executed the write operation.
    Missing or inapplicable evidence leaves the task to the normal answer path.
    """
    if not facts or not all(fact["status"] == "broadcast" for fact in facts):
        return None
    if not re.search(r"广播|broadcast|地址\s*0", question, re.I):
        return None
    evidence = next((c for c in citations if c.get("kind") == "official_pdf"
                     and "broadcast" in c.get("text", "").lower()
                     and re.search(r"no\s+response\s+is\s+returned", c["text"], re.I)), None)
    if evidence is None:
        return None
    return (render_log_facts(facts, issues) + "\n\n"
            f"检索到的协议说明：广播写请求不返回响应。[{evidence['id']}] "
            "因此，这份广播记录没有回复符合协议预期，不能按单播等待响应来判定超时。\n\n"
            "验证边界：本记录不能确认从站已接收或执行写入，也不能排除其他独立故障。"
            "若业务需要确认，应先核对目标从站地址、寄存器映射及当前状态，再使用适用的单播读回或设备状态反馈验证。")
