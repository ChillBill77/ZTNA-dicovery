from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from id_ingest.group_sync.entra_sync import EntraGroupSync

FIX = Path(__file__).parent.parent / "fixtures" / "graph_groups"


def _mock() -> httpx.MockTransport:
    pages = [
        json.loads((FIX / "transitive_member_of_page1.json").read_text()),
        json.loads((FIX / "transitive_member_of_page2.json").read_text()),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "access_token": "x",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_sync_user_returns_flattened_group_list() -> None:
    sync = EntraGroupSync(
        tenant_id="tid",
        client_id="cid",
        client_secret="sec",
        transport=_mock(),
    )
    upserts = await sync.sync_user("alice@corp.example")
    ids = sorted(u["group_id"] for u in upserts)
    assert ids == ["g-all", "g-m365", "g-sales"]
    assert all(u["group_source"] == "entra" for u in upserts)
    names_by_id = {u["group_id"]: u["group_name"] for u in upserts}
    assert names_by_id["g-sales"] == "Sales EMEA"
