from __future__ import annotations

import pytest

from api.auth.session import SessionCodec, SessionData


def test_encode_decode_roundtrip() -> None:
    codec = SessionCodec(secret="x" * 32)
    data = SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=9999999999)
    token = codec.encode(data)
    out = codec.decode(token)
    assert out == data


def test_tampered_token_rejected() -> None:
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(
        SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=9999999999)
    )
    with pytest.raises(ValueError):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))


def test_expired_token_rejected() -> None:
    codec = SessionCodec(secret="x" * 32)
    token = codec.encode(
        SessionData(user_upn="u@x", roles={"viewer"}, csrf="t1", exp=1)
    )
    with pytest.raises(ValueError):
        codec.decode(token)


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError):
        SessionCodec(secret="short")


def test_roles_roundtrip_preserves_set_semantics() -> None:
    codec = SessionCodec(secret="y" * 32)
    data = SessionData(
        user_upn="u@x",
        roles={"admin", "editor", "viewer"},
        csrf="csrf-xyz",
        exp=9999999999,
    )
    out = codec.decode(codec.encode(data))
    # encoded as sorted list internally; decode must restore as set.
    assert out.roles == {"admin", "editor", "viewer"}
    assert isinstance(out.roles, set)
