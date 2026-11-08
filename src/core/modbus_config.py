"""Compare user-supplied RTU configuration; never read or modify a device."""
from __future__ import annotations

import math


PARITY = {"e": "even", "even": "even", "偶": "even", "o": "odd", "odd": "odd", "奇": "odd",
          "n": "none", "none": "none", "无": "none"}
COMMON_FIELDS = {"baudrate", "data_bits", "parity", "stop_bits"}


def check_modbus_config(master: dict, slave: dict | None = None) -> dict:
    """Return conflicts and unknown comparisons, not a physical root cause."""
    if not isinstance(master, dict) or slave is not None and not isinstance(slave, dict):
        raise ValueError("master/slave must be configuration objects")
    source = {"master": master, "slave": slave or {}}
    normalized = {"master": {}, "slave": {}}
    errors, warnings, checks = [], [], []
    for role, values in source.items():
        allowed = COMMON_FIELDS | ({"target_address", "response_timeout_ms"} if role == "master" else {"address", "max_response_ms"})
        if set(values) - allowed:
            raise ValueError("Unsupported configuration fields")
        for key, value in values.items():
            valid = True
            if key == "parity":
                value = PARITY.get(value.strip().lower()) if isinstance(value, str) else None
                valid = value is not None
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                valid = False
            elif key == "baudrate":
                valid = isinstance(value, int) and value > 0
            elif key == "data_bits":
                valid = value == 8
            elif key == "stop_bits":
                valid = value in (1, 2)
            elif key in {"target_address", "address"}:
                valid = isinstance(value, int) and (0 if key == "target_address" else 1) <= value <= 247
            else:
                valid = value > 0
            if not valid:
                errors.append({"role": role, "field": key, "code": "invalid_value"})
            else:
                normalized[role][key] = value
        if normalized[role].get("parity") == "none" and normalized[role].get("stop_bits") == 1:
            warnings.append({"role": role, "code": "verify_device_specific_8N1",
                             "message": "请核对厂商文档；该帧格式不能仅凭此工具判定设备是否支持。"})
    for field in sorted(COMMON_FIELDS):
        left, right = normalized["master"].get(field), normalized["slave"].get(field)
        checks.append({"field": field, "master": left, "slave": right,
                       "result": "unknown" if left is None or right is None else "match" if left == right else "conflict"})
    target = normalized["master"].get("target_address")
    address = normalized["slave"].get("address")
    checks.append({"field": "slave_address", "master": target, "slave": address,
                   "result": "broadcast" if target == 0 else "unknown" if target is None or address is None else "match" if target == address else "conflict"})
    timeout = normalized["master"].get("response_timeout_ms")
    maximum = normalized["slave"].get("max_response_ms")
    if target == 0:
        warnings.append({"code": "broadcast_no_response", "message": "广播写请求不期待响应，不能按单播超时诊断。"})
    elif timeout is not None and maximum is not None and timeout <= maximum:
        warnings.append({"code": "insufficient_timeout_margin",
                         "message": "主站超时未超过给定从站最大响应时间，请核对传输与处理余量。"})
    conflicts = [check for check in checks if check["result"] == "conflict"]
    unknown = [check["field"] for check in checks if check["result"] == "unknown"]
    status = "invalid_config" if errors else "conflict" if conflicts else "incomplete" if unknown else "consistent"
    return {"status": status, "checks": checks, "errors": errors, "warnings": warnings,
            "unknown_fields": unknown, "device_readback": False,
            "limitations": ["Only compares supplied configuration; not a device readback",
                            "Consistent settings do not establish working communication",
                            "A configuration conflict is not proof of the sole physical root cause"]}
