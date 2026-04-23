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
    """Extract the trace-id from a W3C ``traceparent`` header and store it in
    the context-var so later log lines on the same task pick it up.

    Format: ``00-<trace-id>-<span-id>-<flags>``.
    """

    parts = traceparent.split("-")
    tid = parts[1] if len(parts) >= 2 else traceparent
    _trace_id.set(tid)


def _hash(v: str) -> str:
    return "sha256:" + hashlib.sha256(v.encode()).hexdigest()[:16]


def _processor(record: dict[str, Any]) -> bool:
    """loguru filter that mutates the record in place.

    Returning True lets the sink write the record. Returning False drops it;
    we never drop here.
    """

    extra = record["extra"]
    extra["trace_id"] = _trace_id.get()
    if record["level"].name in {"INFO", "WARNING", "ERROR", "CRITICAL"}:
        for k in list(extra.keys()):
            if k in _PII_KEYS and isinstance(extra[k], str):
                extra[k] = _hash(extra[k])
    return True


def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        serialize=True,
        filter=_processor,
    )
