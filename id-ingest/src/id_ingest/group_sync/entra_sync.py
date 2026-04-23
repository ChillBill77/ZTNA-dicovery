from __future__ import annotations

from dataclasses import dataclass

import httpx

from id_ingest.group_sync.ad_sync import GroupUpsert

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"


@dataclass
class EntraGroupSync:
    tenant_id: str
    client_id: str
    client_secret: str
    transport: httpx.BaseTransport | None = None

    async def _token(self, c: httpx.AsyncClient) -> str:
        r = await c.post(
            f"{LOGIN}/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        r.raise_for_status()
        token: str = r.json()["access_token"]
        return token

    async def sync_user(self, user_upn: str) -> list[GroupUpsert]:
        async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as c:
            tok = await self._token(c)
            url: str | None = f"{GRAPH}/users/{user_upn}/transitiveMemberOf"
            headers = {"Authorization": f"Bearer {tok}"}
            out: list[GroupUpsert] = []
            while url:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                body = r.json()
                for g in body.get("value", []):
                    if g.get("@odata.type") != "#microsoft.graph.group":
                        continue
                    out.append(
                        GroupUpsert(
                            user_upn=user_upn,
                            group_id=g["id"],
                            group_name=g.get("displayName") or g["id"],
                            group_source="entra",
                        )
                    )
                url = body.get("@odata.nextLink")
            return out

    async def sync_all(self) -> list[GroupUpsert]:
        """Enumerate all users, then call sync_user for each.

        One shared AsyncClient is reused for the whole enumeration; per-user
        ``sync_user`` opens its own short-lived client (the simplest shape
        compatible with both production Graph calls and ``httpx.MockTransport``
        in tests).
        """
        out: list[GroupUpsert] = []
        async with httpx.AsyncClient(transport=self.transport, timeout=60.0) as c:
            tok = await self._token(c)
            url: str | None = f"{GRAPH}/users?$select=userPrincipalName"
            headers = {"Authorization": f"Bearer {tok}"}
            while url:
                r = await c.get(url, headers=headers)
                r.raise_for_status()
                body = r.json()
                for u in body.get("value", []):
                    upn = u.get("userPrincipalName")
                    if upn:
                        out.extend(await self.sync_user(upn))
                url = body.get("@odata.nextLink")
        return out
