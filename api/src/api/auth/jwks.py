from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class JwksCache:
    """Fetches and caches a provider's JWKS.

    - First call resolves the provider's ``.well-known/openid-configuration``
      to locate ``jwks_uri``, then fetches the JWKS document.
    - Cached entries expire after ``ttl_seconds`` (default 1 h); a cache miss
      on ``kid`` forces a refresh before giving up (handles in-band rotation).
    """

    def __init__(self, discovery_url: str, ttl_seconds: int = 3600) -> None:
        self._discovery_url = discovery_url
        self._ttl = ttl_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> dict[str, Any]:
        async with self._lock:
            if self._is_stale():
                await self._refresh()
            if kid in self._keys:
                return self._keys[kid]
            # Kid miss — refresh once and try again before failing.
            await self._refresh()
            if kid in self._keys:
                return self._keys[kid]
            raise KeyError(f"unknown kid: {kid}")

    def _is_stale(self) -> bool:
        return not self._keys or (time.monotonic() - self._fetched_at) > self._ttl

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            disc = (await client.get(self._discovery_url)).json()
            jwks = (await client.get(disc["jwks_uri"])).json()
        self._keys = {k["kid"]: k for k in jwks["keys"]}
        self._fetched_at = time.monotonic()
