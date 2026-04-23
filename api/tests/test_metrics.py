from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_endpoint_exposes_prometheus_format(client: TestClient) -> None:
    # Prime a couple of requests so the counter has observations.
    client.get("/health/live")
    client.get("/health/live")
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert 'api_http_requests_total{route="/health/live",status="200"}' in body


def test_ws_gauge_metric_present(client: TestClient) -> None:
    r = client.get("/metrics")
    assert "api_ws_connections" in r.text
