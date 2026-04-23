from __future__ import annotations

import pytest

from id_ingest.main import discover_adapters, run_once


def test_discover_adapters_returns_subclass_list() -> None:
    """Auto-discovery always returns a list of IdentityAdapter subclasses."""

    from ztna_common.adapter_base import IdentityAdapter

    found = discover_adapters()
    for cls in found:
        assert issubclass(cls, IdentityAdapter)
        assert cls is not IdentityAdapter


def test_discover_adapters_finds_all_day1_adapters() -> None:
    """All four day-1 identity adapters must auto-register via module scan."""

    names = {cls.name for cls in discover_adapters()}
    assert names == {"ad_4624", "entra_signin", "cisco_ise", "aruba_clearpass"}


@pytest.mark.asyncio
async def test_run_once_returns_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Idle shutdown path returns True after the timeout elapses."""

    # Avoid real Redis connection by pointing redis_url at a non-existent host
    # and mocking aclose; RedisStreamProducer.from_url is lazy so no network
    # traffic is attempted before aclose().
    monkeypatch.setenv("REDIS_URL", "redis://localhost:1/0")
    result = await run_once(timeout_s=0.01)
    assert result is True
