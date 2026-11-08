"""Trace collector – receives finished TraceContext and persists them.

The collector is the bridge between in-memory TraceContext objects and
the on-disk JSON Lines log used by the Dashboard.  It is intentionally
decoupled from the logging module so that trace persistence remains
predictable and testable.

Persistence rules:
- honours ``observability.trace_enabled`` / ``observability.trace_file``;
- truncates long payloads (document text, chunk lists) before writing, so a
  trace stays a pointer to the evidence rather than a copy of it;
- writes one complete line per trace under a process-wide lock.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from src.core.settings import load_settings, resolve_path
from src.core.trace.trace_context import TraceContext

logger = logging.getLogger(__name__)

# Default absolute path for traces file (CWD-independent)
_DEFAULT_TRACES_PATH = resolve_path("logs/traces.jsonl")

MAX_TEXT_CHARS = 500
MAX_LIST_ITEMS = 20
MAX_DEPTH = 4
MAX_STAGES = 40

_WRITE_LOCK = threading.Lock()


def _truncate(value: Any, depth: int = 0) -> Any:
    """Bound the size of a trace payload without losing its shape."""
    if depth > MAX_DEPTH:
        return "…"
    if isinstance(value, str):
        if len(value) <= MAX_TEXT_CHARS:
            return value
        return f"{value[:MAX_TEXT_CHARS]}…(+{len(value) - MAX_TEXT_CHARS} chars)"
    if isinstance(value, dict):
        return {key: _truncate(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_truncate(item, depth + 1) for item in list(value)[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append(f"…(+{len(value) - MAX_LIST_ITEMS} items)")
        return items
    return value


class TraceCollector:
    """Collects finished traces and appends them to a JSON Lines file.

    Args:
        traces_path: File path for the ``traces.jsonl`` output.  When omitted,
            ``observability.trace_file`` from settings is used (falling back to
            ``logs/traces.jsonl``).
        enabled: Force-enable/disable persistence.  When omitted, follows
            ``observability.trace_enabled``.
    """

    def __init__(
        self,
        traces_path: Optional[str | Path] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        settings = None
        if traces_path is None or enabled is None:
            try:
                settings = load_settings()
            except Exception:  # a broken config must not break tracing entirely
                settings = None

        observability = getattr(settings, "observability", None)
        if enabled is None:
            self._enabled = bool(getattr(observability, "trace_enabled", True))
        else:
            self._enabled = bool(enabled)

        configured = getattr(observability, "trace_file", None) if observability else None
        path = traces_path or (resolve_path(configured) if configured else _DEFAULT_TRACES_PATH)
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        """Whether traces are being persisted."""
        return self._enabled

    def collect(self, trace: TraceContext) -> None:
        """Persist a single trace as one JSON line.

        If the trace has not been finished yet, ``finish()`` is called
        automatically so the output always contains timing data.

        Args:
            trace: A populated :class:`TraceContext`.
        """
        if not self._enabled:
            return
        if trace.finished_at is None:
            trace.finish()

        payload = trace.to_dict()
        payload["stages"] = [
            _truncate(stage) for stage in payload.get("stages", [])[:MAX_STAGES]
        ]
        if len(trace.stages) > MAX_STAGES:
            payload["stages_truncated"] = len(trace.stages) - MAX_STAGES
        payload["metadata"] = _truncate(payload.get("metadata", {}))

        line = json.dumps(payload, ensure_ascii=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with _WRITE_LOCK, self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception("Failed to write trace %s", trace.trace_id)

    @property
    def path(self) -> Path:
        """Return the resolved path of the traces file."""
        return self._path
