from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApplicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    owner: str | None = None
    dst_cidr: str
    dst_port_min: int | None = Field(default=None, ge=0, le=65535)
    dst_port_max: int | None = Field(default=None, ge=0, le=65535)
    proto: int | None = None
    priority: int = 100


class Application(ApplicationIn):
    id: int
    source: str
    created_at: datetime
    updated_at: datetime
    updated_by: str | None


class AuditEntry(BaseModel):
    id: int
    application_id: int
    changed_at: datetime
    changed_by: str
    op: Literal["create", "update", "delete"]
    before: dict | None
    after: dict | None
