from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


@dataclass(frozen=True)
class SessionData:
    user_upn: str
    roles: set[str]
    csrf: str
    exp: int  # unix seconds


class SessionCodec:
    """Signed, timestamped cookie-session codec.

    Backed by ``itsdangerous.URLSafeTimedSerializer`` (HMAC-SHA1, strong
    enough for session integrity given a ≥ 32-byte secret). Expiration is
    enforced twice: by the serializer's ``max_age`` (TTL since sign-time) and
    by the ``exp`` claim embedded in the payload (absolute Unix seconds),
    whichever comes first.
    """

    MIN_SECRET_BYTES = 32

    def __init__(self, secret: str, ttl_s: int = 8 * 3600) -> None:
        if len(secret) < self.MIN_SECRET_BYTES:
            raise ValueError(
                f"session secret must be ≥ {self.MIN_SECRET_BYTES} bytes"
            )
        self._serializer = URLSafeTimedSerializer(secret, salt="ztna-session")
        self._ttl = ttl_s

    def encode(self, data: SessionData) -> str:
        payload: dict[str, Any] = {**asdict(data), "roles": sorted(data.roles)}
        return self._serializer.dumps(payload)

    def decode(self, token: str) -> SessionData:
        try:
            raw = self._serializer.loads(token, max_age=self._ttl)
        except (BadSignature, SignatureExpired) as exc:
            raise ValueError(f"invalid session: {exc}") from exc
        if raw["exp"] < int(time.time()):
            raise ValueError("session expired")
        return SessionData(
            user_upn=raw["user_upn"],
            roles=set(raw["roles"]),
            csrf=raw["csrf"],
            exp=raw["exp"],
        )
