import copy

import pytest

from src.core.modbus_config import check_modbus_config


MASTER = {"baudrate": 9600, "data_bits": 8, "parity": "E", "stop_bits": 1, "target_address": 1, "response_timeout_ms": 1000}
SLAVE = {"baudrate": 9600, "data_bits": 8, "parity": "even", "stop_bits": 1, "address": 1, "max_response_ms": 400}


def test_matching_settings_are_not_device_readback():
    result = check_modbus_config(MASTER, SLAVE)
    assert result["status"] == "consistent"
    assert result["device_readback"] is False
    assert not result["unknown_fields"]


def test_missing_slave_is_unknown_not_conflicting():
    result = check_modbus_config(MASTER)
    assert result["status"] == "incomplete"
    assert all(check["result"] == "unknown" for check in result["checks"])


@pytest.mark.parametrize("field,value", [("baudrate", 19200), ("parity", "odd"), ("stop_bits", 2), ("address", 2)])
def test_specific_supplied_mismatches(field, value):
    slave = {**SLAVE, field: value}
    result = check_modbus_config(MASTER, slave)
    assert result["status"] == "conflict"
    assert len([c for c in result["checks"] if c["result"] == "conflict"]) == 1


def test_broadcast_target_does_not_mismatch_individual_slave():
    result = check_modbus_config({**MASTER, "target_address": 0}, SLAVE)
    assert result["status"] == "consistent"
    assert result["checks"][-1]["result"] == "broadcast"
    assert any(w["code"] == "broadcast_no_response" for w in result["warnings"])


def test_timeout_margin_is_a_warning():
    result = check_modbus_config({**MASTER, "response_timeout_ms": 200}, SLAVE)
    assert any(w["code"] == "insufficient_timeout_margin" for w in result["warnings"])


@pytest.mark.parametrize("field,value", [("baudrate", True), ("baudrate", -1), ("target_address", 248),
                                        ("parity", "strange"), ("data_bits", 7), ("response_timeout_ms", float("nan"))])
def test_invalid_values_not_compared_as_valid_settings(field, value):
    result = check_modbus_config({**MASTER, field: value}, SLAVE)
    assert result["status"] == "invalid_config"
    assert any(error["field"] == field for error in result["errors"])


def test_does_not_mutate_inputs():
    original = copy.deepcopy(MASTER)
    check_modbus_config(MASTER, SLAVE)
    assert MASTER == original


def test_unknown_fields_are_not_silently_accepted():
    with pytest.raises(ValueError):
        check_modbus_config({"api_key": "do-not-accept"})
