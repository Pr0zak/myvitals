"""A missing Authorization header is 401, not 422 (ONBOARD-1).

`Header(...)` made the header a required FIELD, so FastAPI answered a
missing Authorization with 422 Unprocessable Entity and a validation body
about a missing field.

That is the wrong answer to "you did not authenticate". 422 means the
request was malformed, so a client cannot tell an unconfigured token from
a genuinely bad request — and the dashboard's own first-run state, before
any token is saved, reported itself as a schema error.
"""

from __future__ import annotations

import inspect

import pytest

from fastapi import HTTPException

from myvitals import auth


class TestMissingHeader:
    @pytest.mark.parametrize(
        "dep", [auth.require_ingest, auth.require_query, auth.require_any],
    )
    def test_none_raises_401_not_422(self, dep):
        with pytest.raises(HTTPException) as ei:
            dep(None)
        assert ei.value.status_code == 401

    @pytest.mark.parametrize(
        "dep", [auth.require_ingest, auth.require_query, auth.require_any],
    )
    def test_the_challenge_header_is_present(self, dep):
        """Without WWW-Authenticate a 401 is not a well-formed challenge,
        and some clients will not offer credentials."""
        with pytest.raises(HTTPException) as ei:
            dep(None)
        assert (ei.value.headers or {}).get("WWW-Authenticate") == "Bearer"

    @pytest.mark.parametrize(
        "dep", [auth.require_ingest, auth.require_query, auth.require_any],
    )
    def test_the_header_is_optional_at_the_signature_level(self, dep):
        """If it stays `Header(...)` FastAPI rejects the request before the
        dependency body ever runs, so the 401 above would be unreachable."""
        sig = inspect.signature(dep)
        assert sig.parameters["authorization"].default is not inspect.Parameter.empty

    @pytest.mark.parametrize("bad", ["", "Basic abc", "token abc"])
    def test_a_non_bearer_scheme_is_also_401(self, bad):
        with pytest.raises(HTTPException) as ei:
            auth.require_query(bad)
        assert ei.value.status_code == 401
