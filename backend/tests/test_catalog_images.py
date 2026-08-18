"""A catalog row must not illustrate itself with another exercise's photo.

Fifty rows pointed `image_front` / `image_side` at a different exercise's
image directory while their own purpose-made artwork sat unreferenced in
`data/img/`. Some of those borrowings were harmless near-synonyms; others
were actively misleading — `Dumbbell_Hip_Thrust` showed a photograph of a
barbell hip thrust to a user whose whole equipment profile is dumbbells, and
`Decline_Push_Up` borrowed a row whose own instructions describe a flat wide
push-up rather than a decline.

The rule applied: a row's own asset wins. It was drawn or pulled for that
exercise specifically, and both clients already render a `.png` as a tinted
icon and a `.jpg` as a photo, so an icon is a first-class result rather than
a fallback.
"""

from __future__ import annotations

import json
import pathlib

DATA = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "myvitals" / "data"
)
IMG = DATA / "img"


def _rows() -> list[dict]:
    rows: list[dict] = []
    for name in ("exercises.json", "exercises_supplement.json"):
        rows += json.loads((DATA / name).read_text())
    return rows


def _dir_of(path: str | None) -> str | None:
    if not path:
        return None
    parts = path.strip("/").split("/")
    return parts[-2] if len(parts) >= 2 else None


def test_no_row_borrows_art_when_it_has_its_own():
    """The specific defect. A row with its own directory must use it."""
    offenders = []
    for row in _rows():
        slug = row["id"]
        own = IMG / slug
        if not own.is_dir() or not any(own.iterdir()):
            continue
        for field in ("image_front", "image_side"):
            borrowed_from = _dir_of(row.get(field))
            if borrowed_from and borrowed_from != slug:
                offenders.append(f"{slug}.{field} -> {borrowed_from}")
    assert not offenders, (
        "these rows illustrate themselves with another exercise's image while "
        "their own art exists:\n  " + "\n  ".join(offenders)
    )


def test_front_and_side_never_come_from_different_exercises():
    """A side view of a different movement is worse than no side view, so
    when only one frame exists the side is nulled rather than borrowed."""
    offenders = []
    for row in _rows():
        front, side = _dir_of(row.get("image_front")), _dir_of(row.get("image_side"))
        if front and side and front != side:
            offenders.append(f"{row['id']}: front={front} side={side}")
    assert not offenders, (
        "front and side frames from different exercises:\n  " + "\n  ".join(offenders)
    )


def test_every_referenced_image_exists_on_disk():
    """A path that 404s renders as a broken tile on both surfaces."""
    missing = []
    for row in _rows():
        for field in ("image_front", "image_side"):
            path = row.get(field)
            if not path:
                continue
            rel = path.replace("/exercises/img/", "", 1).strip("/")
            if not (IMG / rel).is_file():
                missing.append(f"{row['id']}.{field} -> {path}")
    assert not missing, "referenced images not present:\n  " + "\n  ".join(missing)


def test_rows_with_art_actually_reference_it():
    """Art shipped in the repo and referenced by nothing is dead weight in
    the image — 45 correct icons were in exactly that state."""
    unreferenced = []
    referenced = {
        _dir_of(row.get(field))
        for row in _rows()
        for field in ("image_front", "image_side")
    }
    known = {row["id"] for row in _rows()}
    for d in IMG.iterdir():
        if not d.is_dir() or d.name == "muscle":
            continue
        if d.name in known and d.name not in referenced:
            unreferenced.append(d.name)
    assert not unreferenced, (
        "these exercises ship artwork that no catalog row points at:\n  "
        + "\n  ".join(sorted(unreferenced))
    )
