from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.auth.session import SessionCodec
from api.dependencies import redis_client
from api.settings import Settings
from api.ws_fanout import ClientState, SankeyFanout

router = APIRouter(tags=["ws"])

_fanout: SankeyFanout | None = None

# Process-local map of live WebSocket connections keyed by user_upn. Second
# and subsequent connect attempts for the same user close immediately with
# code 1008 (policy violation).
_active_upns: set[str] = set()
_active_lock = asyncio.Lock()


async def startup() -> None:
    global _fanout  # noqa: PLW0603 — lifespan-managed singleton
    _fanout = SankeyFanout(redis=redis_client())
    await _fanout.start()


async def shutdown() -> None:
    if _fanout is not None:
        await _fanout.stop()


def _resolve_cookie_user(ws: WebSocket) -> str | None:
    """Decode the session cookie on the WS upgrade request.

    Returns the authenticated user_upn, or ``None`` if no session is present
    or the token is invalid. Bearer-token flows are not currently supported
    on the WS handshake (browsers cannot set arbitrary headers on
    ``WebSocket``); callers use the cookie path.
    """

    cookie = ws.cookies.get("session")
    if not cookie:
        return None
    try:
        data = SessionCodec(Settings().session_secret).decode(cookie)
    except ValueError:
        return None
    if "viewer" not in data.roles:
        return None
    return data.user_upn


@router.websocket("/ws/sankey")
async def ws_sankey(ws: WebSocket) -> None:
    if _fanout is None:
        await ws.close(code=1011)
        return

    upn = _resolve_cookie_user(ws)
    if upn is None:
        # No valid session cookie or missing viewer role → 1008 policy violation.
        await ws.close(code=1008)
        return

    async with _active_lock:
        if upn in _active_upns:
            await ws.close(code=1008)
            return
        _active_upns.add(upn)

    await ws.accept()

    async def _send(payload: str) -> None:
        await ws.send_text(payload)

    client = ClientState(send=_send, filters={})
    _fanout.add_client(client)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if "filter" in msg:
                    client.filters = msg["filter"]
            except Exception:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        _fanout.remove_client(client)
        async with _active_lock:
            _active_upns.discard(upn)
