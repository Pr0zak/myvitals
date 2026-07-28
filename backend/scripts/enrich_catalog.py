#!/usr/bin/env python3
"""CAT-1: enrich the bundled exercise catalog with metadata that was dropped
when it was first built from free-exercise-db.

Source: yuhonas/free-exercise-db (dist/exercises.json) — Unlicense / public
domain; the exact lineage myvitals' catalog derives from, so ids join 1:1
(byte-identical, e.g. "3_4_Sit-Up"). The MIT hasaneyldrm/exercises-dataset is
the same data repackaged; we take the public-domain original.

DATA ONLY — no images are pulled (the ~24 MB of free-exercise-db JPGs are
already bundled at /exercises/img/<slug>/{0,1}.jpg).

What it adds/backfills on matching rows (NEVER overwrites existing values):
  - `force`  (push / pull / static)  — absent from every catalog row today
  - `secondary_muscles`              — only when currently EMPTY (98 rows)

Deliberately skipped: `category` (the catalog's movement_pattern is richer),
`instructions`/`mechanic`/`primary_muscle` (already present + possibly edited),
`tips` (not a real free-exercise-db field). The 74 hand-authored supplement
rows aren't in free-exercise-db, so they simply don't match — left untouched.

Idempotent: re-running produces no further change. Usage:
  python backend/scripts/enrich_catalog.py path/to/free-exercise-db.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "src/myvitals/data/exercises.json"


def main(fedb_path: str) -> None:
    fedb = {e["id"]: e for e in json.loads(Path(fedb_path).read_text())}
    rows = json.loads(CATALOG.read_text())

    matched = force_added = secondary_backfilled = 0
    for row in rows:
        src = fedb.get(row["id"])
        if src is None:
            continue
        matched += 1
        # force: add only if not already present with a real value.
        if not row.get("force") and src.get("force"):
            row["force"] = src["force"]
            force_added += 1
        # secondary_muscles: backfill only when currently empty.
        if not row.get("secondary_muscles") and src.get("secondaryMuscles"):
            row["secondary_muscles"] = list(src["secondaryMuscles"])
            secondary_backfilled += 1

    CATALOG.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"catalog rows: {len(rows)} | matched free-exercise-db: {matched}")
    print(f"force added: {force_added} | secondary_muscles backfilled: {secondary_backfilled}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: enrich_catalog.py <free-exercise-db dist/exercises.json>")
    main(sys.argv[1])
