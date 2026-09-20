"""Application logging.

The app had none. Not a `basicConfig`, not a `dictConfig`, not a `setLevel`
anywhere — and `fastapi run` configures only the `uvicorn.*` loggers, leaving
the root logger at Python's default of WARNING. So all 51 `log.info` call
sites across this codebase wrote into a void: sync results, scheduled job
outcomes, ingest counts, cardio-day completion, every one of them discarded.
Only warnings and errors ever reached the container output.

That is worse than it sounds, because it is invisible. Nothing fails; the
information simply never appears, so the natural conclusion when a scheduled
job seems not to have run is that it did not run. Diagnosing a routine "did
the poll work?" question meant re-running the work by hand to observe it.

`Settings.log_level` already existed to control exactly this, and was never
read — the "declared but unconsumed" pattern that a codebase audit had
already flagged elsewhere.

Third-party loggers are deliberately pinned lower than the app's. `httpx`
emits an INFO line per request, which on a Google Health sync means one line
per page of results; at that volume the app's own messages are lost in the
noise, which is the same failure as not logging them at all.

SA-O6 — server rows in `app_logs`
----------------------------------
`app_logs` / the Logs page / `GET /debug/logs` have always existed for
`source in (phone, server)`, and no backend code path had ever written a
`server` row: every scheduled-job `log.warning` went to container stdout
only, capped and wiped on the next `docker compose up --force-recreate`.

`_ServerLogHandler` below closes that gap, deliberately narrowly:

* **WARNING and above only.** INFO/DEBUG stay stdout-only. The point is
  "did something fail", not a second copy of the access log — and the
  phone side of this same table is already 265k+ rows with no retention
  (a separate finding, SA-C3, owns adding one); a new writer must not
  make that worse. At the measured WARNING+ rate here (a double-digit
  count of ASGI 500s per few days, and long stretches of zero scheduled-
  job warnings) this adds a trickle, not a second phone.
* **An explicit ALLOWLIST of loggers, not "every WARNING in the app".**
  `analytics/jobs.py`'s anomaly-alert warnings interpolate the actual
  reading that tripped them — resting heart rate, blood-pressure
  averages, a weight delta in kg, a skin-temperature delta — straight
  into the message string (e.g. `"BP stage-%d alert for %s: 7d avg
  %s/%s"`). Piping that into a table a UI renders would be exactly the
  leak this project's whole privacy posture exists to prevent, and
  those alerts are already persisted structurally in `alerts`, so
  nothing is lost by leaving that module out. Several importer/ingest
  modules were left out for the same reason from the other direction:
  a parse-failure exception can echo the offending field back in its
  message (concretely, the Sober CSV importer's real-name-in-
  `addiction`-column gotcha this repo already knows about), so
  `api/imports.py`, `api/ingest.py`, `integrations/imports.py`,
  `integrations/fit_tracks.py`, `api/strava.py`,
  `integrations/strava_web.py`, `api/google_health.py` and
  `integrations/google_health.py` are not wired either. Every call site
  actually included below was read: each one interpolates an exception
  message, a status code, an entity id, a page number, or a count —
  never a physiological value. Widening this list later means re-doing
  that read, not just adding a name.

  **That audit covers the allowlisted `myvitals.*` loggers only.** The
  `uvicorn.error` catch-all below persists the traceback of *any*
  unhandled exception, and `traceback.format_exception`'s own last line
  IS the exception's message — a Pydantic `ValidationError` quotes the
  offending input, and a SQLAlchemy `IntegrityError` quotes the
  conflicting key. On a health table either could put a measurement
  into this row. That is the user's own value, in their own database,
  shown in their own UI, so it was never a leak across a trust boundary
  — but it was not the clean "no physiological value ever" guarantee
  the paragraph above makes for the named loggers. **Fixed (SA-C13):**
  for `uvicorn.error` only, `_format_stack()` builds the persisted
  `stack` from `traceback.format_tb` (frames — file, line, function,
  i.e. *where* it broke) plus the exception's bare type name, and never
  calls `format_exception`/`format_exception_only` — the calls that
  render the message text, i.e. *what was in it*. The allowlisted
  loggers are unaffected and keep the full traceback text, since their
  call sites are the ones actually read end to end.
* **`uvicorn.error` is wired directly, not via root.** That is the one
  new *signal* worth having: unhandled exceptions become the generic
  500 Starlette returns, and uvicorn logs them itself as "Exception in
  ASGI application" — but uvicorn's own logging config gives
  `uvicorn.error` `propagate=True` while its PARENT `uvicorn` logger is
  `propagate=False`, so those records stop one level up and never reach
  root. A handler only attached to root — the obvious first design —
  would miss the exact failures this table is supposed to catch.
* **Non-blocking, best-effort, no recursion.** `emit()` only appends to
  an in-memory buffer (bounded — see `_MAX_QUEUED`) and, at most,
  schedules a debounced flush on the running loop; the actual DB write
  happens later in `_flush()`, wrapped so a DB hiccup is swallowed
  rather than surfacing as a second failure on top of whatever was
  being logged. The handler is attached only to the allowlisted
  loggers (never to root, never to its own module, never to
  `sqlalchemy.*`), so the write inside `_flush()` cannot log its way
  back into itself.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import traceback
from datetime import datetime, timezone

# Libraries whose INFO output is per-request chatter rather than information.
# Pinned to WARNING so an actual problem still surfaces.
_NOISY = (
    "httpx",
    "httpcore",
    "apscheduler.executors.default",
    "apscheduler.scheduler",
    "urllib3",
    "asyncio",
)

# SA-O6: loggers whose WARNING+ output has been read end to end and never
# interpolates a health value — see the module docstring for what was
# excluded, and why. Add a name here only after doing that same read.
_SERVER_LOG_SOURCES = (
    "myvitals.tasks.scheduled",
    "myvitals.integrations.home_assistant",
    "myvitals.integrations.ha_realtime",
    "myvitals.integrations.osm",
    "myvitals.integrations.claude",
    "myvitals.api.mcp",
)

# Not a `myvitals.*` logger: uvicorn's own "Exception in ASGI application"
# (the unhandled-exception → 500 path). See module docstring for why root
# alone can't see it, and for SA-C13 on why its `stack` is built differently
# from the allowlisted loggers' (see `_format_stack` below).
_UVICORN_ERROR_LOGGER = "uvicorn.error"

_MAX_QUEUED = 200
_FLUSH_AFTER_S = 5.0
_MAX_MESSAGE_CHARS = 2000
_MAX_STACK_CHARS = 4000

_configured = False


def _format_stack(record: logging.LogRecord) -> str | None:
    """Render `record.exc_info` into the `stack` field that gets persisted.

    For the allowlisted `myvitals.*` loggers this is the plain
    `traceback.format_exception` text, unchanged — SA-O6 read every call
    site in `_SERVER_LOG_SOURCES` end to end and confirmed none of them
    raises with a value-carrying message, so the full text is safe.

    `uvicorn.error` gets none of that assurance (SA-C13): it is a
    content-unfiltered catch-all for any unhandled exception anywhere in
    the app, and `traceback.format_exception`'s own last line *is* the
    exception's message — a Pydantic `ValidationError` quotes the
    offending input, a SQLAlchemy `IntegrityError` quotes the conflicting
    key, and either could be a measurement from a failed health-table
    write. `traceback.format_tb` renders only frames — file, line,
    function, no locals, no message text — so for this logger the stack
    is built from that plus the exception's bare type name, and this
    function never calls `format_exception` / `format_exception_only`,
    which are what would pull the message (or a chained cause's message,
    via `__cause__`/`__context__`) back in. Diagnostic value (where it
    broke) is kept; payload (what was in it) is dropped, not merely
    truncated — truncation alone would still leak a short value.
    """
    if not record.exc_info:
        return None
    if record.name != _UVICORN_ERROR_LOGGER:
        return "".join(traceback.format_exception(*record.exc_info))[:_MAX_STACK_CHARS]

    exc_type, _exc_value, tb = record.exc_info
    type_name = exc_type.__name__ if exc_type else "UnknownException"
    frames = "".join(traceback.format_tb(tb)) if tb else "(no traceback available)\n"
    stack = (
        f"{type_name} (message redacted — SA-C13, uvicorn.error is unaudited)\n"
        f"Traceback (most recent call last):\n{frames}"
    )
    return stack[:_MAX_STACK_CHARS]


class _ServerLogHandler(logging.Handler):
    """Buffers WARNING+ records and flushes them into `app_logs` as
    `source="server"`, so the backend's own failures land beside the
    phone's in the same Logs view.

    Only ever attached to the loggers in `_SERVER_LOG_SOURCES` plus
    `uvicorn.error` (see `configure_logging`) — never to root, never to
    itself, never to `sqlalchemy.*` — so the DB write inside `_flush()`
    has no path back into `emit()`.

    `emit()` does no I/O: it appends a plain dict to an in-memory list
    behind a lock and, at most, arms a one-shot timer on the currently
    running event loop. The actual write is a batched, best-effort
    `_flush()` a few seconds later. Either half failing — no running
    loop yet, the DB unreachable, a formatting error on a malformed
    record — is swallowed. A logging call must never be the thing that
    breaks the request that made it.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._lock = threading.Lock()
        self._buffer: list[dict] = []
        self._flush_armed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = "ERROR" if record.levelno >= logging.ERROR else "WARN"
            stack = _format_stack(record)
            entry = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "source": "server",
                "level": level,
                "tag": record.name[:128],
                "message": record.getMessage()[:_MAX_MESSAGE_CHARS],
                "stack": stack,
            }
        except Exception:  # noqa: BLE001 — formatting must never break the caller
            return

        arm = False
        with self._lock:
            if len(self._buffer) >= _MAX_QUEUED:
                # Best-effort: drop rather than grow unbounded or block the
                # caller. WARNING+ from a handful of loggers should never
                # get near this in practice (see the module docstring).
                return
            self._buffer.append(entry)
            if not self._flush_armed:
                self._flush_armed = True
                arm = True
        if arm:
            self._arm_flush()

    def _arm_flush(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop right now (e.g. a warning logged before the
            # app's event loop starts). Leave the entry buffered — the
            # next emit() that DOES land on a running loop will arm the
            # flush and pick it up too.
            with self._lock:
                self._flush_armed = False
            return
        loop.call_later(_FLUSH_AFTER_S, self._fire, loop)

    def _fire(self, loop: asyncio.AbstractEventLoop) -> None:
        loop.create_task(self._flush())

    async def _flush(self) -> None:
        with self._lock:
            batch, self._buffer = self._buffer, []
            self._flush_armed = False
        if not batch:
            return
        try:
            from .db import models
            from .db.session import SessionLocal
            now = datetime.now(timezone.utc)
            async with SessionLocal() as db:
                db.add_all(models.AppLog(received_at=now, **e) for e in batch)
                await db.commit()
        except Exception:  # noqa: BLE001
            # Best-effort: a DB hiccup here must never surface as a second
            # failure on top of whatever was originally being logged, and
            # must not re-enter logging (see class docstring on attachment).
            pass


def _install_server_log_handler() -> None:
    """Attach one `_ServerLogHandler` to the allowlisted loggers plus
    `uvicorn.error`. Idempotent, same replace-not-append pattern as the
    stdout handler above, for the same reload-safety reason."""
    handler = _ServerLogHandler()
    for name in (*_SERVER_LOG_SOURCES, _UVICORN_ERROR_LOGGER):
        target = logging.getLogger(name)
        for existing in list(target.handlers):
            if isinstance(existing, _ServerLogHandler):
                target.removeHandler(existing)
        target.addHandler(handler)


def configure_logging(level: str = "INFO") -> None:
    """Send `myvitals.*` logs to stdout at `level`. Idempotent.

    Attaches to the root logger rather than to `myvitals` specifically, so
    anything the app imports is covered too. uvicorn installs its own
    handlers with `propagate=False`, so its access log is untouched and
    nothing is emitted twice.
    """
    global _configured
    if _configured:
        return

    resolved = getattr(logging, str(level).upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))

    root = logging.getLogger()
    # Replace rather than append: a reload in development would otherwise
    # stack handlers and print every line several times.
    for existing in list(root.handlers):
        if getattr(existing, "_myvitals", False):
            root.removeHandler(existing)
    handler._myvitals = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(resolved)

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)

    _install_server_log_handler()

    _configured = True
    logging.getLogger(__name__).info("logging configured at %s", logging.getLevelName(resolved))
