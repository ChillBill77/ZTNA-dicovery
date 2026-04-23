"""Metric placeholders — swap to prometheus_client in P4.

The correlator code references these module-level counters. Keeping them as
plain ints lets P2 progress without an observability story.
"""
from __future__ import annotations

dropped_flows_total: int = 0
unknown_user_ratio: float = 0.0       # always 0.0 in P2 (no identity)
lcd_miss_total: int = 0                # always 0 in P2
queue_depth: dict[str, int] = {}
writer_dropped_rows_total: int = 0


def reset_for_tests() -> None:
    global dropped_flows_total, unknown_user_ratio, lcd_miss_total, writer_dropped_rows_total
    dropped_flows_total = 0
    unknown_user_ratio = 0.0
    lcd_miss_total = 0
    writer_dropped_rows_total = 0
    queue_depth.clear()
