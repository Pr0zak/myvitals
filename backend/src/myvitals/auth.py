import functools
import logging
import re
import secrets

from fastapi import Header, HTTPException, Request, status

from .config import settings

log = logging.getLogger(__name__)


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


# ── Scoped read tokens ──────────────────────────────────────────────────
#
# INGEST_TOKEN writes everything and QUERY_TOKEN reads everything, including
# the MCP endpoint, bulk export, sobriety, fasting, blood pressure and the
# journal. Neither is a credential another app should hold. A scoped read
# token is: it may only GET the routes below, and every response it receives
# is redacted on the way out (`scoped_access.py` — route geometry, blood
# pressure, fasting, sobriety and journal fields are removed).
#
# Enforcement is layered so that no single mistake widens it:
#   1. `scoped_access.ScopedReadMiddleware` runs before routing and answers
#      403 to a scoped token on anything not in this allow-list — including
#      routes with no auth dependency of their own.
#   2. `require_any` accepts a scoped token only when that middleware marked
#      the request AND the request's own path and method pass the same
#      allow-list again.
#   3. `require_query` / `require_ingest` never accept one.
#
# The allow-list matches on the path the router sees (after any root_path),
# never on a prefix of `/summary` or `/query` as a whole: `/summary/today/
# snapshot` bundles sobriety, fasting, journal and profile data, and
# `/query/blood-pressure` is exactly what this token exists to keep out.

#: Exact GET paths a scoped token may read.
SCOPED_READ_EXACT: frozenset[str] = frozenset({
    "/health",
    "/version",
    "/summary/today",
    "/summary/range",
    "/summary/day",
    "/summary/tiles",
    "/summary/readiness",
    "/summary/events",
    "/summary/training-load",
    "/summary/compare",
    "/summary/coverage",
    "/query/sleep/last",
    "/query/sleep/range",
    "/query/hrv",
    "/query/data-health",
    "/query/last-sync",
    "/activities",
    "/activities/stats",
    "/ai/alerts",
    "/trails",
})

#: GET path prefixes a scoped token may read (every route under them).
SCOPED_READ_PREFIXES: tuple[str, ...] = ("/workout/strength/", "/trails/")

#: Carved back out of a prefix above. `resolve-link` makes an outbound HTTP
#: request on the caller's behalf — a utility, not a read of the user's data.
SCOPED_READ_DENY: frozenset[str] = frozenset({"/trails/resolve-link"})

#: Key under which the middleware records, in the ASGI scope, which scoped
#: token authenticated this request. `require_any` refuses a scoped token on
#: a request that does not carry it, so an app that forgot the middleware
#: fails closed rather than open.
SCOPE_KEY = "myvitals.scoped_token"

#: Scoped tokens shorter than this are ignored — one typed by hand is
#: guessable. `openssl rand -hex 32` gives 64.
MIN_SCOPED_TOKEN_LEN = 24

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def scoped_path_allowed(method: str, path: str | None) -> bool:
    """Whether a scoped read token may make this request at all."""
    if method != "GET" or not path:
        return False
    if path in SCOPED_READ_DENY:
        return False
    if path in SCOPED_READ_EXACT:
        return True
    return any(path.startswith(p) and len(path) > len(p) for p in SCOPED_READ_PREFIXES)


