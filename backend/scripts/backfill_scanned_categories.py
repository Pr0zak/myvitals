"""Give already-scanned foods the category their barcode can supply.

`POST /meals/foods` stored no category until now, so every product added
by a barcode scan landed in the pantry's "Other" section — twelve of one
user's fifteen uncategorised rows were scans. New scans carry a category
from the lookup; these were saved before that and can only get one by
asking Open Food Facts again.

Idempotent and conservative: only rows that already have a barcode AND
no category are touched, and a lookup that fails or returns nothing
leaves the row exactly as it was. Run it as often as you like.

    docker compose exec -T backend python \\
        /app/scripts/backfill_scanned_categories.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from myvitals.db import models
from myvitals.db.session import SessionLocal
from myvitals.integrations import openfoodfacts

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill")


async def main() -> None:
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(models.Food)
            .where(models.Food.barcode.isnot(None))
            .where(models.Food.category.is_(None)),
        )).scalars().all()
        log.info("%d scanned food(s) without a category", len(rows))

        filled = 0
        for f in rows:
            try:
                hit = await openfoodfacts.lookup(f.barcode or "")
            except openfoodfacts.BarcodeLookupError as e:
                log.warning("  %s — lookup failed: %s", f.name[:40], e)
                continue
            cat = (hit or {}).get("category")
            if not cat:
                log.info("  %s — no category published", f.name[:40])
                continue
            f.category = cat
            filled += 1
            log.info("  %s -> %s", f.name[:40], cat)
            # A free service, asked politely.
            await asyncio.sleep(0.4)

        if filled:
            await db.commit()
        log.info("filled %d", filled)


if __name__ == "__main__":
    asyncio.run(main())
