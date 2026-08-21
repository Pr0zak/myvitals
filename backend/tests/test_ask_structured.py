"""Structured, cached /ai/ask (ASK-1).

/ai/ask was the last AI surface returning free prose, uncached. Uncached
mattered more than it sounds: it is the one surface the user can fire
repeatedly by hand, so it was the one most able to run up a bill, and it
was the only one with no protection against doing so.
"""

from __future__ import annotations

import inspect

from myvitals.integrations import claude


class TestToolSchema:
    def test_ask_uses_forced_tool_use(self):
        src = inspect.getsource(claude.ask)
        assert "tool_choice" in src, "ask() must force the tool call"
        assert '"name": "give_answer"' in src

    def test_schema_requires_every_rendered_field(self):
        """A client renders these positionally; an absent field is a hole."""
        props = claude.ASK_TOOL["input_schema"]["properties"]
        required = set(claude.ASK_TOOL["input_schema"]["required"])
        assert required == set(props), (
            "every property must be required, or the card renders blanks"
        )
        assert required == {"headline", "answer_bullets", "caveat", "confidence"}

    def test_confidence_is_a_closed_enum(self):
        """Free-text confidence cannot be styled, and would be inconsistent."""
        conf = claude.ASK_TOOL["input_schema"]["properties"]["confidence"]
        assert conf["enum"] == ["high", "medium", "low"]

    def test_caveat_is_required_not_optional(self):
        """The model must actively decide there is no caveat.

        Making it optional lets the model quietly omit the limitations of
        an answer about someone's health, which is the field most worth
        forcing it to think about.
        """
        assert "caveat" in claude.ASK_TOOL["input_schema"]["required"]


class TestSystemPrompt:
    def test_prompt_forbids_inventing_an_answer(self):
        low = claude.ASK_SYSTEM.lower()
        assert "does not support" in low or "doesn't support" in low
        assert "low" in low, "must instruct low confidence on thin data"

    def test_prompt_forbids_diagnosis(self):
        assert "diagnose" in claude.ASK_SYSTEM.lower()


class TestPayloadBounding:
    def test_question_is_inside_the_payload(self):
        """This is what makes the cache correct.

        If the question were passed alongside the payload rather than
        inside it, two different questions against the same data would
        hash identically and the second would get the first's answer.
        """
        src = inspect.getsource(claude.build_ask_payload)
        assert '"question"' in src
        assert "build_summary_payload" in src

    def test_question_is_truncated(self):
        assert claude.MAX_QUESTION_CHARS == 500
        src = inspect.getsource(claude.build_ask_payload)
        assert "MAX_QUESTION_CHARS" in src, (
            "an unbounded question is both a cost lever and an injection surface"
        )


class TestLocalDay:
    def test_no_utc_derived_calendar_days_remain(self):
        """Every payload stamps `today`; it must be the LOCAL today.

        A UTC-derived date rolls at 7pm Central, so for five hours each
        evening the model was told today was tomorrow and every trailing
        window was shifted forward — producing specific, confident, wrong
        statements from correct data. It also changed the cache key twice
        a day, re-billing an unchanged answer.
        """
        src = inspect.getsource(claude)
        assert "datetime.now(timezone.utc).date()" not in src
        # `date.today()` reads the process timezone, which is UTC in the
        # container and the user's own zone on a laptop — so it looks fine
        # in development and is wrong in production.
        assert "date.today()" not in src

    def test_local_today_resolves_through_settings(self):
        src = inspect.getsource(claude._local_today)
        assert "settings.tz" in src


class TestToolResultExtractor:
    def test_returns_empty_dict_when_the_tool_was_not_called(self):
        class _Block:
            type = "text"
            text = "no tool here"

        class _Resp:
            content = [_Block()]

        assert claude._tool_result(_Resp(), "give_answer") == {}

    def test_extracts_the_named_tool_only(self):
        class _Other:
            type = "tool_use"
            name = "give_analysis"
            input = {"a": 1}

        class _Wanted:
            type = "tool_use"
            name = "give_answer"
            input = {"headline": "ok"}

        class _Resp:
            content = [_Other(), _Wanted()]

        assert claude._tool_result(_Resp(), "give_answer") == {"headline": "ok"}

    def test_ask_falls_back_rather_than_raising(self):
        """A missing tool call must not 500 or fabricate.

        tool_choice makes this very unlikely, but "very unlikely" over an
        external API is not "impossible".
        """
        src = inspect.getsource(claude.ask)
        assert "if not analysis:" in src
        assert '"confidence": "low"' in src
