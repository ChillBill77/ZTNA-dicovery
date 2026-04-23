from __future__ import annotations

from collections.abc import Awaitable, Callable

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "api_http_requests_total",
    "API HTTP request count",
    ["route", "status"],
    registry=REGISTRY,
)
WS_CONNECTIONS = Gauge(
    "api_ws_connections",
    "Active WebSocket connections",
    registry=REGISTRY,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(route=path, status=str(response.status_code)).inc()
        return response


async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(
        generate_latest(REGISTRY).decode("utf-8"),
        media_type="text/plain; version=0.0.4",
    )
