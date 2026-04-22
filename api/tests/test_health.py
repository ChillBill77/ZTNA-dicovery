from fastapi.testclient import TestClient


def test_live_is_always_ok(client: TestClient) -> None:
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_component_status(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["components"] == {"db": False, "redis": False}
