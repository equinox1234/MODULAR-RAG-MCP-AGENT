"""Run from project root: python -m scripts.analyze_modbus_log path/to/log.json."""
import argparse
import json
from pathlib import Path

from src.core.modbus_log import analyze_rtu_log


def main():
    parser = argparse.ArgumentParser(description="Analyze normalized Modbus RTU master logs")
    parser.add_argument("path", type=Path)
    parser.add_argument("--timeout-ms", type=float, default=1000)
    args = parser.parse_args()
    try:
        events = json.loads(args.path.read_text(encoding="utf-8"))
        if not isinstance(events, list):
            raise ValueError("Log must be a JSON array")
        print(json.dumps(analyze_rtu_log(events, args.timeout_ms), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