@functools.lru_cache(maxsize=8)
def _parse_scoped(raw: str, ingest: str, query: str) -> tuple[tuple[str, str], ...]:
    """`name:token,name:token` → ((name, token), ...), dropping bad entries.

    A bad entry is logged BY NAME ONLY and skipped rather than failing
    startup: one typo must not take the phone's ingest path down with it.
    Skipping is also the safe direction — a dropped entry grants nothing.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, part in enumerate(p.strip() for p in (raw or "").split(",")):
        if not part:
            continue
        name, sep, token = part.partition(":")
        name, token = name.strip(), token.strip()
        label = name if _NAME_RE.match(name) else f"entry #{i + 1}"
        if not sep or not _NAME_RE.match(name):
            log.error("SCOPED_READ_TOKENS: %s is not name:token — ignored", label)
            continue
        if len(token) < MIN_SCOPED_TOKEN_LEN:
            log.error(
                "SCOPED_READ_TOKENS: token %r is shorter than %d characters — ignored",
                name, MIN_SCOPED_TOKEN_LEN,
            )
            continue
        # A scoped token equal to a full-access token would be ambiguous:
        # the full-access check matches first, so the "scoped" caller would
        # silently get everything.
        if _eq(token, ingest) or _eq(token, query):
            log.error(
                "SCOPED_READ_TOKENS: token %r equals INGEST_TOKEN or QUERY_TOKEN — ignored",
                name,
            )
            continue
        if name in seen:
            log.error("SCOPED_READ_TOKENS: duplicate name %r — later entry ignored", name)
            continue
        if any(_eq(token, t) for _, t in out):
            log.error("SCOPED_READ_TOKENS: token %r duplicates another entry — ignored", name)
            continue
        seen.add(name)
        out.append((name, token))
    return tuple(out)


def scoped_tokens() -> tuple[tuple[str, str], ...]:
    """The configured scoped tokens as ((name, token), ...)."""
    return _parse_scoped(
        settings.scoped_read_tokens, settings.ingest_token, settings.query_token,
    )


def scoped_token_name(token: str | None) -> str | None:
    """The name of the scoped token `token` matches, else None.

    Compares against EVERY configured entry, with no early exit, so the
    response time does not say which entry (or how many) matched.
    """
    if not token:
        return None
    found: str | None = None
    for name, expected in scoped_tokens():
        if _eq(token, expected) and found is None:
            found = name
    return found


def _route_path(scope: dict) -> str:
    """The path the router matches against (scope path minus root_path).

    Mirrors starlette's own `get_route_path`, so the allow-list is checked
    against exactly the string the router will dispatch on.
    """
    path: str = scope.get("path", "")
    root = scope.get("root_path", "")
    if not root or not path.startswith(root):
        return path
    if path == root:
        return ""
    return path[len(root):] if path[len(root)] == "/" else path


def scoped_token_of(request: Request | None) -> str | None:
    """Name of the scoped token that authenticated `request`, else None.

    For endpoints that shape their answer for a scoped caller (e.g.
    `/activities` never loads route geometry for one).
    """
    if request is None:
        return None
    return request.scope.get(SCOPE_KEY)


def _forbidden(detail: str = "this token cannot access this route") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _accept_scoped(token: str, request: Request | None) -> bool:
    """True if `token` is a scoped token allowed on this request.

    Raises 403 when it IS a scoped token but not allowed here; returns
    False when it is not a scoped token at all (the caller then answers
    401 exactly as before).
    """
    name = scoped_token_name(token)
    if name is None:
        return False
    if request is None or request.scope.get(SCOPE_KEY) != name:
        raise _forbidden()
    if not scoped_path_allowed(request.method, _route_path(request.scope)):
        raise _forbidden()
    return True


def require_ingest(authorization: str | None = Header(None)) -> None:
    token = _bearer_or_401(authorization)
    if scoped_token_name(token) is not None:
        raise _forbidden()
    _check(token, settings.ingest_token)


def require_query(authorization: str | None = Header(None)) -> None:
    token = _bearer_or_401(authorization)
    if scoped_token_name(token) is not None:
        raise _forbidden()
    _check(token, settings.query_token)


def require_any(
    authorization: str | None = Header(None),
    request: Request = None,  # type: ignore[assignment]  # injected by FastAPI
) -> None:
    """Accept either the ingest or the query token. Used on endpoints
    that both the phone and the dashboard legitimately need — e.g. sober
    time, where the phone's reset button and the dashboard counter both
    hit the same API but the phone only stores one (ingest) token.

    Also accepts a scoped read token, but only on an allow-listed GET route
    that `ScopedReadMiddleware` has already vetted (see the block above).
    """
    token = _bearer_or_401(authorization)
    if _eq(token, settings.ingest_token) or _eq(token, settings.query_token):
        return
    if _accept_scoped(token, request):
        return
    raise HTTPException(
        status_code=401,
        detail="invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
