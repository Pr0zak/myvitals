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


async def seed_foods(db: AsyncSession, *, force: bool = False) -> int:
    """Upsert the bundled catalog. Returns the number of rows written.

    With `force=False` (the default) the work is skipped entirely when the
    table already holds at least as many USDA rows as the catalog carries.
    That check is what makes this safe to call on every startup: the common
    case costs one COUNT, not 14 round trips.
    """
    rows = catalog()
    if not rows:
        log.warning("food catalog is empty; nothing to seed")
        return 0

    if not force:
        have = (await db.execute(
            select(func.count()).select_from(models.Food)
            .where(models.Food.source == "usda")
        )).scalar_one()
        if have >= len(rows):
            log.debug("food catalog already seeded (%d rows); skipping", have)
            return 0

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
