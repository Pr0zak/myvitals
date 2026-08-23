"""Every ORM insert must supply its non-null timestamps.

A food created through the API returned a 500:

    null value in column "created_at" of relation "foods"
    violates not-null constraint

The column has `server_default now()` in migration 0056, and the SEEDER
worked fine because `pg_insert` omits the column entirely and lets the
table default fire. But SQLAlchemy does not read the database schema —
when the model does not declare `server_default`, the ORM treats the
column as one it must supply and sends an explicit NULL.

So the failure only appeared on the ORM path, which no test exercised:
MEAL-1 verification covered recipes and pantry items, both of which set
their timestamps, and never created a food.

This module is the static guard. It reads every `models.X(...)`
construction in the API layer and checks that each non-null timestamp
column is either passed explicitly or defaulted on the model. It cannot
catch everything a real database would, but it catches exactly this.
"""
from __future__ import annotations

import ast
import pathlib

import sqlalchemy as sa

from myvitals.db import models

API = pathlib.Path(models.__file__).resolve().parent.parent / "api"


def _required_timestamps(cls) -> set[str]:
    """Non-null DateTime columns with no default of any kind.

    A column with a Python default or a model-declared `server_default`
    is safe: SQLAlchemy either fills it or knows to omit it.
    """
    out = set()
    for col in cls.__table__.columns:
        if col.nullable or col.primary_key:
            continue
        if not isinstance(col.type, sa.DateTime):
            continue
        if col.default is not None or col.server_default is not None:
            continue
        out.add(col.name)
    return out


def _model_classes() -> dict[str, type]:
    return {
        name: obj for name, obj in vars(models).items()
        if isinstance(obj, type) and hasattr(obj, "__table__")
    }


def test_every_orm_insert_supplies_its_required_timestamps():
    classes = _model_classes()
    offenders: list[str] = []

    for path in sorted(API.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # models.Food(...) — the only construction form used here.
            fn = node.func
            if not (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "models"):
                continue
            cls = classes.get(fn.attr)
            if cls is None:
                continue
            needed = _required_timestamps(cls)
            if not needed:
                continue
            passed = {kw.arg for kw in node.keywords if kw.arg}
            missing = needed - passed
            if missing:
                offenders.append(
                    f"{path.name}:{node.lineno} models.{fn.attr}(...) "
                    f"omits {', '.join(sorted(missing))}"
                )

    assert offenders == [], (
        "these ORM inserts send NULL for a non-null timestamp and will "
        "fail at the database:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_can_actually_fail():
    """Guards the guard: if `_required_timestamps` stopped finding
    anything, the test above would pass vacuously for every model."""
    interesting = [
        c for c in _model_classes().values() if _required_timestamps(c)
    ]
    assert interesting, "no model has an unguarded non-null timestamp"


def test_foods_created_at_is_safe_both_ways():
    """The column that caused the 500. Belt and braces: the model now
    declares the server default AND `create_food` passes a value, so it
    works whether or not SQLAlchemy knows what the table does."""
    col = models.Food.__table__.columns["created_at"]
    assert col.server_default is not None, "model must declare it"

    src = (API / "meals.py").read_text()
    fn = src[src.index("async def create_food("):]
    fn = fn[: fn.index("@router.")]
    assert "created_at=" in fn, "create_food must pass it explicitly too"
