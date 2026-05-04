from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from ldap3 import ALL, SUBTREE, Connection, Server


class GroupUpsert(TypedDict):
    user_upn: str
    group_id: str
    group_name: str
    group_source: str


_RANGE = re.compile(r"memberOf;range=(?P<lo>\d+)-(?P<hi>\d+|\*)")


def _cn(dn: str) -> str:
    first = dn.split(",", 1)[0]
    return first.split("=", 1)[1] if "=" in first else first


@dataclass
class AdGroupSync:
    ldap_url: str
    bind_dn: str
    bind_password: str
    base_dn: str
    connection_factory: Callable[[], Connection] | None = None

    def _connect(self) -> Connection:
        if self.connection_factory is not None:
            return self.connection_factory()
        srv = Server(self.ldap_url, get_info=ALL)
        return Connection(srv, user=self.bind_dn, password=self.bind_password, auto_bind=True)

    def _read_memberof(self, conn: Connection, user_dn: str) -> list[str]:
        groups: list[str] = []
        attr = "memberOf"
        # AD returns groups in 1500-value chunks via `memberOf;range=X-Y`; walk
        # ranges until the terminating `*` attribute name is seen.
        while True:
            conn.search(user_dn, "(objectClass=user)", SUBTREE, attributes=[attr])
            entries: Any = conn.entries
            if not entries:
                break
            entry = entries[0]
            values = getattr(entry, attr).values if hasattr(entry, attr) else []
            groups.extend(values)
            ranged_attrs = [k for k in entry.entry_attributes if _RANGE.match(k)]
            if not ranged_attrs:
                break
            m = _RANGE.match(ranged_attrs[0])
            if m is None or m.group("hi") == "*":
                break
            next_lo = int(m.group("hi")) + 1
            attr = f"memberOf;range={next_lo}-*"
        return groups

    async def sync_user(self, user_upn: str) -> list[GroupUpsert]:
        def _work() -> list[GroupUpsert]:
            conn = self._connect()
            local = user_upn.split("@", 1)[0]
            conn.search(
                self.base_dn,
                f"(userPrincipalName={user_upn})",
                SUBTREE,
                attributes=["distinguishedName"],
            )
            entries: Any = conn.entries
            if not entries:
                conn.search(
                    self.base_dn,
                    f"(sAMAccountName={local})",
                    SUBTREE,
                    attributes=["distinguishedName"],
                )
                entries = conn.entries
            if not entries:
                return []
            user_dn = str(entries[0].distinguishedName)
            dns = self._read_memberof(conn, user_dn)
            return [
                GroupUpsert(
                    user_upn=user_upn,
                    group_id=dn,
                    group_name=_cn(dn),
                    group_source="ad",
                )
                for dn in dns
            ]

        return await asyncio.to_thread(_work)

    async def sync_all(self) -> AsyncIterator[GroupUpsert]:
        def _enumerate() -> list[str]:
            conn = self._connect()
            conn.search(
                self.base_dn,
                "(objectClass=user)",
                SUBTREE,
                attributes=["userPrincipalName"],
            )
            entries: Any = conn.entries
            upns: list[str] = []
            for e in entries:
                upn = getattr(e, "userPrincipalName", None)
                if upn is not None and str(upn):
                    upns.append(str(upn))
            return upns

        users = await asyncio.to_thread(_enumerate)
        for upn in users:
            for up in await self.sync_user(upn):
                yield up
