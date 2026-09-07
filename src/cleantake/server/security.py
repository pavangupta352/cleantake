"""Loopback, same-origin and scoped download authorization."""

from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from starlette.responses import JSONResponse

ARTIFACT_ROUTE = re.compile(r"^/api/projects/[^/]+/exports/[^/]+/.+$")
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class UploadTooLarge(Exception):
    pass


class Tickets:
    def __init__(self):
        self._tickets: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, path: str) -> dict:
        with self._lock:
            now = time.time()
            self._tickets = {key: item for key, item in self._tickets.items() if item[1] > now}
            if len(self._tickets) >= 1024:
                self._tickets.pop(next(iter(self._tickets)))
            token = secrets.token_urlsafe(32)
            expiry = now + 60
            self._tickets[token] = (path, expiry)
            return {
                "url": f"{path}?ticket={token}",
                "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
            }

    def valid(self, token: str, path: str) -> bool:
        with self._lock:
            item = self._tickets.get(token)
            return item is not None and item[1] > time.time() and hmac.compare_digest(item[0], path)


def _authority(value: str, scheme: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(f"{scheme}://{value}")
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        hostname = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        if hostname is None or not 1 <= port <= 65535:
            return None
        if hostname != "localhost" and not ipaddress.ip_address(hostname).is_loopback:
            return None
        return hostname, port
    except ValueError:
        return None


class SessionBoundary:
    """Pure ASGI middleware bounds streamed bodies before multipart spooling."""

    def __init__(self, app, *, state):
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))

        async def secured_send(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                names = {key.lower() for key, _ in existing}
                existing.extend(
                    (key.lower().encode(), value.encode())
                    for key, value in HEADERS.items()
                    if key.lower().encode() not in names
                )
                message["headers"] = existing
            await send(message)

        async def deny(status, code, message):
            await error_response(status, code, message)(scope, receive, secured_send)

        host_values = headers.get("host", [])
        host = _authority(host_values[0], scope["scheme"]) if len(host_values) == 1 else None
        if host is None:
            await deny(403, "forbidden_host", "Use the local CleanTake address.")
            return
        origins = headers.get("origin", [])
        if origins:
            try:
                parsed = urlsplit(origins[0])
            except ValueError:
                await deny(403, "forbidden_origin", "Open CleanTake from its local studio address.")
                return
            if (
                len(origins) != 1
                or parsed.scheme != scope["scheme"]
                or parsed.path
                or parsed.query
                or parsed.fragment
                or _authority(parsed.netloc, parsed.scheme) != host
            ):
                await deny(403, "forbidden_origin", "Open CleanTake from its local studio address.")
                return
        path = scope["path"]
        if path.startswith("/api") and path != "/api/health":
            supplied = headers.get("x-cleantake-token", [])
            authorized = len(supplied) == 1 and hmac.compare_digest(
                supplied[0].encode("latin-1"), self.state.token.encode("utf-8")
            )
            if not authorized and scope["method"] == "GET" and ARTIFACT_ROUTE.fullmatch(path):
                values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get(
                    "ticket", []
                )
                authorized = len(values) == 1 and self.state.tickets.valid(values[0], path)
            if not authorized:
                await deny(401, "invalid_session", "Open the studio with its current launch link.")
                return
        limit = self.state.limits.max_upload_bytes
        content_type = headers.get("content-type", [""])[0].split(";", 1)[0].strip().lower()
        upload_route = path == "/api/projects/import" or re.fullmatch(
            r"/api/projects/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/sources",
            path,
        )
        if not (
            scope["method"] == "POST" and upload_route and content_type == "multipart/form-data"
        ):
            limit = min(limit, self.state.limits.json_bytes)
        lengths = headers.get("content-length", [])
        try:
            if len(lengths) > 1 or (lengths and int(lengths[0]) < 0):
                raise ValueError
            if lengths and int(lengths[0]) > limit:
                await deny(
                    413, "upload_too_large", "The request exceeds the configured upload limit."
                )
                return
        except ValueError:
            await deny(422, "invalid_request", "Invalid request length.")
            return
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise UploadTooLarge
            return message

        try:
            await self.app(scope, bounded_receive, secured_send)
        except UploadTooLarge:
            await deny(413, "upload_too_large", "The request exceeds the configured upload limit.")
