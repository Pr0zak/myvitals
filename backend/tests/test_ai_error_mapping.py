"""AI provider failures reach the user as words, not a bare 500 (UX-E1)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from myvitals.api import errors
from myvitals.integrations.llm import LlmError
from myvitals.integrations.llm.claude_cli import CliError


def _app(exc: Exception) -> TestClient:
    app = FastAPI()
    errors.install(app)

    @app.post("/boom")
    async def boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_a_rate_limit_is_429_with_a_retry_hint():
    r = _app(CliError("the AI is temporarily rate-limited on the Claude subscription")).post("/boom")
    assert r.status_code == 429
    assert r.json()["detail"] == errors.RATE_LIMITED
    assert r.headers["retry-after"] == "60"


def test_a_rejected_credential_points_at_settings():
    r = _app(LlmError("401 Unauthorized: invalid x-api-key")).post("/boom")
    assert r.status_code == 503
    assert "Settings" in r.json()["detail"]


def test_anything_else_is_503_and_keeps_the_providers_words():
    r = _app(CliError("claude CLI timed out after 180s")).post("/boom")
    assert r.status_code == 503
    assert "timed out after 180s" in r.json()["detail"]


def test_the_handlers_are_installed_on_the_real_app():
    from myvitals.main import app
    assert CliError in app.exception_handlers
    assert LlmError in app.exception_handlers
