from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import build_app


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Force health probes to return False in unit tests (no real DB/Redis).
    monkeypatch.setattr("api.main.ping_db", _fake_false, raising=True)
    monkeypatch.setattr("api.main.ping_redis", _fake_false, raising=True)
    return TestClient(build_app())


async def _fake_false() -> bool:
    return False
