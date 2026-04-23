"""AD group-sync tests.

Rather than fighting ldap3's MOCK_SYNC strategy (limited filter handling and
no real range-retrieval semantics), these tests inject a tiny FakeLdapConn that
implements the narrow surface AdGroupSync consumes: ``search(...)``,
``entries[0]``, ``entry.distinguishedName``, ``entry.entry_attributes``, and
``getattr(entry, attr).values``.

TODO(P3-followup): add a range-retrieval integration test once a real AD mock
or chunked fixture loader is wired up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from id_ingest.group_sync.ad_sync import AdGroupSync


@dataclass
class _Attr:
    values: list[str]


class _Entry:
    """Minimal substitute for ``ldap3.Entry``."""

    def __init__(self, *, dn: str, attrs: dict[str, list[str]]) -> None:
        self.distinguishedName = dn
        self._attr_names = list(attrs.keys())
        for name, values in attrs.items():
            setattr(self, name, _Attr(values))

    @property
    def entry_attributes(self) -> list[str]:
        return list(self._attr_names)


class _FakeConn:
    """Implements just enough of ldap3.Connection for AdGroupSync tests."""

    def __init__(self, *, user_dn: str, memberof_values: list[str]) -> None:
        self._user_dn = user_dn
        self._memberof_values = memberof_values
        self.entries: list[Any] = []

    def search(
        self,
        search_base: str,
        search_filter: str,
        search_scope: Any = None,
        attributes: list[str] | None = None,
    ) -> None:
        if (
            "userPrincipalName=" in search_filter
            or "sAMAccountName=" in search_filter
        ):
            self.entries = [_Entry(dn=self._user_dn, attrs={})]
            return
        # Non-ranged retrieval: return all memberOf values, no ranged attr name.
        self.entries = [
            _Entry(
                dn=self._user_dn,
                attrs={"memberOf": self._memberof_values},
            )
        ]


@pytest.mark.asyncio
async def test_small_group_flatten() -> None:
    group_dns = [
        "CN=Sales EMEA,OU=Groups,DC=example",
        "CN=Engineering,OU=Groups,DC=example",
        "CN=All Staff,OU=Groups,DC=example",
    ]

    def _factory() -> Any:
        return _FakeConn(
            user_dn="CN=alice,OU=Users,DC=example",
            memberof_values=group_dns,
        )

    sync = AdGroupSync(
        ldap_url="ldap://mock",
        bind_dn="cn=svc",
        bind_password="x",
        base_dn="dc=example",
        connection_factory=_factory,
    )
    upserts = await sync.sync_user("alice@example")
    assert len(upserts) == 3
    assert {u["group_source"] for u in upserts} == {"ad"}
    assert upserts[0]["group_name"] == "Sales EMEA"
    assert upserts[0]["group_id"] == group_dns[0]
    assert upserts[0]["user_upn"] == "alice@example"


@pytest.mark.asyncio
async def test_unknown_upn_returns_empty() -> None:
    class _EmptyConn:
        entries: list[Any] = []

        def search(self, *args: Any, **kwargs: Any) -> None:
            self.entries = []

    sync = AdGroupSync(
        ldap_url="ldap://mock",
        bind_dn="cn=svc",
        bind_password="x",
        base_dn="dc=example",
        connection_factory=lambda: _EmptyConn(),  # type: ignore[return-value,arg-type]
    )
    upserts = await sync.sync_user("unknown@example")
    assert upserts == []


@pytest.mark.asyncio
async def test_group_name_falls_back_to_raw_when_no_equals_sign() -> None:
    def _factory() -> Any:
        return _FakeConn(
            user_dn="CN=bob,OU=Users,DC=example",
            memberof_values=["oddvalue-without-equals"],
        )

    sync = AdGroupSync(
        ldap_url="ldap://mock",
        bind_dn="cn=svc",
        bind_password="x",
        base_dn="dc=example",
        connection_factory=_factory,
    )
    upserts = await sync.sync_user("bob@example")
    assert len(upserts) == 1
    assert upserts[0]["group_name"] == "oddvalue-without-equals"
