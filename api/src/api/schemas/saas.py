from __future__ import annotations

from pydantic import BaseModel, Field


class SaasIn(BaseModel):
    name: str = Field(min_length=1)
    vendor: str | None = None
    fqdn_pattern: str = Field(min_length=2)   # e.g. ".office365.com"
    category: str | None = None
    priority: int = 100


class SaasEntry(SaasIn):
    id: int
    source: str
