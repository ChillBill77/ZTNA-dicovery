from __future__ import annotations

from pydantic import BaseModel


class GroupMembers(BaseModel):
    group_id: str
    group_name: str
    size: int
    members: list[str]
    next_cursor: str | None = None
