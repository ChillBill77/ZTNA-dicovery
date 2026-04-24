from __future__ import annotations

import contextvars
import hashlib
import sys
from typing import Any

from loguru import logger

_PII_KEYS = {"upn", "src_ip", "user_upn", "ip"}
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)


def set_trace_id(traceparent: str) -> None:
    """Extract the trace-id from a W3C ``traceparent`` header and stash it in
    the async context-var so later log lines on the same task pick it up.

    Format: ``00-<trace-id>-<span-id>-<flags>``.
    """

    parts = traceparent.split("-")
    tid = parts[1] if len(parts) >= 2 else traceparent
    _trace_id.set(tid)


def _hash(v: str) -> str:
    return "sha256:" + hashlib.sha256(v.encode()).hexdigest()[:16]


def _processor(record: dict[str, Any]) -> bool:
    """loguru filter — inject trace_id and hash PII at INFO+."""

    extra = record["extra"]
    extra["trace_id"] = _trace_id.get()
    if record["level"].name in {"INFO", "WARNING", "ERROR", "CRITICAL"}:
        for k in list(extra.keys()):
            if k in _PII_KEYS and isinstance(extra[k], str):
                extra[k] = _hash(extra[k])
    return True


def configure(level: str = "INFO") -> None:
    """Install a structured JSON sink on loguru at the requested level.

    Adds a ``trace_id`` extra field (empty unless :func:`set_trace_id` has been
    called on the current task) and hashes ``upn`` / ``src_ip`` / ``user_upn``
    / ``ip`` extras at INFO and above (raw only at DEBUG).

    Idempotent — removes any previously installed sinks first so callers can
    safely invoke it multiple times.
    """

    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=False,
        filter=_processor,
    )


# Explicit alias matching the api-side name so call sites can be uniform.
configure_logging = configure
