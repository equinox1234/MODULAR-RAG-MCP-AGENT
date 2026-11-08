"""Build the Modbus dense index (Chroma) for hybrid retrieval.

Usage:
    python -m scripts.build_modbus_dense_index
    python -m scripts.build_modbus_dense_index --force --batch-size 32

This calls the configured embedding API once per chunk batch, so it costs money
and needs network access.  The BM25 index is not touched; `retrieval_mode: bm25`
keeps working without this step.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.core.modbus_dense import build_dense_index


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build the Modbus dense (Chroma) index")
    parser.add_argument("--force", action="store_true", help="Clear the collection and re-embed everything")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Chunks per embedding request (DashScope caps this at 20)")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    def progress(done: int, total: int) -> None:
        print(f"  embedded {done}/{total}", flush=True)

    report = build_dense_index(
        batch_size=args.batch_size, force=args.force, progress=progress
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
