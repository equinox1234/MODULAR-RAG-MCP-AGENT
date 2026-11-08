"""Actual SDK client/server process roundtrip, without paid model calls."""
import pytest

from scripts.modbus_mcp_demo import run_demo


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_stdio_domain_roundtrip():
    report = await run_demo()
    assert report["transport"] == "stdio"
    assert not report["model_calls_requested"]
    assert len(report["available_tools"]) >= 7
    assert any(c["page"] == 48 for c in report["results"]["search_modbus_docs"]["citations"])
    statuses = [tx["status"] for tx in report["results"]["analyze_modbus_log"]["transactions"]]
    assert statuses == ["response_received", "timeout", "pending"]
    config = report["results"]["check_modbus_config"]
    assert config["status"] == "conflict"
    assert [c["field"] for c in config["checks"] if c["result"] == "conflict"] == ["baudrate"]
