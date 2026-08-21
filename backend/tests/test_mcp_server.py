"""Read-only MCP endpoint (MCP-1).

The transport rules here are exact — a client that follows the spec will
reject a server that does not — so most of these pin behaviour the spec
states as MUST.
"""

from __future__ import annotations

import inspect

import pytest

from myvitals.api import mcp
from myvitals.integrations import mcp_tools


class TestReadOnly:
    def test_no_tool_name_suggests_mutation(self):
        """The safety property this server rests on.

        Its whole value is letting a model read health data. A model
        *writing* to a health record it partly misunderstands is not worth
        any convenience it would buy, so there is no write path — and this
        catches the moment someone adds one.
        """
        forbidden = (
            "set_", "update_", "delete_", "create_", "add_", "put_",
            "post_", "log_", "write_", "remove_", "patch_", "clear_",
        )
        for name in mcp_tools.TOOLS:
            assert not name.startswith(forbidden), (
                f"{name} looks like a mutation; this server is read-only"
            )

    def test_every_tool_advertises_readonly(self):
        for t in mcp_tools.tool_list():
            assert t["annotations"]["readOnlyHint"] is True
            assert t["annotations"]["destructiveHint"] is False

    def test_no_tool_handler_writes_to_the_session(self):
        for name, (_d, _s, fn) in mcp_tools.TOOLS.items():
            src = inspect.getsource(fn)
            for verb in ("db.add(", "db.commit(", "db.delete(", "db.merge("):
                assert verb not in src, f"{name} calls {verb}"


class TestPrivacy:
    def test_activity_titles_are_not_exposed(self):
        """Strava titles routinely embed home and workplace addresses.

        `test_ai_privacy.py` keeps them out of Claude payloads; this tool
        reads the Activity table directly, so it has to make the same
        choice explicitly rather than inheriting it.
        """
        src = inspect.getsource(mcp_tools._activities)
        assert '"name"' not in src, "activity titles must not be returned"
        assert "a.name" not in src


class TestSchemas:
    def test_every_tool_has_a_description_and_schema(self):
        for t in mcp_tools.tool_list():
            assert t["description"].strip()
            assert t["inputSchema"]["type"] == "object"

    def test_schemas_reject_unknown_arguments(self):
        """additionalProperties:false makes a hallucinated argument fail
        loudly at the client rather than being silently ignored here."""
        for t in mcp_tools.tool_list():
            assert t["inputSchema"].get("additionalProperties") is False

    @pytest.mark.parametrize(
        "raw,expected",
        [(None, 30), ("garbage", 30), (0, 1), (-5, 1), (100000, 365), (14, 14)],
    )
    def test_days_are_clamped_not_rejected(self, raw, expected):
        """An MCP client is a model choosing its own arguments.

        `days: 100000` will happen. Clamping keeps a reasonable question
        answerable; erroring fails it on an implementation detail the
        model cannot see.
        """
        assert mcp_tools._clamp_days(raw, 30, 365) == expected


class TestProtocolConstants:
    def test_advertises_the_current_revision_first(self):
        assert mcp.SUPPORTED_VERSIONS[0] == "2026-07-28"
        assert mcp.MODERN_VERSION == "2026-07-28"

    def test_still_supports_the_handshake_era(self):
        """A server that speaks only the newest revision is useless to a
        client that has not shipped it yet, and 2026-07-28 was under a
        month old when this was written."""
        assert "2025-11-25" in mcp.SUPPORTED_VERSIONS

    def test_header_mismatch_uses_the_spec_allocated_code(self):
        assert mcp.HEADER_MISMATCH == -32020


class TestOriginValidation:
    def test_absent_origin_is_allowed(self):
        """Real MCP clients are not browsers and send no Origin."""
        assert mcp._origin_allowed(None) is True

    @pytest.mark.parametrize("origin", [
        "http://localhost:3000", "https://localhost", "http://127.0.0.1:8080",
    ])
    def test_local_origins_allowed(self, origin):
        assert mcp._origin_allowed(origin) is True

    @pytest.mark.parametrize("origin", [
        "https://evil.example.com", "http://attacker.test",
        "https://localhost.evil.com",
    ])
    def test_foreign_origins_refused(self, origin):
        """DNS rebinding: a page resolves its own host to 127.0.0.1 and
        then POSTs here, using the user's machine as a confused deputy.

        Note `localhost.evil.com` — a prefix check would pass it, which is
        why the guard matches on scheme+host rather than substring.
        """
        assert mcp._origin_allowed(origin) is False


class TestHeaderDecoding:
    def test_plain_values_pass_through(self):
        assert mcp._decode_header("get_sleep") == "get_sleep"

    def test_base64_sentinel_is_decoded(self):
        """Clients encode non-ASCII header values as `=?base64?…?=`.

        Comparing the encoded form against a plain body value would fail
        validation every time.
        """
        import base64 as b64
        raw = "Hello, 世界"
        enc = "=?base64?" + b64.b64encode(raw.encode()).decode() + "?="
        assert mcp._decode_header(enc) == raw

    def test_malformed_base64_falls_back_to_the_raw_value(self):
        """Better a header mismatch than a 500 on bad input."""
        assert mcp._decode_header("=?base64?!!!not-b64!!!?=").startswith("=?base64?")


