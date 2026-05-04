from __future__ import annotations

import json
from ipaddress import ip_network
from pathlib import Path

import httpx
import pytest
from id_ingest.adapters.entra_signin_adapter import EntraSigninAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "entra"


def _mock_transport() -> httpx.MockTransport:
    pages = [
        json.loads((FIX / "signins_page1.json").read_text()),
        json.loads((FIX / "signins_page2.json").read_text()),
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(
                200,
                json={"access_token": "abc", "expires_in": 3600, "token_type": "Bearer"},
            )
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_adapter_emits_events_for_success_only() -> None:
    adapter = EntraSigninAdapter(
        tenant_id="tid",
        client_id="cid",
        client_secret="sec",
        corp_cidrs=[ip_network("10.0.0.0/8")],
        transport=_mock_transport(),
        poll_interval_s=0,
    )
    events = [ev async for ev in adapter.poll_once()]
    upns = {ev["user_upn"] for ev in events}
    # svc@corp.example had errorCode != 0 → must be dropped
    assert "alice@corp.example" in upns
    assert "svc@corp.example" not in upns


@pytest.mark.asyncio
async def test_confidence_by_corp_cidr_membership() -> None:
    adapter = EntraSigninAdapter(
        tenant_id="tid",
        client_id="cid",
        client_secret="sec",
        corp_cidrs=[ip_network("10.0.0.0/8")],
        transport=_mock_transport(),
        poll_interval_s=0,
    )
    events = [ev async for ev in adapter.poll_once()]
    by_upn = {ev["user_upn"]: ev for ev in events}
    assert by_upn["alice@corp.example"]["confidence"] == 80
    assert by_upn["carol@corp.example"]["confidence"] == 80  # 10.0.99.2 in /8
    # bob@corp.example at 198.51.100.5 is outside the corp CIDR
    assert by_upn["bob@corp.example"]["confidence"] == 40


@pytest.mark.asyncio
async def test_delta_link_captured_after_full_page_walk() -> None:
    adapter = EntraSigninAdapter(
        tenant_id="tid",
        client_id="cid",
        client_secret="sec",
        corp_cidrs=[ip_network("10.0.0.0/8")],
        transport=_mock_transport(),
        poll_interval_s=0,
    )
    _ = [ev async for ev in adapter.poll_once()]
    assert adapter.healthcheck()["delta_link_seen"] is True
