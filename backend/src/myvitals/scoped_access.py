"""Gate + redaction for scoped read tokens (see the block in auth.py).

`ScopedReadMiddleware` runs before routing. For a request that carries a
scoped read token it:

1. answers 403 unless the method is GET and the path is allow-listed —
   whether or not the route has an auth dependency of its own;
2. records which token it was in the ASGI scope, which `require_any`
   insists on seeing before it will accept a scoped token;
3. buffers the JSON response and passes it through `redact()`, so fields a
   scoped caller must never receive are removed even when an allowed route
   embeds them (`/summary/day` carries the journal and blood pressure,
   `/summary/range` carries fasting hours, `/ai/alerts` can carry a
   sobriety goal).

Requests with any other token, or none, pass through untouched: nothing is
buffered, parsed or rewritten for the phone or the dashboard.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import SCOPE_KEY, _route_path, scoped_path_allowed, scoped_token_name

log = logging.getLogger(__name__)

#: Keys removed wherever they appear in a response to a scoped token.
REDACTED_KEYS: frozenset[str] = frozenset({
    # Route geometry. Routes start and end at home.
    "polyline", "polyline_simple", "summary_polyline",
    "latlng", "start_latlng", "end_latlng",
    # Blood pressure.
    "bp_systolic_avg", "bp_diastolic_avg", "blood_pressure", "bp30",
    "systolic", "diastolic",
    # Fasting.
    "fasting_hours", "fasting",
    # Sobriety.
    "sober",
    # Journal.
    "annotations", "annotations1d", "journal",
})

#: A list item that is a dict whose `key`, `metric` or `kind` is one of
#: these (a Blood-pressure tile, a data-health stream, a sobriety-goal
#: alert), or a bare string equal to one, is dropped from the list.
SENSITIVE_TAGS: frozenset[str] = frozenset({
    "blood_pressure", "bp", "sober", "fasting", "fast_streak", "journal",
})
_TAG_FIELDS = ("key", "metric", "kind")

_FORBIDDEN = {"detail": "this token cannot access this route"}
_UNREDACTABLE = {"detail": "this response is not available to a scoped token"}


def _is_sensitive_item(item: Any) -> bool:
    if isinstance(item, str):
        return item in SENSITIVE_TAGS
    if isinstance(item, dict):
        for f in _TAG_FIELDS:
            v = item.get(f)
            if isinstance(v, str) and v in SENSITIVE_TAGS:
                return True
    return False


def redact(value: Any) -> Any:
    """`value` with every scoped-token-forbidden field removed (recursive)."""
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k not in REDACTED_KEYS}
    if isinstance(value, list):
        return [redact(v) for v in value if not _is_sensitive_item(v)]
    return value


def _bearer(scope: Scope) -> str | None:
    """The bearer token from the first Authorization header, parsed the same
    way `auth._bearer_or_401` parses it (and Starlette's Headers.get picks
    the first header too)."""
    for name, value in scope.get("headers") or ():
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return token if scheme.lower() == "bearer" else None
    return None


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body, separators=(",", ":")).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": raw})


class _RedactingSend:
    """Buffers one HTTP response and forwards it redacted.

    Fails closed: a response that is not plain JSON (compressed, a file,
    a stream of some other type) is replaced with a 500 rather than passed
    through unread.
    """

    def __init__(self, send: Send) -> None:
        self._send = send
        self._start: Message | None = None
        self._chunks: list[bytes] = []
        self._done = False

    async def __call__(self, message: Message) -> None:
        if self._done:
            return
        kind = message["type"]
        if kind == "http.response.start":
            self._start = message
            return
        if kind == "http.response.body":
            self._chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                await self._flush()
            return
        # http.response.pathsend / zerocopy / trailers: nothing here can be
        # redacted, so nothing here is sent.
        await self._fail()

    async def _fail(self) -> None:
        self._done = True
        await _send_json(self._send, 500, _UNREDACTABLE)

    async def _flush(self) -> None:
        start = self._start
        if start is None:
            await self._fail()
            return
        body = b"".join(self._chunks)
        headers = MutableHeaders(raw=list(start.get("headers", [])))
        if body:
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            is_json = ctype == "application/json" or ctype.endswith("+json")
            if not is_json or headers.get("content-encoding"):
                await self._fail()
                return
            try:
                data = json.loads(body)
            except ValueError:
                await self._fail()
                return
            body = json.dumps(
                redact(data), ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ).encode("utf-8")
            headers["content-length"] = str(len(body))
        self._done = True
        await self._send({**start, "headers": headers.raw})
        await self._send({"type": "http.response.body", "body": body})


class ScopedReadMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        name = scoped_token_name(_bearer(scope))
        if name is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Closing before accept makes the server answer the upgrade 403.
            await send({"type": "websocket.close", "code": 1008})
            return
        method = scope.get("method", "")
        path = _route_path(scope)
        if not scoped_path_allowed(method, path):
            log.info("scoped token %r refused: %s %s", name, method, path)
            await _send_json(send, 403, _FORBIDDEN)
            return
        scope[SCOPE_KEY] = name
        await self.app(scope, receive, _RedactingSend(send))
