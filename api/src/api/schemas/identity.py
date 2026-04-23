from __future__ import annotations

from pydantic import BaseModel


class IdentityResolution(BaseModel):
    """Flattened view of the binding covering ``(src_ip, at)``.

    ``user_upn`` is ``None`` when no live binding exists; the other fields are
    ``None`` in that case. Otherwise every field is populated: ``groups`` is a
    ``list[str]`` sorted by group name, and ``ttl_remaining`` is clamped ≥ 0.
    """

    user_upn: str | None
    source: str | None = None
    confidence: int | None = None
    groups: list[str] = []
    ttl_remaining: int | None = None
