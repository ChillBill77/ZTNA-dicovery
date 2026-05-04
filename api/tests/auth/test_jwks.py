from __future__ import annotations

import httpx
import pytest
import respx
from api.auth.jwks import JwksCache
from freezegun import freeze_time

DISCOVERY_URL = "https://login.microsoftonline.com/tid/v2.0/.well-known/openid-configuration"
JWKS_URL = "https://login.microsoftonline.com/tid/discovery/v2.0/keys"


@pytest.fixture
def discovery_mock(respx_mock: respx.Router) -> respx.Router:
    # Named routes — newer respx no longer supports indexing the router by raw
    # URL string; tests look up call_count via respx_mock["<name>"].
    respx_mock.get(DISCOVERY_URL, name="discovery").mock(
        return_value=httpx.Response(200, json={"jwks_uri": JWKS_URL})
    )
    respx_mock.get(JWKS_URL, name="jwks").mock(
        return_value=httpx.Response(
            200,
            json={"keys": [{"kid": "kid-1", "kty": "RSA", "n": "x", "e": "AQAB"}]},
        )
    )
    return respx_mock


@pytest.mark.asyncio
async def test_first_lookup_fetches_keys(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    key = await cache.get_key("kid-1")
    assert key["kid"] == "kid-1"
    assert discovery_mock["jwks"].call_count == 1


@pytest.mark.asyncio
async def test_cache_hits_within_ttl(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    await cache.get_key("kid-1")
    await cache.get_key("kid-1")
    assert discovery_mock["jwks"].call_count == 1  # still cached


@pytest.mark.asyncio
async def test_cache_refreshes_after_ttl(discovery_mock: respx.Router) -> None:
    with freeze_time("2026-04-22 10:00:00") as frozen:
        cache = JwksCache(DISCOVERY_URL, ttl_seconds=3600)
        await cache.get_key("kid-1")
        frozen.tick(delta=3601)
        await cache.get_key("kid-1")
    assert discovery_mock["jwks"].call_count == 2


@pytest.mark.asyncio
async def test_cache_refreshes_on_kid_miss(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    await cache.get_key("kid-1")
    # Simulate rotated kid-2 in upstream JWKS.
    discovery_mock.get(JWKS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "keys": [
                    {"kid": "kid-1", "kty": "RSA", "n": "x", "e": "AQAB"},
                    {"kid": "kid-2", "kty": "RSA", "n": "y", "e": "AQAB"},
                ]
            },
        )
    )
    key = await cache.get_key("kid-2")
    assert key["kid"] == "kid-2"
    assert discovery_mock["jwks"].call_count == 2


@pytest.mark.asyncio
async def test_unknown_kid_raises(discovery_mock: respx.Router) -> None:
    cache = JwksCache(DISCOVERY_URL)
    with pytest.raises(KeyError):
        await cache.get_key("not-there")
