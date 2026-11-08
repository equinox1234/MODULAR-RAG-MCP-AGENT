"""Modular RAG MCP Server - main entry point.

A thin wrapper so all three launch styles start the same stdio server:

    python main.py
    python -m src.mcp_server.server
    mcp-server                     # installed console script

The real implementation lives in :mod:`src.mcp_server.server`; this module only
exists so tooling and docs that point at ``main.py`` keep working.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Start the MCP server over stdio.

    Returns:
        int: Exit code (0 for success, non-zero for failure).
    """
    from src.mcp_server.server import main as run_server

    return run_server()


if __name__ == "__main__":
    sys.exit(main())
