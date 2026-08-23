"""Every `models.X.attr` in the source names a column that exists.

This file exists because of a specific failure that reached production:
`build_prep_plan_payload` referenced `models.FoodLogEntry.eaten_on`. The
column is `day`. Nothing caught it — the module imports fine, because
SQLAlchemy attributes are resolved at attribute-access time, and the only
tests over that code path are static ones that never build the query.

It surfaced as a bare 500 the first time a real user pressed the button,
with the actual cause thirty lines deep in a starlette traceback.

The check is deliberately cheap and total: walk the AST of every source
file for `models.<Class>.<attr>`, and assert the attribute resolves on
the mapped class. It runs in well under a second and covers every query
in the app, not just the ones a test happens to execute.

Attribute-name typos in an ORM query are the archetypal bug that unit
tests miss and production finds, because the code is correct Python
right up to the moment it runs.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from myvitals.db import models

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"

#: Names on the `models` module that are not mapped classes — enums,
#: constants, imported helpers. Referencing an attribute on one of these
#: is not the pattern being checked.
_SKIP_NON_CLASS = True


def _model_refs(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """Find `models.<Class>.<attr>` in one file.

    Only the two-level form is interesting. `models.Food` alone is a
    class reference, and `models.Food.name.ilike(...)` nests deeper but
    its base is still the two-level form, which is what gets checked.
    """
    tree = ast.parse(path.read_text())
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        inner = node.value
        if not isinstance(inner, ast.Attribute):
            continue
        base = inner.value
        if not (isinstance(base, ast.Name) and base.id == "models"):
            continue
        out.append((node.lineno, inner.attr, node.attr))
    return out


def _sources() -> list[pathlib.Path]:
    return sorted(
        p for p in SRC.rglob("*.py")
        if "alembic" not in p.parts and p.name != "models.py"
    )


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_every_model_attribute_reference_resolves(path: pathlib.Path):
    bad: list[str] = []
    for lineno, cls_name, attr in _model_refs(path):
        cls = getattr(models, cls_name, None)
        if cls is None or not isinstance(cls, type):
            # Not a mapped class — an enum or constant reached through
            # the same module. Out of scope rather than a failure.
            continue
        if not hasattr(cls, attr):
            rel = path.relative_to(SRC.parent.parent)
            bad.append(f"{rel}:{lineno} — {cls_name} has no attribute '{attr}'")
    assert not bad, "\n".join(bad)


def test_the_check_actually_finds_something():
    """A guard that would pass on an empty result set is not a guard.

    If a refactor renames the `models` import or changes the access
    pattern, this file would silently start checking nothing.
    """
    total = sum(len(_model_refs(p)) for p in _sources())
    assert total > 300, f"only found {total} model attribute references"


def test_the_regression_that_prompted_this_file():
    """`FoodLogEntry.day`, not `eaten_on`. Named explicitly so a rename
    of the column has to come past this test."""
    assert hasattr(models.FoodLogEntry, "day")
    assert not hasattr(models.FoodLogEntry, "eaten_on")
