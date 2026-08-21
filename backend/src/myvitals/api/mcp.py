"""Read-only MCP endpoint (MCP-1).

Publishes the aggregates this app already computes as MCP tools, so the
user's own Claude subscription can read their health data directly rather
than every question billing the app's Anthropic key.

## Transport

Streamable HTTP, request/response only. A single POST endpoint, single
JSON object per response, no SSE.

The 2026-07-28 spec revision made this *simpler* than earlier ones, not
harder: it removed protocol-level sessions, removed the GET stream, and
replaced the `initialize` handshake with per-request version negotiation
via `_meta`. A read-only server that streams nothing needs none of the
machinery that revision deleted.

Two eras are supported:

* **2026-07-28** — per-request `_meta.io.modelcontextprotocol/protocolVersion`,
  mirrored in the `MCP-Protocol-Version` header, with `Mcp-Method` and
  `Mcp-Name` headers that MUST match the body.
* **2025-11-25 and earlier** — the `initialize` handshake. Supported
  because clients in the field still speak it; the revision is under a
  month old at time of writing, and a server that only speaks the newest
  version is useless to a client that has not shipped it yet.

Deliberately NOT implemented, with the spec's own guidance for each:
sessions (`Mcp-Session-Id` is ignored, never minted), the standalone GET
stream (405), resumable streams (`Last-Event-ID` ignored), and
`subscriptions/listen`. Nothing here changes, so there is nothing to
subscribe to.

## Security

* `Origin` is validated — the spec requires it to prevent DNS rebinding,
  where a page you visit resolves a hostname to 127.0.0.1 and then talks
  to a local MCP server from your browser.
* Authentication reuses the existing query token via `Authorization:
  Bearer`. Deliberately not a new secret: another credential to generate,
  store and rotate is a worse security outcome than reusing the one that
  already gates every other read endpoint.
* Read-only. There is no write path and no tool that mutates anything.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import urlparse
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db.session import get_session
from ..integrations import mcp_tools

router = APIRouter()
log = logging.getLogger(__name__)

SERVER_NAME = "myvitals"
SERVER_VERSION = "1"

#: Newest first — this is what UnsupportedProtocolVersionError advertises.
SUPPORTED_VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26")
MODERN_VERSION = "2026-07-28"

#: JSON-RPC error codes. -32020 is allocated by the MCP spec.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020

_META_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_BASE64_PREFIX = "=?base64?"
_BASE64_SUFFIX = "?="


def _err(
    id_: Any, code: int, message: str, data: dict[str, Any] | None = None,
    status: int = 200,
) -> JSONResponse:
    body: dict[str, Any] = {
        "jsonrpc": "2.0", "id": id_,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        body["error"]["data"] = data
    return JSONResponse(body, status_code=status)


def _ok(id_: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": result})


def _decode_header(value: str) -> str:
    """Undo the spec's Base64 sentinel encoding, if present.

    Clients encode header values that cannot be represented as plain ASCII
    as `=?base64?<b64>?=`. Comparing an encoded header against a plain body
    value would fail every time, so decode before validating.
    """
    if value.startswith(_BASE64_PREFIX) and value.endswith(_BASE64_SUFFIX):
        inner = value[len(_BASE64_PREFIX):-len(_BASE64_SUFFIX)]
        try:
            return base64.b64decode(inner).decode("utf-8")
        except Exception:  # noqa: BLE001
            return value
    return value


def _origin_allowed(origin: str | None) -> bool:
    """Reject cross-origin browser traffic.

    The attack this blocks is DNS rebinding: a page you visit resolves its
    own hostname to 127.0.0.1 and then POSTs to a local MCP server, using
    your machine as the confused deputy. A real MCP client (Claude Desktop,
    Claude Code) sends no Origin at all, so absence is allowed and only a
    *present, foreign* Origin is refused.
    """
    if origin is None:
        return True
    if origin.lower() == "null":
        return True
    # Parsed, not prefix-matched. `startswith("https://localhost")` also
    # matches `https://localhost.evil.com`, which is an attacker-controlled
    # host and precisely the bypass this guard exists to stop. Comparing
    # the parsed hostname exactly is the only form that holds.
    try:
        parsed = urlparse(origin)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "").lower() in ("localhost", "127.0.0.1", "::1")


@router.get("/mcp")
@router.delete("/mcp")
async def mcp_rejected_methods() -> Response:
    """GET and DELETE were the session / stream mechanisms of older
    revisions. 2026-07-28 removed both, and instructs a server that only
    speaks this revision to answer 405 so an older client can detect the
    era rather than hang waiting for a stream that will never open."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp", dependencies=[Depends(require_query)])
