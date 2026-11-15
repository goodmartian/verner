"""Response compression and cache headers for the slow-changing GET answers.

`Compression` gzips what is larger than 1 KB, except pictures (already packed) and event streams.
`Caching` gives every GET answer of the API `Cache-Control: no-cache` and an `ETag` (a hash of the body, so it changes
with the data and with the code that shapes the answer), and answers 304 when the browser sends the ETag back. No
answer may be kept without asking: a new release must show at once. Answers that carry an ETag already are left alone.
"""

from __future__ import annotations

import hashlib

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MIN_SIZE = 1024
NO_CACHE = b"no-cache"  # the browser asks every time and gets a 304 without a body while the answer is the same


class Compression:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=MIN_SIZE)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path.endswith((".png", "/messages")) or _streamed(path):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


# a hotspot export is up to 1.6 GB: it streams through untouched (gzip of it would cost a core for a minute; the proxy
# in front may still pack it) and is never gathered to hash it
def _streamed(path: str) -> bool:
    return path == "/api/export" or path.startswith("/api/export/file/")


def cached(scope: Scope) -> bool:
    """Every GET answer of the API but the health check and the export file: its body hash is its version."""
    path = scope.get("path", "")
    return (scope["type"] == "http" and scope["method"] == "GET" and path.startswith("/api/")
            and path != "/api/health" and not _streamed(path))


class Caching:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not cached(scope):
            await self.app(scope, receive, send)
            return
        start: Message | None = None
        body = b""

        async def collect(message: Message) -> None:
            nonlocal start, body
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                body += message.get("body", b"")

        await self.app(scope, receive, collect)
        assert start is not None
        headers = list(start["headers"])
        names = {k.lower() for k, _ in headers}
        if start["status"] == 200 and b"etag" not in names:
            etag = f'"{hashlib.sha1(body).hexdigest()[:20]}"'
            headers += [(b"etag", etag.encode()), (b"cache-control", NO_CACHE)]
            sent = dict(scope["headers"]).get(b"if-none-match", b"").decode()
            if etag in sent:
                keep = [(k, v) for k, v in headers if k.lower() in (b"etag", b"cache-control")]
                await send({"type": "http.response.start", "status": 304, "headers": keep})
                await send({"type": "http.response.body", "body": b""})
                return
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})
