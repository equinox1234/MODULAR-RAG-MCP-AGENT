"""The documented entry points must all reach the real stdio server."""

from pathlib import Path


def test_main_module_forwards_to_mcp_server(monkeypatch):
    import main as entry
    import src.mcp_server.server as server

    calls = []
    monkeypatch.setattr(server, "main", lambda: calls.append(True) or 7)

    assert entry.main() == 7
    assert calls == [True]


def test_console_script_targets_the_real_server():
    """`mcp-server` used to point at the old stub in main.py."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert 'mcp-server = "src.mcp_server.server:main"' in text


def test_server_main_is_importable_without_starting_a_server():
    from src.mcp_server.server import main as server_main

    assert callable(server_main)
