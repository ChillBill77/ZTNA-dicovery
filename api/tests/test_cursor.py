from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api.cursor import CursorPayload, decode_cursor, encode_cursor


def test_encode_decode_roundtrip() -> None:
    payload = CursorPayload(
        last_time=datetime(2026, 4, 22, 14, 12, 5, tzinfo=UTC),
        last_src_ip="10.0.0.1",
        last_dst_ip="1.1.1.1",
        last_dst_port=443,
    )
    token = encode_cursor(payload)
    got = decode_cursor(token)
    assert got == payload


def test_decode_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


def test_decode_rejects_wrong_schema() -> None:
    import base64
    import json

    bad = base64.urlsafe_b64encode(json.dumps({"foo": 1}).encode()).decode()
    with pytest.raises(ValueError):
        decode_cursor(bad)
