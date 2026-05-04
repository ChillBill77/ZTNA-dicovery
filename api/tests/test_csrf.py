from __future__ import annotations

from api.middleware_csrf import CsrfMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build() -> TestClient:
    app = FastAPI()
    app.add_middleware(CsrfMiddleware)

    @app.get("/safe")
    async def safe() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/mutate")
    async def mutate() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_get_always_allowed() -> None:
    assert _build().get("/safe").status_code == 200


def test_post_without_cookie_allowed_bearer_flow() -> None:
    # No session cookie → treated as bearer flow; middleware is a no-op.
    r = _build().post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200


def test_post_with_cookie_requires_matching_header() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    # No CSRF header / no matching cookie → 403.
    r = c.post("/mutate")
    assert r.status_code == 403


def test_post_with_cookie_and_matching_header_allowed() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    c.cookies.set("csrf_token", "t123")
    r = c.post("/mutate", headers={"X-CSRF-Token": "t123"})
    assert r.status_code == 200


def test_post_with_mismatched_token_denied() -> None:
    c = _build()
    c.cookies.set("session", "abc")
    c.cookies.set("csrf_token", "t123")
    r = c.post("/mutate", headers={"X-CSRF-Token": "DIFFERENT"})
    assert r.status_code == 403
