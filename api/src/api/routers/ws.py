from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.dependencies import redis_client
from api.ws_fanout import ClientState, SankeyFanout

router = APIRouter(tags=["ws"])

_fanout: SankeyFanout | None = None


async def startup() -> None:
    global _fanout  # noqa: PLW0603 — lifespan-managed singleton
    _fanout = SankeyFanout(redis=redis_client())
    await _fanout.start()


async def shutdown() -> None:
    if _fanout is not None:
        await _fanout.stop()


@router.websocket("/ws/sankey")
async def ws_sankey(ws: WebSocket) -> None:
    if _fanout is None:
        await ws.close(code=1011)
        return
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
