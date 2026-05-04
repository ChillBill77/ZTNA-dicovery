from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF check for cookie-authenticated requests.

    Cookie-auth'd mutations must send an ``X-CSRF-Token`` header that equals
    the ``csrf_token`` cookie. Bearer-token flows (``Authorization`` header)
    are exempt: a cross-origin form submission cannot attach a custom
    Authorization header, so the classic CSRF vector does not apply.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if request.cookies.get("session") is None:
            return await call_next(request)
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("x-csrf-token")
        if not cookie_token or cookie_token != header_token:
            return JSONResponse(status_code=403, content={"detail": "CSRF token mismatch"})
        return await call_next(request)