class TestRemovedMechanisms:
    def test_get_and_delete_are_rejected(self):
        """Sessions and the standalone stream were removed in 2026-07-28.

        The spec asks a server that only speaks this revision to answer
        405, so an older client detects the era instead of hanging on a
        stream that will never open.
        """
        src = inspect.getsource(mcp.mcp_rejected_methods)
        assert "405" in src

    def test_sessions_are_never_minted(self):
        src = inspect.getsource(mcp)
        assert "Mcp-Session-Id" not in src.replace(
            "`Mcp-Session-Id` is ignored, never minted", "",
        ), "the server must not mint or echo session ids"


class TestTransportEndToEnd:
    """Drives the real ASGI app, so routing, auth, headers, origin checks
    and JSON-RPC framing are all exercised together.

    A protocol implementation that has never answered an actual HTTP
    request is not verified — the parts that break are the joins between
    layers, which unit tests on helper functions cannot see.

    The database session is overridden with a stub: these assert transport
    conformance, not query results.
    """

    @pytest.fixture()
    def client(self, monkeypatch):
        # `settings` is read at import, so setenv here would be too late.
        # Patch the loaded object instead.
        from myvitals.config import settings as _settings
        monkeypatch.setattr(_settings, "query_token", "query-test", raising=False)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # A bare app carrying only the MCP router: importing the whole
        # application would start schedulers and background pollers, which
        # a transport test has no business doing.
        app = FastAPI()
        app.include_router(mcp.router)

        from myvitals.db.session import get_session
        app.dependency_overrides[get_session] = lambda: None
        return TestClient(app)

    AUTH = {"Authorization": "Bearer query-test"}

    def _post(self, client, body, headers=None):
        h = {**self.AUTH, **(headers or {})}
        return client.post("/mcp", json=body, headers=h)

    def test_unauthenticated_is_refused(self, client):
        r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code in (401, 403, 422)

    def test_get_returns_405(self, client):
        r = client.get("/mcp", headers=self.AUTH)
        assert r.status_code == 405

    def test_delete_returns_405(self, client):
        r = client.delete("/mcp", headers=self.AUTH)
        assert r.status_code == 405

    def test_foreign_origin_is_403(self, client):
        r = self._post(
            client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"Origin": "https://evil.example.com"},
        )
        assert r.status_code == 403

    def test_tools_list_over_the_handshake_era(self, client):
        r = self._post(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert "get_daily_summary" in names
        assert names == set(mcp_tools.TOOLS)

    def test_initialize_negotiates_a_supported_version(self, client):
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        })
        assert r.json()["result"]["protocolVersion"] == "2025-11-25"

    def test_initialize_falls_back_for_an_unknown_version(self, client):
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        })
        assert r.json()["result"]["protocolVersion"] == mcp.MODERN_VERSION

    def test_server_discover_lists_versions(self, client):
        r = self._post(client, {"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
        res = r.json()["result"]
        assert mcp.MODERN_VERSION in res["protocolVersions"]
        assert res["serverInfo"]["name"] == "myvitals"

    def test_modern_request_requires_the_method_header(self, client):
        """The header mirroring is a MUST, and the reason is real: an
        intermediary routing on the header while the server executes the
        body is a security bug if they can disagree."""
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": {mcp._META_VERSION_KEY: mcp.MODERN_VERSION}},
        }, {"MCP-Protocol-Version": mcp.MODERN_VERSION})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == mcp.HEADER_MISMATCH

    def test_modern_request_with_matching_headers_succeeds(self, client):
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": {mcp._META_VERSION_KEY: mcp.MODERN_VERSION}},
        }, {
            "MCP-Protocol-Version": mcp.MODERN_VERSION,
            "Mcp-Method": "tools/list",
        })
        assert r.status_code == 200
        assert "tools" in r.json()["result"]

    def test_header_and_meta_version_must_agree(self, client):
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": {mcp._META_VERSION_KEY: "2025-11-25"}},
        }, {"MCP-Protocol-Version": mcp.MODERN_VERSION, "Mcp-Method": "tools/list"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == mcp.HEADER_MISMATCH

    def test_unsupported_version_lists_what_is_supported(self, client):
        r = self._post(
            client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"MCP-Protocol-Version": "1999-01-01"},
        )
        assert r.status_code == 400
        assert mcp.MODERN_VERSION in r.json()["error"]["data"]["supported"]

    def test_unknown_method_is_404_with_a_jsonrpc_body(self, client):
        """The JSON-RPC body is what distinguishes this from a 404 by a
        server that hosts no MCP endpoint at all."""
        r = self._post(client, {"jsonrpc": "2.0", "id": 1, "method": "nope/nope"})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == mcp.METHOD_NOT_FOUND

    def test_notification_gets_202_and_no_body(self, client):
        r = self._post(client, {"jsonrpc": "2.0", "method": "notifications/whatever"})
        assert r.status_code == 202
        assert not r.content

    def test_unknown_tool_is_a_tool_error_not_a_transport_error(self, client):
        """The model called a valid method with a bad argument. Returning
        isError lets it read the message and correct itself; a transport
        error just fails the turn."""
        r = self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "definitely_not_a_tool", "arguments": {}},
        })
        assert r.status_code == 200
        assert r.json()["result"]["isError"] is True

    def test_malformed_json_is_a_parse_error(self, client):
        r = client.post(
            "/mcp", content=b"{not json", headers={**self.AUTH,
                                                   "Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == mcp.PARSE_ERROR

    def test_non_jsonrpc_body_is_rejected(self, client):
        r = self._post(client, {"hello": "world"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == mcp.INVALID_REQUEST
