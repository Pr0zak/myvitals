from fastapi import Header, HTTPException, status

from .config import settings


def _check(token: str, expected: str) -> None:
    if not token or token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_ingest(authorization: str = Header(...)) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer required")
    _check(token, settings.ingest_token)


def require_query(authorization: str = Header(...)) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer required")
    _check(token, settings.query_token)


def require_any(authorization: str = Header(...)) -> None:
    """Accept either the ingest or the query token. Used on endpoints
    that both the phone and the dashboard legitimately need — e.g. sober
    time, where the phone's reset button and the dashboard counter both
    hit the same API but the phone only stores one (ingest) token."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer required")
    if token != settings.ingest_token and token != settings.query_token:
        raise HTTPException(
            status_code=401,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
