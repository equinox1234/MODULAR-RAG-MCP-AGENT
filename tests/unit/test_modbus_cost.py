import pytest
from src.observability.dashboard.services.modbus_cost import estimate_calls


def test_known_price_and_separate_tiers():
    result = estimate_calls("qwen3.7-flash", "https://dashscope.aliyuncs.com/compatible-mode/v1", [
        {"usage": {"prompt_tokens": 9164, "completion_tokens": 3376}}])
    assert result["amount"] == pytest.approx(0.0045336)
    tier = estimate_calls("qwen3.7-flash", "https://dashscope.aliyuncs.com/v1", [
        {"usage": {"prompt_tokens": 20000, "completion_tokens": 100}},
        {"usage": {"prompt_tokens": 20000, "completion_tokens": 100}}])
    assert tier["amount"] == pytest.approx(0.00816)


def test_unknown_endpoint_and_failed_calls_are_not_guessed():
    assert estimate_calls("qwen3.7-flash", "https://proxy.invalid", [])['amount'] is None
    assert estimate_calls("qwen3.7-flash", "https://dashscope.aliyuncs.com/v1", [{"failed": True}])['amount'] is None
