"""The app must actually emit its own logs.

It did not. There was no `basicConfig`, `dictConfig` or `setLevel` anywhere
in the codebase, and `fastapi run` configures only the `uvicorn.*` loggers —
so the root logger sat at Python's default of WARNING and all 51 `log.info`
call sites wrote into a void.

The failure mode is nasty precisely because nothing breaks. Sync results,
scheduled job outcomes and ingest counts simply never appear, so the natural
reading when a scheduled job seems not to have run is that it did not run.
Answering "did the poll work?" meant re-running the work by hand to watch it
happen.

`Settings.log_level` existed the whole time and was never read.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from myvitals.config import settings
from myvitals.logging_config import (
    _NOISY,
    _SERVER_LOG_SOURCES,
    _UVICORN_ERROR_LOGGER,
    _ServerLogHandler,
    configure_logging,
)


def test_the_setting_is_actually_consumed():
    """log_level was declared and unread — the "declared but unconsumed"
    pattern this codebase has been bitten by elsewhere."""
    import inspect

    from myvitals import main

    src = inspect.getsource(main)
    assert "configure_logging(settings.log_level)" in src


def test_app_loggers_emit_at_info(caplog):
    configure_logging("INFO")
    with caplog.at_level(logging.INFO, logger="myvitals.test"):
        logging.getLogger("myvitals.test").info("hello")
    assert any("hello" in r.message for r in caplog.records)


def test_root_level_is_low_enough_for_app_info():
    """The specific defect: root at WARNING silently discards every
    log.info in the application."""
    configure_logging("INFO")
    assert logging.getLogger().level <= logging.INFO


def test_a_handler_is_attached():
    configure_logging("INFO")
    assert logging.getLogger().handlers, "nothing would reach the container output"


def test_noisy_third_party_loggers_are_pinned_lower():
    """httpx emits an INFO line per request, which on a Google Health sync
    is one line per page of results. At that volume the app's own messages
    are lost, which is the same failure as not logging them."""
    configure_logging("INFO")
    for name in _NOISY:
        assert logging.getLogger(name).level >= logging.WARNING, name


def test_repeated_configuration_does_not_stack_handlers():
    """A reload would otherwise print every line several times."""
    configure_logging("INFO")
    before = len(logging.getLogger().handlers)
    for _ in range(3):
        configure_logging("INFO")
    assert len(logging.getLogger().handlers) == before


def test_an_unparseable_level_falls_back_rather_than_crashing():
    """A typo in the environment must not take the app down at import."""
    import myvitals.logging_config as lc

    lc._configured = False
    configure_logging("NOT_A_LEVEL")
    assert logging.getLogger().level == logging.INFO


def test_the_default_setting_is_info():
    assert str(settings.log_level).upper() == "INFO"


# ─── SA-O6: backend WARNING+ reaching app_logs as source="server" ──────────
#
# `app_logs` / the Logs page / GET /debug/logs already existed for
# `source in (phone, server)`. No code path had ever written a `server`
# row, so that filter always returned nothing and every backend failure
# was visible only via `docker compose logs` — capped and wiped on the
# next deploy. These tests pin the handler that fixes that, and — just as
# importantly — pin what it must NEVER pick up.


def _reconfigure():
    """Force a clean pass through configure_logging(), including the
    server-handler install step (which the `_configured` early-return
    would otherwise skip on a second call)."""
    import myvitals.logging_config as lc

    lc._configured = False
    configure_logging("INFO")


def _handler_on(logger_name: str) -> _ServerLogHandler | None:
    for h in logging.getLogger(logger_name).handlers:
        if isinstance(h, _ServerLogHandler):
            return h
    return None


def test_server_handler_is_wired_on_every_allowlisted_logger():
    _reconfigure()
    for name in (*_SERVER_LOG_SOURCES, _UVICORN_ERROR_LOGGER):
        assert _handler_on(name) is not None, f"{name} has no server-log handler"


def test_server_handler_is_not_on_root():
    """Attached per-logger, not via root — see the module docstring on why
    root alone would miss uvicorn.error's ASGI-exception records anyway."""
    _reconfigure()
    assert _handler_on("root") is None
    assert not any(isinstance(h, _ServerLogHandler) for h in logging.getLogger().handlers)


def test_server_handler_does_not_watch_its_own_logger():
    """A DB failure inside _flush() must not be able to re-enter emit()."""
    _reconfigure()
    assert _handler_on("myvitals.logging_config") is None


def test_analytics_jobs_is_never_wired():
    """analytics/jobs.py's alert warnings interpolate the actual reading
    that tripped them straight into the message — resting heart rate, a
    blood-pressure average, a weight delta in kg, a skin-temperature
    delta. Piping that into a table a UI renders would be the exact leak
    this app's privacy posture exists to prevent, and those alerts are
    already structured rows in `alerts`, so nothing is lost by leaving it
    out. This is a deliberate exclusion, not an oversight — pin it so a
    future "just widen the allowlist" edit has to consciously remove this
    test rather than silently reintroduce the leak."""
    assert "myvitals.analytics.jobs" not in _SERVER_LOG_SOURCES
    assert _handler_on("myvitals.analytics.jobs") is None


def test_importer_and_ingest_loggers_are_never_wired():
    """A parse-failure exception can echo the offending field back in its
    message — concretely, the Sober CSV importer's real-name-in-
    `addiction`-column gotcha this repo already knows about (CLAUDE.md).
    None of the modules that parse external/user-supplied payloads are on
    the allowlist."""
    excluded = (
        "myvitals.api.imports",
        "myvitals.api.ingest",
        "myvitals.integrations.imports",
        "myvitals.integrations.fit_tracks",
        "myvitals.api.strava",
        "myvitals.integrations.strava_web",
        "myvitals.api.google_health",
        "myvitals.integrations.google_health",
    )
    for name in excluded:
        assert name not in _SERVER_LOG_SOURCES, name
        assert _handler_on(name) is None, name


def test_repeated_configuration_does_not_stack_the_server_handler():
    """Same reload-safety property as the stdout handler above."""
    _reconfigure()
    before = len(logging.getLogger(_UVICORN_ERROR_LOGGER).handlers)
    for _ in range(3):
        _reconfigure()
    assert len(logging.getLogger(_UVICORN_ERROR_LOGGER).handlers) == before


def _make_record(
    name: str = "myvitals.tasks.scheduled",
    level: int = logging.WARNING,
    msg: str = "trail poll failed: %s",
    args: tuple = ("boom",),
    exc_info=None,
) -> logging.LogRecord:
    return logging.getLogger(name).makeRecord(
        name, level, "test.py", 1, msg, args, exc_info,
    )


def test_emit_only_buffers_warning_and_above():
    """DEBUG/INFO stay stdout-only — the point is failures, not a second
    copy of the access log, and the phone side of this table is already
    unbounded (SA-C3). The level gate is enforced by the logging module's
    own dispatch (Logger.callHandlers checks `record.levelno >=
    handler.level` before ever calling emit()), so this goes through a
    real logger rather than calling handler.emit()/.handle() directly,
    which would bypass that gate."""
    handler = _ServerLogHandler()
    assert handler.level == logging.WARNING

    logger = logging.getLogger("myvitals.tasks.scheduled")
    logger.addHandler(handler)
    try:
        logger.info("fyi, nothing wrong")
    finally:
        logger.removeHandler(handler)
    assert handler._buffer == []


def test_emit_resolves_percent_args_into_a_plain_message():
    handler = _ServerLogHandler()
    handler.emit(_make_record(msg="Google Health poll failed: %s", args=("401",)))
    assert handler._buffer[0]["message"] == "Google Health poll failed: 401"
    assert handler._buffer[0]["source"] == "server"
    assert handler._buffer[0]["tag"] == "myvitals.tasks.scheduled"


@pytest.mark.parametrize(
    ("levelno", "expected"),
    [(logging.WARNING, "WARN"), (logging.ERROR, "ERROR"), (logging.CRITICAL, "ERROR")],
)
def test_level_bucket_matches_the_apps_log_vocabulary(levelno, expected):
    """AppLog / GET /debug/logs speak VERBOSE|DEBUG|INFO|WARN|ERROR, not
    Python's WARNING/CRITICAL — a stored "CRITICAL" would silently fall
    outside `order[min_idx:]` in list_logs() and vanish from every
    WARN-or-above / ERROR-or-above filter."""
    handler = _ServerLogHandler()
    handler.emit(_make_record(level=levelno, msg="x", args=()))
    assert handler._buffer[0]["level"] == expected


def test_emit_captures_a_traceback_into_stack_when_exc_info_is_set():
    handler = _ServerLogHandler()
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys
        handler.emit(_make_record(msg="HA event handling failed: %s",
                                   args=("kaboom",), exc_info=sys.exc_info()))
    stack = handler._buffer[0]["stack"]
    assert stack is not None and "ValueError: kaboom" in stack


def test_emit_truncates_an_overlong_message_and_stack():
    handler = _ServerLogHandler()
    huge = "x" * 10_000
    try:
        raise ValueError(huge)
    except ValueError:
        import sys
        handler.emit(_make_record(msg="%s", args=(huge,), exc_info=sys.exc_info()))
    entry = handler._buffer[0]
    assert len(entry["message"]) <= 2000
    assert len(entry["stack"]) <= 4000


# ─── SA-C13: uvicorn.error's stack must not carry the exception message ───
#
# uvicorn.error is a content-unfiltered catch-all for any unhandled
# exception (unlike the allowlisted myvitals.* loggers above, whose call
# sites were read end to end). A Pydantic ValidationError or a SQLAlchemy
# IntegrityError quotes the offending value into str(exc), and
# traceback.format_exception's last line IS that string — so the fix is
# scoped to this one logger, not the allowlisted ones.


def test_uvicorn_error_stack_drops_the_exception_message():
    """Mirrors how Pydantic/SQLAlchemy actually build these messages: the
    value is interpolated into the exception's message AT RUNTIME (an
    f-string), so the raise site's SOURCE line names the variable, never
    the value — exactly what traceback.format_tb renders. Hard-coding the
    number as a source literal would test something that can't happen for
    a real ValidationError/IntegrityError."""
    handler = _ServerLogHandler()
    weight_kg = 172.5
    try:
        raise ValueError(f"weight_kg={weight_kg} violates check constraint")
    except ValueError:
        import sys
        handler.emit(_make_record(
            name="uvicorn.error", msg="Exception in ASGI application\n",
            args=(), exc_info=sys.exc_info(),
        ))
    stack = handler._buffer[0]["stack"]
    assert stack is not None
    assert "172.5" not in stack  # the value — what was in it — is gone
    assert "ValueError" in stack  # the type name is kept — it's not the payload


def test_uvicorn_error_stack_keeps_the_frames():
    """The type name alone isn't enough to debug from — the frames (where
    it broke) must survive even though the message (what was in it) does
    not."""
    handler = _ServerLogHandler()
    try:
        raise RuntimeError("some sensitive detail")
    except RuntimeError:
        import sys
        handler.emit(_make_record(
            name="uvicorn.error", msg="Exception in ASGI application\n",
            args=(), exc_info=sys.exc_info(),
        ))
    stack = handler._buffer[0]["stack"]
    assert "test_logging_config.py" in stack
    assert "Traceback" in stack


def test_allowlisted_logger_stack_is_unaffected_by_the_uvicorn_fix():
    """Only uvicorn.error changes — the allowlisted loggers keep the full
    traceback text, since SA-O6 already confirmed their call sites never
    raise with a value-carrying message."""
    handler = _ServerLogHandler()
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys
        handler.emit(_make_record(
            name="myvitals.tasks.scheduled", msg="trail poll failed: %s",
            args=("boom",), exc_info=sys.exc_info(),
        ))
    stack = handler._buffer[0]["stack"]
    assert "ValueError: kaboom" in stack


def test_emit_never_raises_on_a_malformed_record():
    """A logging call must never be the thing that breaks the request
    that made it — including when the call site itself has a bug (too
    few %-args for its own format string)."""
    handler = _ServerLogHandler()
    bad = _make_record(msg="bad %s %s", args=("only-one",))
    handler.emit(bad)  # must not raise
    assert handler._buffer == []


def test_the_buffer_is_bounded():
    """Best-effort: drop rather than grow unbounded or block the caller.
    A separate finding (SA-C3) already covers the phone side of this
    table having no retention at all — this must not add a second one."""
    import myvitals.logging_config as lc

    handler = _ServerLogHandler()
    for i in range(lc._MAX_QUEUED + 50):
        handler.emit(_make_record(msg="filler %d", args=(i,)))
    assert len(handler._buffer) == lc._MAX_QUEUED


async def test_flush_persists_the_batch_with_source_server(monkeypatch):
    captured: list = []

    class _FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add_all(self, items):
            captured.extend(list(items))

        async def commit(self):
            pass

    monkeypatch.setattr(
        "myvitals.db.session.SessionLocal", lambda: _FakeDB(), raising=True,
    )

    handler = _ServerLogHandler()
    handler.emit(_make_record(msg="Concept2 poll failed: %s", args=("timeout",)))
    await handler._flush()

    assert handler._buffer == []
    assert len(captured) == 1
    row = captured[0]
    assert row.source == "server"
    assert row.level == "WARN"
    assert row.message == "Concept2 poll failed: timeout"


async def test_flush_is_a_noop_on_an_empty_buffer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "myvitals.db.session.SessionLocal",
        lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError("should not be called")),
        raising=True,
    )
    handler = _ServerLogHandler()
    await handler._flush()  # nothing buffered — must not touch the DB
    assert calls == []


async def test_flush_swallows_a_db_failure():
    """A DB hiccup while flushing must not surface as a second failure on
    top of whatever was originally being logged."""
    class _ExplodingSessionLocal:
        def __call__(self):
            raise RuntimeError("db unreachable")

    import myvitals.db.session as dbsession
    orig = dbsession.SessionLocal
    dbsession.SessionLocal = _ExplodingSessionLocal()
    try:
        handler = _ServerLogHandler()
        handler.emit(_make_record())
        await handler._flush()  # must not raise
    finally:
        dbsession.SessionLocal = orig
    assert handler._buffer == []


async def test_emit_arms_a_debounced_flush_on_the_running_loop(monkeypatch):
    """emit() itself does no I/O — it schedules a flush a few seconds out
    on whatever loop is currently running, rather than blocking or
    flushing per-record."""
    import myvitals.logging_config as lc

    monkeypatch.setattr(lc, "_FLUSH_AFTER_S", 0.05)
    captured: list = []

    class _FakeDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add_all(self, items):
            captured.extend(list(items))

        async def commit(self):
            pass

    monkeypatch.setattr(
        "myvitals.db.session.SessionLocal", lambda: _FakeDB(), raising=True,
    )

    handler = _ServerLogHandler()
    handler.emit(_make_record(msg="trail poll failed: %s", args=("dns",)))
    assert captured == []  # not flushed synchronously
    await asyncio.sleep(0.2)
    assert len(captured) == 1


def test_emit_without_a_running_loop_buffers_but_does_not_raise():
    """A warning logged before the app's event loop starts (or in a sync
    test) must not crash — it just waits in the buffer for the next
    emit() that lands on a running loop."""
    handler = _ServerLogHandler()
    handler.emit(_make_record())  # no running loop in this sync test
    assert len(handler._buffer) == 1
    assert handler._flush_armed is False