async def mcp_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> Response:
    if not _origin_allowed(request.headers.get("origin")):
        return _err(
            None, INVALID_REQUEST, "Origin not allowed.", status=403,
        )

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _err(None, PARSE_ERROR, "Invalid JSON.", status=400)

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _err(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message.", status=400)

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    meta = params.get("_meta") or {}

    # A notification has no id. Nothing here needs to act on one, but the
    # spec requires 202 with an empty body rather than a JSON-RPC reply.
    if req_id is None and method is not None:
        return Response(status_code=202)

    # ── version negotiation ──────────────────────────────────────────
    header_version = request.headers.get("mcp-protocol-version")
    body_version = meta.get(_META_VERSION_KEY) if isinstance(meta, dict) else None

    if header_version and body_version and header_version != body_version:
        return _err(
            req_id, HEADER_MISMATCH,
            "MCP-Protocol-Version header does not match _meta.",
            status=400,
        )

    version = header_version or body_version
    if version and version not in SUPPORTED_VERSIONS:
        return _err(
            req_id, INVALID_REQUEST,
            f"Unsupported protocol version {version}.",
            data={"supported": list(SUPPORTED_VERSIONS)},
            status=400,
        )
    modern = version == MODERN_VERSION

    # ── mirrored-header validation (2026-07-28) ──────────────────────
    # The spec requires these to match the body so an intermediary routing
    # on the header and a server executing on the body cannot disagree —
    # the whole point of mirroring them.
    if modern:
        h_method = request.headers.get("mcp-method")
        if h_method is None:
            return _err(req_id, HEADER_MISMATCH, "Missing Mcp-Method header.",
                        status=400)
        if h_method != method:
            return _err(
                req_id, HEADER_MISMATCH,
                f"Mcp-Method header '{h_method}' does not match body '{method}'.",
                status=400,
            )
        if method in ("tools/call", "resources/read", "prompts/get"):
            h_name = request.headers.get("mcp-name")
            b_name = params.get("name") or params.get("uri")
            if h_name is None:
                return _err(req_id, HEADER_MISMATCH, "Missing Mcp-Name header.",
                            status=400)
            if _decode_header(h_name) != b_name:
                return _err(
                    req_id, HEADER_MISMATCH,
                    "Mcp-Name header does not match the body.",
                    status=400,
                )

    # ── dispatch ─────────────────────────────────────────────────────
    try:
        if method == "server/discover":
            # Mandatory in 2026-07-28: lets a client learn supported
            # versions and capabilities in one request instead of guessing.
            return _ok(req_id, {
                "protocolVersions": list(SUPPORTED_VERSIONS),
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
            })

        if method == "initialize":
            # The pre-2026-07-28 handshake. Echo back a version the client
            # asked for when we support it, else our newest — the older
            # spec's negotiation rule.
            asked = params.get("protocolVersion")
            agreed = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            return _ok(req_id, {
                "protocolVersion": agreed,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {"listChanged": False}},
            })

        if method in ("notifications/initialized", "ping"):
            return _ok(req_id, {})

        if method == "tools/list":
            return _ok(req_id, {"tools": mcp_tools.tool_list()})

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return _err(req_id, INVALID_PARAMS, "arguments must be an object.")
            try:
                result = await mcp_tools.call_tool(db, name, args)
            except KeyError:
                # An unknown TOOL is a tool-level failure, not a missing
                # RPC method: the client called a valid method with a bad
                # argument, and isError lets the model see and correct it
                # rather than the transport erroring out.
                return _ok(req_id, {
                    "isError": True,
                    "content": [{
                        "type": "text",
                        "text": (
                            f"Unknown tool '{name}'. Available: "
                            + ", ".join(sorted(mcp_tools.TOOLS))
                        ),
                    }],
                })
            import json as _json
            return _ok(req_id, {
                "content": [{
                    "type": "text",
                    "text": _json.dumps(result, default=str, indent=2),
                }],
                "isError": False,
            })

        # Unknown method. The spec asks for 404 plus a JSON-RPC -32601 so a
        # client can tell this apart from a 404 by a server that does not
        # host an MCP endpoint at all.
        return _err(req_id, METHOD_NOT_FOUND, f"Unknown method '{method}'.",
                    status=404)

    except Exception as e:  # noqa: BLE001
        log.exception("MCP method %s failed", method)
        return _err(req_id, INTERNAL_ERROR, f"{type(e).__name__}: {e}")
