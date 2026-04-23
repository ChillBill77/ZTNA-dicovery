from __future__ import annotations

from typing import Any


async def exchange_code(code: str) -> dict[str, Any]:
    """Exchange an authorization ``code`` for verified id_token claims.

    Production runtime plugs authlib / httpx here to hit the IdP token
    endpoint. Tests monkeypatch this to return crafted claims without
    network traffic.
    """

    raise NotImplementedError("exchange_code must be monkeypatched in tests")
