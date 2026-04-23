from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RawFlow(BaseModel):
    time: datetime
    src_ip: str
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    flow_count: int
    source: str


class RawFlowsPage(BaseModel):
    items: list[RawFlow]
    next_cursor: str | None = None
    total_est: int | None = None
