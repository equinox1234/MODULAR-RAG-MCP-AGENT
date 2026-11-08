import copy
import json

import pytest

from src.core.modbus_facts import render_log_facts, transaction_facts, validate_log_claims
from src.core.modbus_log import analyze_rtu_log
from src.core.modbus_agent import ModbusAgent
from tests.unit.test_modbus_agent import ScriptedLLM, Knowledge


REQUEST = {"timestamp_ms": 0, "direction": "TX", "hex_frame": "01 03 00 00 00 02 C4 0B"}
BROADCAST = {"timestamp_ms": 0, "direction": "TX", "hex_frame": "00 06 00 01 00 05 19 D8"}


def test_distinguishes_slave_register_start_and_quantity():
    analysis = analyze_rtu_log([REQUEST])
    fact = transaction_facts(analysis)[0]
    assert fact["slave_address"] == 1
    assert fact["start_address"] == 0
    assert fact["quantity"] == 2
    assert "address" not in fact
    rendered = render_log_facts([fact], [])
    assert "从站地址=1" in rendered
    assert "寄存器起始地址=0" in rendered


@pytest.mark.parametrize("key,value", [("start_address", 1), ("slave_address", 0), ("quantity", 1),
                                        ("status", "timeout"), ("start_address", False)])
def test_contradictory_claims_are_rejected(key, value):
    expected = transaction_facts(analyze_rtu_log([REQUEST]))
    claims = copy.deepcopy(expected)
    claims[0][key] = value
    with pytest.raises(ValueError):
        validate_log_claims(claims, expected)


def test_broadcast_cannot_be_claimed_pending():
    expected = transaction_facts(analyze_rtu_log([BROADCAST]))
    assert expected[0]["status"] == "broadcast"
    assert "start_address" not in expected[0]
    assert expected[0]["register_address"] == 1
    wrong = copy.deepcopy(expected)
    wrong[0]["status"] = "pending"
    with pytest.raises(ValueError):
        validate_log_claims(wrong, expected)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "extra"])
def test_incomplete_or_fabricated_claims_rejected(mutation):
    expected = transaction_facts(analyze_rtu_log([REQUEST]))
    actual = copy.deepcopy(expected)
    if mutation == "omit":
        actual.clear()
    elif mutation == "duplicate":
        actual += actual
    else:
        actual[0]["invented"] = 42
    with pytest.raises(ValueError):
        validate_log_claims(actual, expected)


def test_log_fact_repair_uses_correct_facts_and_discards_wrong_answer():
    facts = transaction_facts(analyze_rtu_log([BROADCAST]))
    wrong = copy.deepcopy(facts)
    wrong[0]["status"] = "pending"
    model = ScriptedLLM([{"action": "analyze_log"}, {"action": "search_docs", "query": "广播"},
                         {"action": "finish"}, {"log_claims": wrong, "analysis": "错误待响应结论 [D1]"},
                         {"log_claims": facts, "analysis": "广播请求不期待响应。[D1]"}])
    result = ModbusAgent(model, Knowledge()).run("广播没有响应", events=[BROADCAST])
    assert result["status"] == "completed"
    assert result["verified_log_claims"] == facts
    assert result["trace"][-1]["fact_format_repairs"] == 1
    assert "错误待响应结论" not in result["answer"]
    assert "状态=broadcast" in result["answer"]
    assert "状态=pending" not in result["answer"]
    observation = result["observations"][0]
    assert "general_limitations_not_event_facts" in observation
    assert "limitations" not in observation
    assert "general_limitations_not_event_facts" not in model.prompts[-1][-1].content


def test_two_wrong_log_claims_do_not_complete():
    model = ScriptedLLM([{"action": "analyze_log"}, {"action": "search_docs", "query": "广播"},
                         {"action": "finish"}, {"log_claims": [], "analysis": "没有事实 [D1]"},
                         {"log_claims": [], "analysis": "仍然错误 [D1]"}])
    result = ModbusAgent(model, Knowledge()).run("分析广播", events=[BROADCAST])
    assert result["status"] == "answer_error"
    assert "没有事实" not in result["answer"]
