import secrets

from fastapi import Header, HTTPException, status

from .config import settings


def _eq(a: str, b: str) -> bool:
    """Constant-time token comparison — avoids leaking token length/prefix
    via response timing. Matches the secrets.compare_digest used for the
    Concept2 webhook secret elsewhere."""
    return bool(a) and bool(b) and secrets.compare_digest(a, b)


def _check(token: str, expected: str) -> None:
    if not _eq(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _bearer_or_401(authorization: str | None) -> str:
    """Extract the bearer token, or raise 401.

    `Header(...)` made the header a REQUIRED field, so FastAPI answered a
    missing Authorization with 422 Unprocessable Entity and a validation
    body about a missing field. That is the wrong answer to "you did not
    authenticate": 422 says the request was malformed, so a client cannot
    tell an unconfigured token from a genuinely bad request, and the
    dashboard's own first-run state — no token saved yet — reported itself
    as a schema error.

    401 with WWW-Authenticate is what the situation actually is, and it is
    what lets a client show "set your token" instead of "something went
    wrong".
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="bearer required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def require_ingest(authorization: str | None = Header(None)) -> None:
    _check(_bearer_or_401(authorization), settings.ingest_token)


def require_query(authorization: str | None = Header(None)) -> None:
    _check(_bearer_or_401(authorization), settings.query_token)


def require_any(authorization: str | None = Header(None)) -> None:
    """Accept either the ingest or the query token. Used on endpoints
    that both the phone and the dashboard legitimately need — e.g. sober
    time, where the phone's reset button and the dashboard counter both
    hit the same API but the phone only stores one (ingest) token."""
    token = _bearer_or_401(authorization)
    if not _eq(token, settings.ingest_token) and not _eq(token, settings.query_token):
        raise HTTPException(
            status_code=401,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
