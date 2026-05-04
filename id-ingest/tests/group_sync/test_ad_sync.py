"""AD group-sync tests.

Rather than fighting ldap3's MOCK_SYNC strategy (limited filter handling and
no real range-retrieval semantics), these tests inject a tiny FakeLdapConn that
implements the narrow surface AdGroupSync consumes: ``search(...)``,
``entries[0]``, ``entry.distinguishedName``, ``entry.entry_attributes``, and
``getattr(entry, attr).values``.

Range-retrieval (``memberOf;range=lo-hi`` chunked walker) is covered by
``test_range_retrieval_walks_chunks`` via a paginated fake connection; a real
AD mock or chunked fixture loader is no longer required for that path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

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
        if "userPrincipalName=" in search_filter or "sAMAccountName=" in search_filter:
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
        entries: ClassVar[list[Any]] = []

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


@pytest.mark.asyncio
async def test_range_retrieval_walks_chunks() -> None:
    """_read_memberof must follow `memberOf;range=lo-hi` continuations."""

    page1_groups = [f"CN=g{i},OU=Groups,DC=example" for i in range(1500)]
    page2_groups = [f"CN=g{i},OU=Groups,DC=example" for i in range(1500, 1547)]

    class _PaginatedConn:
        """FakeLdapConn variant — first search returns memberOf;range=0-1499
        with 1500 values; second search (for memberOf;range=1500-*) returns
        memberOf;range=1500-* with the remainder.

        Real ldap3 ``Entry`` objects expose a ranged attribute under both the
        ranged name (e.g. ``memberOf;range=0-1499``) AND the bare base name
        (``memberOf``). We replicate that here so ``getattr(entry, "memberOf")``
        in production succeeds on the first iteration just like it does in the
        wild — while ``entry.entry_attributes`` still surfaces the ranged key
        so the walker can detect a continuation.
        """

        def __init__(self, user_dn: str) -> None:
            self._user_dn = user_dn
            self._calls = 0
            self.entries: list[Any] = []

        def search(
            self,
            search_base: str,
            search_filter: str,
            search_scope: Any = None,
            attributes: list[str] | None = None,
        ) -> None:
            if "userPrincipalName=" in search_filter or "sAMAccountName=" in search_filter:
                self.entries = [_Entry(dn=self._user_dn, attrs={})]
                return
            # memberOf retrieval — first call returns the bounded range,
            # second returns the unbounded continuation.
            self._calls += 1
            if self._calls == 1:
                attrs = {
                    "memberOf": page1_groups,
                    "memberOf;range=0-1499": page1_groups,
                }
            elif self._calls == 2:
                attrs = {"memberOf;range=1500-*": page2_groups}
            else:
                self.entries = []
                return
            self.entries = [_Entry(dn=self._user_dn, attrs=attrs)]

    sync = AdGroupSync(
        ldap_url="ldap://mock",
        bind_dn="cn=svc",
        bind_password="x",
        base_dn="dc=example",
        connection_factory=lambda: _PaginatedConn(user_dn="CN=carol,OU=Users,DC=example"),
    )
    upserts = await sync.sync_user("carol@example")
    assert len(upserts) == 1547
    assert {u["group_source"] for u in upserts} == {"ad"}
    # spot-check first and last
    assert upserts[0]["group_id"].startswith("CN=g0,")
    assert upserts[-1]["group_id"].startswith("CN=g1546,")
