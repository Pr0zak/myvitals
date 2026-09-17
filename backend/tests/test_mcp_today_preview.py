"""The forward-looking MCP tools, and the write they must not perform (OG3-B1).

All eight original tools are retrospective: what happened, how much, how
consistently. None could answer "what am I lifting today, and at what
weight" — which, for someone who trains at home from a phone with a Claude
session open, is the question asked most often.

The hazard in adding it is specific and easy to miss. The endpoint behind
today's plan, `get_today`, GENERATES and persists a workout when none exists
yet. Reusing it wholesale would make a read-only tool the thing that decides
today's session happened — a model asking a question would silently commit a
row, and the daily plan would depend on whether anyone had chatted about it.
So `preview_today_workout` reads the existing row and otherwise says plainly
that nothing is planned.

`test_mcp_server.py` already asserts no tool NAME suggests mutation. That is
a guard on naming; this is a guard on behaviour.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from myvitals.integrations import mcp_tools


def _body_source(fn) -> str:
    """A function's source with its docstring removed.

    These assertions grep for names that must not be CALLED. The docstrings
    here discuss those same names at length — explaining why they are
    forbidden is the point — so a naive grep over the whole source fails on
    its own explanation.
    """
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    fn_node = tree.body[0]
    body = fn_node.body
    if (
        body and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


class TestBothToolsAreRegistered:
    def test_preview_and_records_are_present(self):
        assert "preview_today_workout" in mcp_tools.TOOLS
        assert "get_exercise_records" in mcp_tools.TOOLS

    def test_they_advertise_read_only(self):
        listed = {t["name"]: t for t in mcp_tools.tool_list()}
        for name in ("preview_today_workout", "get_exercise_records"):
            ann = listed[name]["annotations"]
            assert ann["readOnlyHint"] is True
            assert ann["destructiveHint"] is False

    def test_they_take_no_arguments(self):
        """Neither is windowed, so neither should invent a `days` knob."""
        for name in ("preview_today_workout", "get_exercise_records"):
            schema = mcp_tools.TOOLS[name][1]
            assert schema["properties"] == {}
            assert schema["additionalProperties"] is False


class TestThePreviewNeverGenerates:
    def test_it_does_not_reach_the_generating_path(self):
        """Reading the source, because the write is what must not happen.

        `get_today`, `generate_plan` and `persist_plan` are the three names
        on the path that creates a workout. A preview that touches any of
        them has stopped being a preview.
        """
        src = _body_source(mcp_tools._today_workout)
        for forbidden in ("get_today", "generate_plan", "persist_plan"):
            assert forbidden not in src, (
                f"preview_today_workout calls {forbidden}, which writes a "
                "workout row. Asking what today looks like must not be the "
                "thing that decides today happened."
            )

    def test_it_reads_the_existing_row_and_hydrates_it(self):
        """And it must reuse the app's own hydration, not a second copy.

        The prescription a model reads has to be the prescription both
        clients render; a parallel assembly here is how a tool starts
        quoting weights the app never offered.
        """
        src = _body_source(mcp_tools._today_workout)
        assert "_existing_workout_for" in src
        assert "_hydrate_workout" in src

    def test_the_absent_case_is_stated_not_faked(self):
        # `ast.unparse` normalises string quoting, so accept either form
        # rather than pinning the test to its output style.
        src = _body_source(mcp_tools._today_workout)
        assert ("'planned': False" in src or '"planned": False' in src), (
            "with no plan the tool must say so explicitly rather than "
            "returning an empty shape a model would read as a rest day"
        )


class TestRecordsReusesTheEndpoint:
    def test_it_delegates_rather_than_reimplementing(self):
        """PR-1b's five PR kinds must not be re-derived here.

        A single scalar best cannot represent a bodyweight hold, which is
        why `/records` reports five kinds. A second implementation in this
        module would lose that distinction again, quietly, for the one
        caller least able to notice.
        """
        src = _body_source(mcp_tools._exercise_records)
        assert "strength_records" in src
        assert "select(" not in src, (
            "this tool should delegate to /records, not run its own query"
        )
