from __future__ import annotations

from typing import Any

import pytest

from api.auth.jwt_verify import InvalidToken, verify_jwt
from api.tests.auth.fixtures.mock_token import new_keypair, sign, standard_claims


class _FakeJwks:
    def __init__(self, pub: dict[str, Any]) -> None:
        self._pub = pub

    async def get_key(self, kid: str) -> dict[str, Any]:
        if kid != self._pub["kid"]:
            raise KeyError(kid)
        return self._pub


ISS = "https://login.microsoftonline.com/tid/v2.0"


@pytest.mark.asyncio
async def test_valid_token_returns_claims() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(groups=["g1"]), priv)
    claims = await verify_jwt(
        token, _FakeJwks(pub), audience="client-id", issuer=ISS
    )
    assert claims["upn"] == "alice@example.com"
    assert claims["groups"] == ["g1"]


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(ttl=-1), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(
            token, _FakeJwks(pub), audience="client-id", issuer=ISS
        )


@pytest.mark.asyncio
async def test_wrong_audience_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(aud="other"), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(
            token, _FakeJwks(pub), audience="client-id", issuer=ISS
        )


@pytest.mark.asyncio
async def test_wrong_issuer_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(iss="https://evil/"), priv)
    with pytest.raises(InvalidToken):
        await verify_jwt(
            token, _FakeJwks(pub), audience="client-id", issuer=ISS
        )


@pytest.mark.asyncio
async def test_tampered_signature_rejected() -> None:
    priv, pub = new_keypair()
    token = sign(standard_claims(), priv)
    tampered = token[:-4] + "AAAA"
    with pytest.raises(InvalidToken):
        await verify_jwt(
            tampered, _FakeJwks(pub), audience="client-id", issuer=ISS
        )


@pytest.mark.asyncio
async def test_no_kid_header_rejected() -> None:
    # Handcraft a token without a kid by stripping it from the header.
    priv, pub = new_keypair()
    from jose import jwt as jose_jwt

    token = jose_jwt.encode(standard_claims(), priv, algorithm="RS256")
    with pytest.raises(InvalidToken):
        await verify_jwt(
            token, _FakeJwks(pub), audience="client-id", issuer=ISS
        )
