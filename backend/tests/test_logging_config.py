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

import logging

from myvitals.config import settings
from myvitals.logging_config import _NOISY, configure_logging


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
