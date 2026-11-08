"""Deterministic Modbus RTU analysis. No device access or LLM required."""

from __future__ import annotations

import re
from typing import Any


EXCEPTIONS = {
    1: "Illegal function", 2: "Illegal data address", 3: "Illegal data value",
    4: "Server device failure", 5: "Acknowledge", 6: "Server device busy",
    8: "Memory parity error", 10: "Gateway path unavailable",
    11: "Gateway target device failed to respond",
}


def crc16(data: bytes) -> int:
    """Return Modbus CRC-16; RTU transmits its low byte first."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse_rtu_frame(hex_frame: str, direction: str) -> dict[str, Any]:
    """Parse one complete frame; direction is request or response.

    Invalid input returns structured errors. A valid CRC establishes integrity,
    not that a response matches a request or that register values are meaningful.
    """
    result: dict[str, Any] = {"valid": False, "errors": [], "warnings": [], "fields": {}}
    errors = result["errors"]
    if direction not in ("request", "response"):
        errors.append("direction must be request or response")
        return result
    result["direction"] = direction
    if not isinstance(hex_frame, str):
        errors.append("hex_frame must be a hexadecimal string")
        return result
    compact = re.sub(r"\s+", "", hex_frame)
    if not compact or len(compact) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", compact):
        errors.append("Expected complete hexadecimal bytes separated optionally by whitespace")
        return result
    if not 4 <= len(compact) // 2 <= 256:
        errors.append("RTU frame length must be between 4 and 256 bytes")
        return result
    frame = bytes.fromhex(compact)
    result["raw_hex"] = frame.hex(" ").upper()
    address, function = frame[:2]
    result.update(address=address, function_code=function)
    expected = crc16(frame[:-2])
    received = int.from_bytes(frame[-2:], "little")
    result["crc"] = {"expected": f"{expected:04X}", "received": f"{received:04X}",
                     "valid": expected == received}
    if expected != received:
        errors.append("CRC mismatch; decoded fields are untrusted")
    if address > 247 or (address == 0 and direction == "response"):
        errors.append("Invalid device address for this direction")
    if address == 0:
        result["warnings"].append("Broadcast request: no response is expected")
        if function in (3, 4):
            errors.append("Read requests cannot use broadcast address")
    payload = frame[2:-2]
    fields = result["fields"]

    def word(offset: int) -> int:
        return int.from_bytes(payload[offset:offset + 2], "big")

    def quantity(value: int, maximum: int) -> None:
        if not 1 <= value <= maximum:
            errors.append(f"Register quantity must be between 1 and {maximum}")
        if fields["start_address"] + value > 65536:
            errors.append("Register range exceeds address space")

    if function & 0x80:
        if direction != "response" or len(payload) != 1:
            errors.append("Exception must be a response with one exception byte")
        else:
            fields.update(original_function=function & 0x7F, exception_code=payload[0],
                          exception_name=EXCEPTIONS.get(payload[0], "Unknown exception"))
    elif function in (3, 4) and direction == "response":
        if not payload:
            errors.append("Missing byte count")
        else:
            count = payload[0]
            fields["byte_count"] = count
            if count != len(payload) - 1 or count % 2 or not 2 <= count <= 250:
                errors.append("Invalid register response byte count")
            else:
                fields["register_values"] = [word(i) for i in range(1, len(payload), 2)]
    elif function in (3, 4, 6, 16):
        if function == 16 and direction == "request":
            if len(payload) < 5:
                errors.append("Write-multiple request header is incomplete")
            else:
                fields.update(start_address=word(0), quantity=word(2), byte_count=payload[4])
                quantity(word(2), 123)
                if payload[4] != word(2) * 2 or len(payload) != 5 + payload[4]:
                    errors.append("Write-multiple byte count does not match quantity or frame length")
                else:
                    fields["register_values"] = [word(i) for i in range(5, len(payload), 2)]
        elif len(payload) != 4:
            errors.append("Expected four payload bytes")
        elif function == 6:
            fields.update(register_address=word(0), register_value=word(2))
        else:
            fields.update(start_address=word(0), quantity=word(2))
            quantity(word(2), 123 if function == 16 else 125)
    else:
        errors.append(f"Unsupported function code: {function:02X}")
    result["valid"] = not errors
    return result
