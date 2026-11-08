"""python -m scripts.modbus_qa '问题' [--log path.json] [--llm]."""
import argparse
import json
import sys
from pathlib import Path

from src.core.modbus_knowledge import ModbusKnowledge


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Modbus domain retrieval and cited answers")
    parser.add_argument("question")
    parser.add_argument("--device", help="Explicit device scope, e.g. VT-100 (fictional)")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--timeout-ms", type=float, default=1000)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--llm", action="store_true", help="Use the configured real model; default extracts evidence")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        llm = None
        if args.llm:
            from src.core.settings import load_settings
            from src.libs.llm.llm_factory import LLMFactory
            settings = load_settings(args.config) if args.config else load_settings()
            key = settings.llm.api_key or ""
            if key.startswith("YOUR_"):
                raise ValueError("Configure a real LLM credential before using --llm")
            llm = LLMFactory.create(settings)
        events = json.loads(args.log.read_text(encoding="utf-8")) if args.log else None
        if events is not None and not isinstance(events, list):
            raise ValueError("Log must be a JSON array")
        result = ModbusKnowledge().answer(args.question, device=args.device, events=events,
                                         timeout_ms=args.timeout_ms, top_k=args.top_k, llm=llm)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
