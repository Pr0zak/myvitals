"""Auth: constant-time token comparison + bearer gate behaviour.

Previously zero coverage. Locks the v0.7.292 switch to secrets.compare_digest
and the require_ingest / require_query / require_any token routing (the
phone-uses-ingest-token contract).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from myvitals.auth import _eq, require_any, require_ingest, require_query
from myvitals.config import settings


def test_eq_truth_table():
    assert _eq("abc", "abc") is True
    assert _eq("abc", "abd") is False
    assert _eq("abc", "ab") is False
    # An empty token must never authenticate, even against an empty expected.
    assert _eq("", "") is False
    assert _eq("x", "") is False
    assert _eq("", "x") is False


def test_require_ingest_accepts_ingest_token():
    require_ingest(f"Bearer {settings.ingest_token}")  # no raise == pass


def test_require_query_accepts_query_token():
    require_query(f"Bearer {settings.query_token}")


def test_require_ingest_rejects_query_token():
    with pytest.raises(HTTPException) as ei:
        require_ingest(f"Bearer {settings.query_token}")
    assert ei.value.status_code == 401


def test_require_any_accepts_either_token():
    require_any(f"Bearer {settings.ingest_token}")
    require_any(f"Bearer {settings.query_token}")


def test_require_any_rejects_unknown_token():
    with pytest.raises(HTTPException) as ei:
        require_any("Bearer definitely-not-a-real-token")
    assert ei.value.status_code == 401


def test_non_bearer_scheme_rejected():
    with pytest.raises(HTTPException):
        require_ingest(f"Basic {settings.ingest_token}")
