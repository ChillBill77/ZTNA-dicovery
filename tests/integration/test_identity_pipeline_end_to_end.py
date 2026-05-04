"""End-to-end identity pipeline integration test.

Drives a Winlogbeat-formatted AD 4624 syslog event into id-ingest's
ad_4624 adapter (UDP :5516) and asserts the parsed IdentityEvent lands
in the Redis ``identity.events`` stream.

This is the identity-side counterpart to ``test_pipeline_end_to_end.py``
(flow side). Together they cover the two ingest paths feeding the
correlator's Enricher.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from datetime import datetime, timezone

import pytest
import redis.asyncio as redis_async

pytestmark = pytest.mark.integration

IDENTITY_STREAM = "identity.events"
AD_SYSLOG_HOST = "localhost"
AD_SYSLOG_PORT = 5516
REDIS_URL = "redis://localhost:6379/0"


def _build_winlogbeat_4624(
    *, src_ip: str, user: str, domain: str, logon_type: str = "10"
) -> bytes:
    """Mint a single Winlogbeat-style syslog frame the ad_4624 adapter parses.

    The adapter strips a leading ``proc[pid]: `` prefix before JSON-decoding,
    so the wire format is ``winlogbeat[1]: {json}``.
    """

    payload = {
        "@timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_id": 4624,
        "winlog": {
            "event_data": {
                "TargetUserName": user,
                "TargetDomainName": domain,
                "LogonType": logon_type,
                "IpAddress": src_ip,
                "LogonGuid": "{00000000-0000-0000-0000-000000000001}",
            }
        },
    }
    line = f"winlogbeat[1]: {json.dumps(payload)}\n"
    return line.encode("utf-8")


@pytest.mark.asyncio
async def test_ad_4624_syslog_lands_in_identity_stream(
    compose_stack: dict[str, str],
) -> None:
    client = redis_async.from_url(REDIS_URL, decode_responses=True)
    try:
        # Snapshot existing stream length so the assertion is robust to any
        # baseline events emitted during compose bring-up.
        baseline = await client.xlen(IDENTITY_STREAM) if await client.exists(
            IDENTITY_STREAM
        ) else 0

        frame = _build_winlogbeat_4624(
            src_ip="10.99.0.42",
            user="alice",
            domain="example.com",
            logon_type="10",
        )

        # Send a few duplicates to absorb single-packet UDP loss; the adapter
        # is happy to ingest repeats and the assertion only checks that the
        # stream grew by ≥ 1.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _ in range(5):
                sock.sendto(frame, (AD_SYSLOG_HOST, AD_SYSLOG_PORT))
                time.sleep(0.05)
        finally:
            sock.close()

        deadline = time.monotonic() + 15
        latest = baseline
        while time.monotonic() < deadline:
            latest = await client.xlen(IDENTITY_STREAM) if await client.exists(
                IDENTITY_STREAM
            ) else 0
            if latest > baseline:
                break
            await asyncio.sleep(0.5)
        assert latest > baseline, (
            f"identity.events did not grow after AD 4624 syslog "
            f"(baseline={baseline}, latest={latest})"
        )

        # Spot-check the newest entries carry our user_upn so we know the
        # adapter parsed them (not just an unrelated heartbeat). The
        # producer XADDs a single ``event`` field with a JSON-encoded
        # IdentityEvent payload (see common/redis_bus.py).
        entries = await client.xrevrange(IDENTITY_STREAM, count=10)
        upns: set[str] = set()
        for _entry_id, fields in entries:
            payload = fields.get("event")
            if payload is None:
                continue
            doc = json.loads(payload)
            upn = doc.get("user_upn")
            if upn is not None:
                upns.add(upn)
        assert "alice@example.com" in upns, (
            f"expected user_upn alice@example.com in latest entries, got {upns}"
        )
    finally:
        await client.aclose()
