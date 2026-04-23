from __future__ import annotations

import sys

from loguru import logger


def configure(level: str = "INFO") -> None:
    """Install a structured JSON sink on loguru at the requested level.

    Idempotent — removes any previously installed sinks first so callers can
    safely invoke it multiple times (e.g., after fork or reload).
    """

    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )
