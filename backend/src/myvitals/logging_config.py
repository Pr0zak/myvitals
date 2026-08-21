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
"""

from __future__ import annotations

import logging
import sys

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

_configured = False


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

    _configured = True
    logging.getLogger(__name__).info("logging configured at %s", logging.getLevelName(resolved))
