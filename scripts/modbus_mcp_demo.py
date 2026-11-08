"""Exercise the real stdio MCP server; default demo uses no model API calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def run_demo(include_agent: bool = False) -> dict:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server.server"],
                                       cwd=str(ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    calls = [
        ("search_modbus_docs", {"query": "异常码2是什么意思", "top_k": 3}),
        ("analyze_modbus_log", {"events": json.loads((ROOT / "tests/fixtures/modbus_simulated_log.json").read_text(encoding="utf-8"))}),
        ("check_modbus_config", {"master": {"baudrate": 9600, "data_bits": 8, "parity": "E", "stop_bits": 1,
                                             "target_address": 1, "response_timeout_ms": 1000},
                                  "slave": {"baudrate": 19200, "data_bits": 8, "parity": "even", "stop_bits": 1,
                                            "address": 1, "max_response_ms": 400}}),
    ]
    if include_agent:
        calls.append(("run_modbus_agent", {"question": "主站向地址0发送广播写请求后没有回复，能确认写入成功吗？请查文档说明。",
            "events": [{"timestamp_ms": 0, "direction": "TX", "hex_frame": "00 06 00 01 00 05 19 D8"}]}))
    report = {"transport": "stdio", "model_calls_requested": include_agent, "results": {}}
    with anyio.fail_after(300 if include_agent else 90):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialization = await session.initialize()
                report["server"] = initialization.serverInfo.model_dump()
                report["available_tools"] = [tool.name for tool in (await session.list_tools()).tools]
                for name, arguments in calls:
                    result = await session.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(f"MCP tool failed: {name}")
                    payload = result.structuredContent
                    if payload is None:
                        payload = json.loads(next(item.text for item in result.content if item.type == "text"))
                    report["results"][name] = payload
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Live MCP stdio demo for Modbus domain tools")
    parser.add_argument("--agent", action="store_true", help="Also run the real paid model-backed Agent")
    parser.add_argument("--output", type=Path, default=ROOT / "data/modbus/mcp_demo.json")
    args = parser.parse_args()
    report = anyio.run(run_demo, args.agent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"transport": report["transport"], "tools": report["available_tools"],
                      "executed": list(report["results"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
