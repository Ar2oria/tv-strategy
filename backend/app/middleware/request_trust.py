"""Sanitized Host trust and browser mutation-origin enforcement."""

from collections.abc import Sequence

from app.api.errors import public_error_response
from app.middleware.targets import normalize_host, normalize_origin
from starlette.datastructures import Headers, parse_host_header
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


async def _forbidden(scope: Scope, receive: Receive, send: Send) -> None:
    response = public_error_response(
        scope["path"],
        code="request_origin_forbidden",
        message="Request origin is not allowed",
        status_code=403,
    )
    await response(scope, receive, send)


def _fetch_site_is_allowed(headers: Headers) -> bool:
    values = headers.getlist("sec-fetch-site")
    if not values:
        return True
    return len(values) == 1 and values[0].strip().lower() in ALLOWED_FETCH_SITES


def _request_origin(scope: Scope, headers: Headers) -> str:
    hosts = headers.getlist("host")
    if len(hosts) != 1:
        raise ValueError("Request must have one Host header")
    scheme = scope.get("scheme", "http")
    return normalize_origin(f"{scheme}://{hosts[0]}")


def _origin_is_allowed(
    scope: Scope,
    headers: Headers,
    allowed_origins: frozenset[str],
) -> bool:
    origins = headers.getlist("origin")
    if not origins:
        return True
    if len(origins) != 1:
        return False
    try:
        origin = normalize_origin(origins[0])
        request_origin = _request_origin(scope, headers)
    except (TypeError, ValueError, UnicodeError):
        return False
    return origin == request_origin or origin in allowed_origins


class BrowserRequestTrustMiddleware:
    """Reject cross-site and ambiguous browser mutations before routing."""

    def __init__(self, app: ASGIApp, *, allowed_origins: Sequence[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(
            normalize_origin(origin) for origin in allowed_origins
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not _fetch_site_is_allowed(headers) or not _origin_is_allowed(
            scope, headers, self.allowed_origins
        ):
            await _forbidden(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SanitizedTrustedHostMiddleware(TrustedHostMiddleware):
    """Use Starlette Host checks with route-aware sanitized rejection responses."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Sequence[str]) -> None:
        normalized = tuple(normalize_host(host) for host in allowed_hosts)
        self.normalized_hosts = frozenset(normalized)
        starlette_hosts = tuple(
            f"[{host}]" if ":" in host else host for host in normalized
        )
        super().__init__(app, allowed_hosts=starlette_hosts, www_redirect=False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return
        parsed_host = parse_host_header(Headers(scope=scope).get("host"))
        try:
            host = (
                None
                if parsed_host is None
                else normalize_host(parsed_host.host)
            )
        except ValueError:
            host = None
        if host not in self.normalized_hosts:
            response = public_error_response(
                scope["path"],
                code="invalid_host",
                message="Invalid host header",
                status_code=400,
            )
            await response(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
