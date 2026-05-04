from __future__ import annotations

from typing import Any, Protocol

from jose import ExpiredSignatureError, JWTError, jwt


class InvalidToken(Exception):
    """Raised when a JWT fails any verification check (signature/aud/iss/exp)."""


class _JwksSource(Protocol):
    async def get_key(self, kid: str) -> dict[str, Any]: ...


async def verify_jwt(
    token: str,
    jwks: _JwksSource,
    *,
    audience: str,
    issuer: str,
) -> dict[str, Any]:
    """Verify an RS256 JWT against a JWKS source + audience + issuer.

    Raises :class:`InvalidToken` on any failure; returns the decoded claims
    dict on success. Tokens without a ``kid`` header are rejected.
    """

    try:
        unverified = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
    kid = unverified.get("kid")
    if not kid:
        raise InvalidToken("no kid in token header")
    try:
        key = await jwks.get_key(kid)
    except KeyError as exc:
        raise InvalidToken(f"unknown kid: {kid}") from exc
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
        return decoded
    except ExpiredSignatureError as exc:
        raise InvalidToken("expired") from exc
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
