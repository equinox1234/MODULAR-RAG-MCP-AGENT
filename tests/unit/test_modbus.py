"""Protocol vectors and malformed frames for the RTU analysis tool."""
import pytest

from src.core.modbus import crc16, parse_rtu_frame


def frame(body):
    data = bytes.fromhex(body)
    return (data + crc16(data).to_bytes(2, "little")).hex()


def test_known_crc_vector():
    result = parse_rtu_frame("01 03 00 00 00 02 C4 0B", "request")
    assert result["valid"]
    assert result["fields"] == {"start_address": 0, "quantity": 2}


def test_crc_corruption():
    result = parse_rtu_frame("01 03 00 00 00 02 C4 00", "request")
    assert not result["valid"]
    assert not result["crc"]["valid"]


@pytest.mark.parametrize("body,direction,field,value", [
    ("01 03 04 00 64 00 C8", "response", "register_values", [100, 200]),
    ("01 83 02", "response", "exception_code", 2),
    ("01 06 00 01 00 05", "request", "register_value", 5),
    ("01 10 00 00 00 02 04 00 01 00 02", "request", "register_values", [1, 2]),
    ("01 10 00 00 00 02", "response", "quantity", 2),
])
def test_supported_frames(body, direction, field, value):
    result = parse_rtu_frame(frame(body), direction)
    assert result["valid"]
    assert result["fields"][field] == value


@pytest.mark.parametrize("body,direction", [
    ("01 03 03 00 01 00", "response"),
    ("01 03 00 00 00 00", "request"),
    ("01 03 FF FF 00 02", "request"),
    ("01 10 00 00 00 02 02 00 01", "request"),
    ("01 83 02", "request"), ("00 03 00 00 00 01", "request"),
    ("00 06 00 00 00 01", "response"), ("F8 06 00 00 00 01", "request"),
    ("01 03", "response"), ("01 01 00 00 00 01", "request"),
])
def test_invalid_protocol_frames(body, direction):
    assert not parse_rtu_frame(frame(body), direction)["valid"]


@pytest.mark.parametrize("text", ["", "abc", "zz", "01", "00" * 257])
def test_invalid_hex(text):
    assert not parse_rtu_frame(text, "request")["valid"]


def test_explicit_direction_required():
    assert not parse_rtu_frame("010300000002c40b", "TX")["valid"]


def test_broadcast_write():
    result = parse_rtu_frame(frame("00 06 00 00 00 01"), "request")
    assert result["valid"]
    assert result["warnings"]
