"""AI provider failures, as responses a person can read (UX-E1).

Every AI surface can fail upstream — a rate limit on the Claude
subscription, an expired key, a provider that is down. None of those were
mapped to a response, so each reached the client as a bare 500 and both
clients showed "Request failed with status code 500". The friendly wording
already existed (`claude_cli.friendly_error`) and was never seen by anyone.

The mapping is by kind of failure, because the kinds want different things
from the user: a rate limit wants them to wait (429), a rejected credential
wants them to go to Settings, and anything else is the provider's problem
(503). Nothing here retries; the provider adapters already do that where a
retry can help.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..integrations.llm import LlmError
from ..integrations.llm.claude_cli import CliError

log = logging.getLogger(__name__)

_RATE_HINTS = (
    "rate limit", "rate-limit", "rate-limited", "429", "overloaded",
    "usage limit", "capacity", "quota", "too many requests",
)
_AUTH_HINTS = (
    "not logged in", "/login", "invalid api key", "authentication_error",
    "unauthorized", "401", "invalid x-api-key", "permission_error",
)

RATE_LIMITED = (
    "The AI is rate-limited right now — try again in a minute."
)
AUTH_REJECTED = (
    "The AI provider rejected its credentials. Check Settings → AI."
)


def classify(err: Exception) -> tuple[int, str]:
    """(status code, message) for a provider failure."""
    text = str(err)
    low = text.lower()
    status = getattr(err, "status_code", None)
    if status == 429 or any(h in low for h in _RATE_HINTS):
        return 429, RATE_LIMITED
    if status in (401, 403) or any(h in low for h in _AUTH_HINTS):
        return 503, AUTH_REJECTED
    # The adapters raise with a message already written for a person; keep
    # it, but never let an empty one through as a blank error.
    return 503, f"The AI provider failed: {text}" if text else "The AI provider failed."


async def _handle(request: Request, exc: Exception) -> JSONResponse:
    code, message = classify(exc)
    log.warning("AI provider error on %s → %d: %s",
                request.url.path, code, str(exc)[:300])
    headers = {"Retry-After": "60"} if code == 429 else None
    return JSONResponse(status_code=code, content={"detail": message}, headers=headers)


def install(app: FastAPI) -> None:
    app.add_exception_handler(CliError, _handle)
    app.add_exception_handler(LlmError, _handle)
    try:
        import anthropic
    except ImportError:  # pragma: no cover — the SDK is a hard dependency
        return
    app.add_exception_handler(anthropic.APIStatusError, _handle)
    app.add_exception_handler(anthropic.APIConnectionError, _handle)
