import pytest

from src.core.modbus import crc16
from src.core.modbus_log import analyze_rtu_log


def event(t, direction, body):
    data = bytes.fromhex(body)
    return {"timestamp_ms": t, "direction": direction,
            "hex_frame": (data + crc16(data).to_bytes(2, "little")).hex()}


def request(t=0):
    return event(t, "TX", "01 03 00 00 00 02")


def response(t=20):
    return event(t, "RX", "01 03 04 00 64 00 C8")


def test_pair():
    tx = analyze_rtu_log([request(), response()])["transactions"][0]
    assert tx["status"] == "response_received"
    assert tx["latency_ms"] == 20


def test_capture_end_not_timeout():
    assert analyze_rtu_log([request()])["transactions"][0]["status"] == "pending"


def test_timeout_and_late_response():
    result = analyze_rtu_log([request(), response(1001)])
    assert result["transactions"][0]["status"] == "timeout"
    assert result["issues"][0]["kind"] == "unmatched_response"


def test_deadline_boundary():
    assert analyze_rtu_log([request(), response(1000)])["transactions"][0]["status"] == "response_received"


def test_exception():
    result = analyze_rtu_log([request(), event(20, "RX", "01 83 02")])
    assert result["transactions"][0]["status"] == "exception_response"


@pytest.mark.parametrize("body", ["02 03 04 00 64 00 C8", "01 03 02 00 64", "01 04 04 00 64 00 C8"])
def test_response_mismatch(body):
    result = analyze_rtu_log([request(), event(20, "RX", body)])
    assert result["transactions"][0]["status"] == "pending"
    assert result["issues"][0]["kind"] == "response_mismatch"


def test_invalid_crc_does_not_complete_request():
    bad = response()
    bad["hex_frame"] = bad["hex_frame"][:-4] + "0000"
    result = analyze_rtu_log([request(), bad, response(30)])
    assert result["issues"][0]["kind"] == "invalid_frame"
    assert result["transactions"][0]["latency_ms"] == 30


def test_overlapping_requests():
    result = analyze_rtu_log([request(), request(100)])
    assert result["transactions"][0]["status"] == "interrupted_by_new_request"


def test_broadcast():
    result = analyze_rtu_log([event(0, "TX", "00 06 00 01 00 05")])
    assert result["transactions"][0]["status"] == "broadcast"


def test_write_echo_mismatch():
    result = analyze_rtu_log([event(0, "TX", "01 06 00 01 00 05"), event(20, "RX", "01 06 00 01 00 06")])
    assert result["issues"][0]["kind"] == "response_mismatch"


@pytest.mark.parametrize("events", [[request(20), response(10)], [{"timestamp_ms": float("nan")}], [{"timestamp_ms": 0, "direction": "ERROR"}]])
def test_invalid_events(events):
    with pytest.raises(ValueError):
        analyze_rtu_log(events)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), True])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        analyze_rtu_log([], timeout)
