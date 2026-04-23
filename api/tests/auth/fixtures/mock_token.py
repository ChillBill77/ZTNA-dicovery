"""Generate real RS256 keypairs + signed JWTs for auth tests.

Uses ``python-jose`` (installed via ``api[test]``) to produce JWK dicts
directly from PEM-encoded keys. Returns ``(priv_jwk, pub_jwk)`` with a shared
``kid`` so the fake JWKS source can resolve the signing key by ``kid``.
"""

from __future__ import annotations

import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt


def new_keypair(kid: str = "kid-1") -> tuple[dict[str, Any], dict[str, Any]]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_key = jwk.construct(priv_pem.decode(), "RS256")
    priv_jwk = priv_key.to_dict()
    priv_jwk["kid"] = kid

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_key = jwk.construct(pub_pem.decode(), "RS256")
    pub_jwk = pub_key.to_dict()
    pub_jwk["kid"] = kid
    return priv_jwk, pub_jwk


def sign(claims: dict[str, Any], priv_jwk: dict[str, Any]) -> str:
    token: str = jwt.encode(
        claims,
        priv_jwk,
        algorithm="RS256",
        headers={"kid": priv_jwk["kid"]},
    )
    return token


def standard_claims(
    sub: str = "user-1",
    upn: str = "alice@example.com",
    groups: list[str] | None = None,
    aud: str = "client-id",
    iss: str = "https://login.microsoftonline.com/tid/v2.0",
    ttl: int = 3600,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "sub": sub,
        "upn": upn,
        "groups": groups or [],
        "aud": aud,
        "iss": iss,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
    }
