from types import SimpleNamespace

import pytest

from src.mcp_server.protocol_handler import ProtocolHandler, create_mcp_server, get_protocol_handler
from src.mcp_server.tools.modbus_tools import ModbusTools, register_tools


@pytest.fixture
def handler():
    protocol = ProtocolHandler("test", "1")
    knowledge = SimpleNamespace(answer=lambda query, **kwargs: {"citations": [{"page": 48}], "mode": "extractive"})
    fake_agent = SimpleNamespace(run=lambda *a, **kw: {"status": "completed", "answer": "test", "events": []})
    register_tools(protocol, ModbusTools(knowledge, lambda max_steps: fake_agent))
    return protocol


@pytest.mark.asyncio
async def test_search_is_structured_and_does_not_need_llm(handler):
    result = await handler.execute_tool("search_modbus_docs", {"query": "异常码02"})
    assert result.isError is False
    assert result.structuredContent["citations"][0]["page"] == 48


@pytest.mark.asyncio
async def test_log_analysis_preserves_pending(handler):
    result = await handler.execute_tool("analyze_modbus_log", {"events": [
        {"timestamp_ms": 0, "direction": "TX", "hex_frame": "01 03 00 00 00 02 C4 0B"}]})
    assert result.structuredContent["transactions"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_config_missing_peer_is_incomplete(handler):
    result = await handler.execute_tool("check_modbus_config", {"master": {"baudrate": 9600}})
    assert result.structuredContent["status"] == "incomplete"


@pytest.mark.asyncio
async def test_agent_adapter_does_not_echo_raw_input_events(handler):
    result = await handler.execute_tool("run_modbus_agent", {"question": "测试"})
    assert not result.isError
    assert "events" not in result.structuredContent


@pytest.mark.asyncio
@pytest.mark.parametrize("name,arguments", [
    ("search_modbus_docs", {"query": "q", "top_k": True}),
    ("search_modbus_docs", {"query": "q", "path": "private"}),
    ("analyze_modbus_log", {"events": [], "timeout_ms": float("nan")}),
    ("analyze_modbus_log", {"events": [{}]}),
    ("check_modbus_config", {"master": {"api_key": "do-not-print"}}),
    ("run_modbus_agent", {"question": "q", "max_steps": 100}),
])
async def test_invalid_arguments_are_errors_without_echoing_values(handler, name, arguments):
    result = await handler.execute_tool(name, arguments)
    assert result.isError
    assert result.structuredContent["error"]["code"] == "invalid_arguments"
    assert "do-not-print" not in result.content[0].text


@pytest.mark.asyncio
async def test_configuration_errors_surface_their_fix_hint():
    """A missing dense index must tell the caller how to fix it, not go generic."""
    protocol = ProtocolHandler("test", "1")
    knowledge = SimpleNamespace(
        answer=lambda query, **kwargs: (_ for _ in ()).throw(
            ValueError("Modbus dense index unavailable (stale). Run: python -m scripts.build_modbus_dense_index --force")
        )
    )
    register_tools(protocol, ModbusTools(knowledge, lambda max_steps: SimpleNamespace()))

    result = await protocol.execute_tool("search_modbus_docs", {"query": "异常码02"})

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "tool_error"
    assert "build_modbus_dense_index" in result.structuredContent["error"]["message"]


def test_original_and_domain_tools_are_registered_together():
    names = get_protocol_handler(create_mcp_server("test", "1")).tools
    assert {"query_knowledge_hub", "list_collections", "get_document_summary",
            "search_modbus_docs", "analyze_modbus_log", "check_modbus_config", "run_modbus_agent"} <= set(names)
