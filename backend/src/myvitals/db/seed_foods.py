"""Load the bundled USDA food catalog into the `foods` table (MEAL-1).

Runs once on startup, and is cheap to re-run: the whole thing is an
idempotent upsert keyed on `slug`, so a restart with an unchanged catalog
touches nothing, and a refreshed catalog updates rows in place.

Two properties this must preserve:

**User rows are never touched.** The upsert only fires on rows whose
`source` is still "usda". If someone corrects a bundled food's nutrition,
that edit flips `source` to "user" and the next seed leaves it alone —
otherwise every restart would silently revert their correction.

**Deleted foods stay deleted.** Nothing here removes rows that are absent
from the catalog. A recipe or pantry item may point at one, and USDA
reworking a description between releases is not a reason to orphan a
user's recipe line.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.foods import NUTRIENT_COLUMNS, catalog
from . import models

log = logging.getLogger(__name__)

#: Rows per INSERT statement.
#:
#: asyncpg refuses a statement with more than 32,767 bind parameters, and
#: a multi-row INSERT binds one per column per row. At 13 columns the hard
#: ceiling is 2,520 rows, against a catalog of ~7,000 — so a single
#: statement does not merely risk the limit, it exceeds it by 3x. This
#: session has hit that ceiling twice already in other code paths. 500
#: leaves a wide margin and keeps each statement small enough that a
#: failure is cheap to retry.
CHUNK = 500

_COLUMNS = ("slug", "name", "category", *NUTRIENT_COLUMNS, "unit_grams")


async def _needs_reseed(db: AsyncSession, rows: list[dict]) -> str | None:
    """Decide whether the stored catalog is behind the bundled one.

    Returns a human-readable reason, or None when the DB is up to date.

    Row count alone is NOT sufficient, and assuming it was shipped a bug:
    v0.16.0 added four vitamin columns without changing the row count, so
    the count-only guard short-circuited, the seed never ran, and every
    new column stayed NULL in production while the tables looked fine.

    So this also asks, per nutrient column, "the bundled catalog has
    values for this — does the database?". A column that is entirely null
    in the DB while the file has data for it means the stored rows predate
    that column. One aggregate query over ~10k rows, run once at startup.
    """
    have = (await db.execute(
        select(func.count()).select_from(models.Food)
        .where(models.Food.source == "usda")
    )).scalar_one()
    if have < len(rows):
        return f"{have} stored rows against {len(rows)} in the bundled catalog"

    # Which columns does the FILE actually supply? A column the catalog
    # has no data for cannot be used as evidence of staleness.
    supplied = {
        c for c in NUTRIENT_COLUMNS
        if any(r.get(c) is not None for r in rows)
    }
    if not supplied:
        return None

    counts = (await db.execute(
        select(*[
            func.count(getattr(models.Food, c)) for c in sorted(supplied)
        ]).select_from(models.Food)
        .where(models.Food.source == "usda")
    )).one()
    empty = [
        c for c, n in zip(sorted(supplied), counts) if not n
    ]
    if empty:
        return f"columns present in the catalog but empty in the database: {', '.join(empty)}"
    return None


async def seed_foods(db: AsyncSession, *, force: bool = False) -> int:
    """Upsert the bundled catalog. Returns the number of rows written.

    With `force=False` (the default) the work is skipped when the stored
    catalog already matches the bundled one — see `_needs_reseed` for what
    "matches" means, and why a row count on its own is not enough.
    """
    rows = catalog()
    if not rows:
        log.warning("food catalog is empty; nothing to seed")
        return 0

    if not force:
        reason = await _needs_reseed(db, rows)
        if reason is None:
            log.debug("food catalog already up to date; skipping seed")
            return 0
        log.info("re-seeding food catalog: %s", reason)

    written = 0
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        values = [
            {
                "slug": r["slug"],
                "name": r["name"],
                "source": "usda",
                "category": r.get("category"),
                **{c: r.get(c) for c in NUTRIENT_COLUMNS},
                "unit_grams": r.get("unit_grams"),
            }
            for r in chunk
        ]
        stmt = pg_insert(models.Food).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[models.Food.slug],
            set_={c: getattr(stmt.excluded, c) for c in _COLUMNS},
            # Only bundled rows are refreshed. A row the user has taken
            # ownership of keeps their values.
            where=models.Food.source == "usda",
        )
        await db.execute(stmt)
        written += len(chunk)

    await db.commit()
    log.info("food catalog seeded: %d rows", written)
    return written
