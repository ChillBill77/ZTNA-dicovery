from __future__ import annotations

from pydantic import BaseModel


class NodeLeft(BaseModel):
    id: str
    label: str
    size: int


class NodeRight(BaseModel):
    id: str
    label: str
    kind: str   # saas | ptr | port | raw | manual


class Link(BaseModel):
    src: str
    dst: str
    bytes: int
    flows: int
    users: int = 0


class SankeyDelta(BaseModel):
    ts: str
    window_s: int
    nodes_left: list[NodeLeft]
    nodes_right: list[NodeRight]
    links: list[Link]
    lossy: bool = False
    dropped_count: int = 0
    truncated: bool = False
    total_links: int | None = None
