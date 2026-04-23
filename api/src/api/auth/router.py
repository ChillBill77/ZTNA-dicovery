from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from api.auth.jwks import JwksCache
from api.auth.jwt_verify import InvalidToken, verify_jwt
from api.auth.roles import RoleMap, roles_from_groups
from api.auth.session import SessionCodec, SessionData
from api.settings import Settings

router = APIRouter()


def _settings() -> Settings:
    return Settings()


def _role_map(settings: Settings) -> RoleMap:
    def _split(val: str) -> set[str]:
        return {x for x in (val or "").split(",") if x}

    return RoleMap(
        viewer=_split(settings.oidc_group_ids_viewer),
        editor=_split(settings.oidc_group_ids_editor),
        admin=_split(settings.oidc_group_ids_admin),
    )


def _codec(settings: Settings) -> SessionCodec:
    return SessionCodec(secret=settings.session_secret)


def _jwks(settings: Settings) -> JwksCache:
    return JwksCache(
        settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    )


@router.get("/api/auth/login")
async def login(settings: Settings = Depends(_settings)) -> RedirectResponse:
    state = secrets.token_urlsafe(16)
    auth_url = (
        f"{settings.oidc_issuer.rstrip('/')}/authorize"
        f"?response_type=code&client_id={settings.oidc_client_id}"
        f"&redirect_uri={settings.oidc_redirect_uri}"
        f"&scope=openid+profile+email"
        f"&state={state}"
    )
    r = RedirectResponse(auth_url, status_code=302)
    r.set_cookie(
        "oidc_state",
        state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return r


@router.get("/api/auth/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    settings: Settings = Depends(_settings),
) -> RedirectResponse:
    if request.cookies.get("oidc_state") != state:
        raise HTTPException(status_code=400, detail="state mismatch")
    from api.auth.oidc import exchange_code

    claims = await exchange_code(code)

    roles = roles_from_groups(claims.get("groups", []), _role_map(settings))
    csrf = secrets.token_urlsafe(16)
    data = SessionData(
        user_upn=claims["upn"],
        roles=roles,
        csrf=csrf,
        exp=int(time.time()) + settings.access_token_ttl_s,
    )
    token = _codec(settings).encode(data)
    r = RedirectResponse("/", status_code=302)
    r.set_cookie(
        "session",
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=28800,
    )
    r.set_cookie(
        "csrf_token",
        csrf,
        secure=True,
        samesite="strict",
        max_age=28800,
    )
    r.delete_cookie("oidc_state")
    return r


@router.post("/api/auth/logout", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie("session")
    response.delete_cookie("csrf_token")
    response.status_code = 204
    return response


async def current_user(request: Request) -> dict[str, Any]:
    # 1. Bearer JWT path — for machine/API clients.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        settings = _settings()
        try:
            claims = await verify_jwt(
                auth_header.split(None, 1)[1],
                _jwks(settings),
                audience=settings.oidc_client_id,
                issuer=settings.oidc_issuer,
            )
        except InvalidToken as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "user_upn": claims.get("upn", claims.get("sub", "unknown")),
            "roles": roles_from_groups(
                claims.get("groups", []), _role_map(settings)
            ),
        }

    # 2. Cookie session path — for browser clients.
    cookie = request.cookies.get("session")
    if cookie:
        try:
            data = _codec(_settings()).decode(cookie)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"user_upn": data.user_upn, "roles": data.roles}

    raise HTTPException(status_code=401, detail="unauthenticated")


@router.get("/api/auth/me")
async def me(
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return {"user_upn": user["user_upn"], "roles": sorted(user["roles"])}


@router.get("/auth/verify")
async def verify(user: dict[str, Any] = Depends(current_user)) -> Response:
    r = JSONResponse(content={})
    r.headers["X-User"] = user["user_upn"]
    r.headers["X-Roles"] = ",".join(sorted(user["roles"]))
    return r
