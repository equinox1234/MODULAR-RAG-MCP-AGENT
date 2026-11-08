"""Read-only Modbus tools on the existing MCP server; no credentials in arguments."""
from __future__ import annotations

import asyncio
import json
from threading import Lock
from typing import Any

from jsonschema import Draft202012Validator
from mcp import types

from src.core.modbus_config import check_modbus_config
from src.core.modbus_log import analyze_rtu_log

EVENTS = {"type": "array", "maxItems": 500, "items": {
    "type": "object", "additionalProperties": False,
    "properties": {"timestamp_ms": {"type": "number", "minimum": 0},
                   "direction": {"enum": ["TX", "RX"]},
                   "hex_frame": {"type": "string", "minLength": 8, "maxLength": 1024}},
    "required": ["timestamp_ms", "direction", "hex_frame"]}}
CONFIG_FIELDS = {"baudrate": {"type": "integer", "minimum": 1}, "data_bits": {"const": 8},
                 "parity": {"type": "string", "minLength": 1, "maxLength": 8},
                 "stop_bits": {"enum": [1, 2]}}


def schema(properties, required):
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


SCHEMAS = {
    "search_modbus_docs": schema({"query": {"type": "string", "minLength": 1, "maxLength": 4000},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
        "device": {"type": "string", "minLength": 1, "maxLength": 80}}, ["query"]),
    "analyze_modbus_log": schema({"events": EVENTS,
        "timeout_ms": {"type": "number", "exclusiveMinimum": 0, "default": 1000}}, ["events"]),
    "check_modbus_config": schema({
        "master": schema({**CONFIG_FIELDS, "target_address": {"type": "integer", "minimum": 0, "maximum": 247},
                          "response_timeout_ms": {"type": "number", "exclusiveMinimum": 0}}, []),
        "slave": schema({**CONFIG_FIELDS, "address": {"type": "integer", "minimum": 1, "maximum": 247},
                         "max_response_ms": {"type": "number", "exclusiveMinimum": 0}}, [])}, ["master"]),
    "run_modbus_agent": schema({"question": {"type": "string", "minLength": 1, "maxLength": 4000},
        "events": EVENTS, "device": {"type": "string", "minLength": 1, "maxLength": 80},
        "timeout_ms": {"type": "number", "exclusiveMinimum": 0, "default": 1000},
        "max_steps": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
        "execution_mode": {"enum": ["auto", "agent"], "default": "auto"}}, ["question"]),
}
DESCRIPTIONS = {
    "search_modbus_docs": "Search local Modbus original PDF text; returns excerpts, versions, page citations. Offline in bm25 mode; hybrid mode embeds the query via the configured API. Explicit device scope needed for fictional VT-100 data.",
    "analyze_modbus_log": "Analyze up to 500 normalized master-side RTU events. Checks CRC, pairing and timeouts; capture-end pending is not timeout. No device access or model calls.",
    "check_modbus_config": "Compare supplied master/slave RTU settings. Missing values stay unknown; does not read or write devices, establish a root cause, or call a model.",
    "run_modbus_agent": "Run the LangGraph Modbus assistant with server-local model credentials. Makes paid LLM calls; may take minutes. Returns cited answer, tool observations and trace. Domain tools inside this Agent are local calls, not nested MCP calls.",
}


class ModbusTools:
    def __init__(self, knowledge=None, agent_factory=None):
        self._knowledge = knowledge
        self._agent_factory = agent_factory
        self._lock = Lock()

    def knowledge(self):
        with self._lock:
            if self._knowledge is None:
                from src.core.modbus_knowledge import ModbusKnowledge
                self._knowledge = ModbusKnowledge()
            return self._knowledge

    def execute(self, name: str, arguments: dict) -> dict:
        if name == "search_modbus_docs":
            return self.knowledge().answer(arguments["query"], top_k=arguments.get("top_k", 3), device=arguments.get("device"))
        if name == "analyze_modbus_log":
            return analyze_rtu_log(arguments["events"], arguments.get("timeout_ms", 1000))
        if name == "check_modbus_config":
            return check_modbus_config(**arguments)
        if name == "run_modbus_agent":
            if self._agent_factory is None:
                from src.core.modbus_agent import ModbusAgent
                from src.core.settings import load_settings
                from src.libs.llm.llm_factory import LLMFactory
                agent = ModbusAgent(LLMFactory.create(load_settings()), self.knowledge(), arguments.get("max_steps", 6))
            else:
                agent = self._agent_factory(arguments.get("max_steps", 6))
            result = agent.run(arguments["question"], events=arguments.get("events"),
                               device=arguments.get("device"), timeout_ms=arguments.get("timeout_ms", 1000),
                               execution_mode=arguments.get("execution_mode", "auto"))
            result.pop("events", None)
            return result
        raise ValueError("Unknown domain tool")


def register_tools(protocol_handler, service: ModbusTools | None = None) -> None:
    service = service or ModbusTools()
    for name, input_schema in SCHEMAS.items():
        def make_handler(tool_name, tool_schema):
            async def handler(**arguments: Any):
                try:
                    # Reject NaN/Infinity and non-JSON values before schema validation.
                    json.dumps(arguments, allow_nan=False)
                    if not Draft202012Validator(tool_schema).is_valid(arguments):
                        raise ValueError("Invalid arguments")
                except (ValueError, TypeError):
                    result, failed = {"error": {"code": "invalid_arguments",
                                                "message": "Check tool schema and normalized input values."}}, True
                else:
                    try:
                        result = await asyncio.to_thread(service.execute, tool_name, arguments)
                        failed = tool_name == "run_modbus_agent" and result.get("status") not in {"completed", "needs_input"}
                    except ValueError as exc:
                        # Our own configuration/validation messages are safe to show
                        # (e.g. "run scripts.build_modbus_dense_index"), unlike
                        # provider errors which may echo request details.
                        result, failed = {"error": {"code": "tool_error", "type": type(exc).__name__,
                                                    "message": str(exc)}}, True
                    except Exception as exc:
                        result, failed = {"error": {"code": "tool_execution_failed", "type": type(exc).__name__,
                                                   "message": "Check server-local corpus and model configuration."}}, True
                return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                                            structuredContent=result, isError=failed)
            return handler
        protocol_handler.register_tool(name, DESCRIPTIONS[name], input_schema, make_handler(name, input_schema))
