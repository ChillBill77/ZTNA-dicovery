from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import ClassVar

import httpx
from loguru import logger
from ztna_common.adapter_base import IdentityAdapter
from ztna_common.event_types import IdentityEvent

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_BASE = "https://login.microsoftonline.com"
CONF_IN = 80
CONF_OUT = 40
TTL_S = 3600


class EntraSigninAdapter(IdentityAdapter):
    name: ClassVar[str] = "entra_signin"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        corp_cidrs: list[IPv4Network | IPv6Network],
        *,
        transport: httpx.BaseTransport | None = None,
        poll_interval_s: int = 60,
    ) -> None:
        self._tid = tenant_id
        self._cid = client_id
        self._sec = client_secret
        self._cidrs = corp_cidrs
        self._poll = poll_interval_s
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)
        self._delta_link: str | None = None

    @classmethod
    def from_config(cls, cfg: dict[str, object]) -> EntraSigninAdapter:
        raw_cidrs = cfg.get("corp_cidrs", []) or []
        cidrs = [ip_network(c) for c in raw_cidrs]  # type: ignore[union-attr]
        return cls(
            tenant_id=str(cfg["tenant_id"]),
            client_id=str(cfg["client_id"]),
            client_secret=str(cfg["client_secret"]),
            corp_cidrs=cidrs,
            poll_interval_s=int(cfg.get("poll_interval_s", 60)),  # type: ignore[arg-type]
        )

    async def _token(self) -> str:
        resp = await self._client.post(
            f"{AUTH_BASE}/{self._tid}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._cid,
                "client_secret": self._sec,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        token: str = resp.json()["access_token"]
        return token

    def _confidence(self, ip: str) -> int:
        try:
            addr = ip_address(ip)
        except ValueError:
            return CONF_OUT
        return CONF_IN if any(addr in c for c in self._cidrs) else CONF_OUT

    async def poll_once(self) -> AsyncIterator[IdentityEvent]:
        token = await self._token()
        url: str | None = (
            self._delta_link or f"{GRAPH_BASE}/auditLogs/signIns?$filter=status/errorCode eq 0"
        )
        while url:
            r = await self._client.get(url, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            body = r.json()
            for item in body.get("value", []):
                if item.get("status", {}).get("errorCode") != 0:
                    continue
                ip = item.get("ipAddress")
                upn = item.get("userPrincipalName")
                if not ip or not upn:
                    continue
                ts = datetime.fromisoformat(item["createdDateTime"].replace("Z", "+00:00"))
                yield IdentityEvent(
                    ts=ts,
                    src_ip=ip,
                    user_upn=upn,
                    source=self.name,
                    event_type="logon",
                    confidence=self._confidence(ip),
                    ttl_seconds=TTL_S,
                    mac=None,
                    raw_id=item.get("id"),
                )
            url = body.get("@odata.nextLink")
            if not url and body.get("@odata.deltaLink"):
                self._delta_link = body["@odata.deltaLink"]

    async def run(self) -> AsyncIterator[IdentityEvent]:
        while True:
            try:
                async for ev in self.poll_once():
                    yield ev
            except Exception as exc:
                logger.warning("entra_signin poll error: {}", exc)
            await asyncio.sleep(self._poll)

    def healthcheck(self) -> dict[str, object]:
        return {"adapter": self.name, "delta_link_seen": bool(self._delta_link)}
