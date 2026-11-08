"""Run the LangGraph agent using configured real LLM credentials."""
import argparse
import json
import sys
from pathlib import Path

from src.core.modbus_agent import ModbusAgent
from src.core.modbus_knowledge import ModbusKnowledge
from src.core.settings import load_settings
from src.libs.llm.llm_factory import LLMFactory


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="LangGraph Modbus RTU troubleshooting agent")
    parser.add_argument("question")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--device")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--timeout-ms", type=float, default=1000)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execution-mode", choices=["auto", "agent"], default="auto")
    args = parser.parse_args()
    settings = load_settings(args.config) if args.config else load_settings()
    try:
        if (settings.llm.api_key or "").startswith("YOUR_"):
            raise ValueError("Configure real model credentials first")
        events = json.loads(args.log.read_text(encoding="utf-8")) if args.log else None
        agent = ModbusAgent(LLMFactory.create(settings), ModbusKnowledge(), args.max_steps)
        state = agent.run(args.question, events=events, device=args.device, timeout_ms=args.timeout_ms, execution_mode=args.execution_mode)
        # Do not duplicate raw input logs in persisted output.
        state.pop("events", None)
        output = json.dumps(state, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        print(output)
        if state["status"] not in {"completed", "needs_input"}:
            raise SystemExit(1)
    except Exception as exc:
        # No raw provider exception messages in CLI output.
        parser.exit(1, f"Agent failed ({type(exc).__name__}); check configuration and local inputs.\n")


if __name__ == "__main__":
    main()
