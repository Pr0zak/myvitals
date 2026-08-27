"""Barcode lookup against Open Food Facts.

MEALS_PLAN phase 7, deferred until the typing friction was measurable
rather than predicted. It is measurable: roughly half this diet is
packaged, the food log has been used twice, and every packaged entry
starts by typing a product name into a catalog built from USDA — which
does not carry brands.

Three things about this source shape the code:

**It is crowd-sourced, and the quality varies.** A live probe of Lay's
Classic Potato Chips returned an ingredients list for CHEESE. So a
product from here is never merged into the bundled catalog and never
silently trusted: it lands as `source="openfoodfacts"`, distinct from
`"usda"`, so the app can always say where a number came from. The seed
in `db/seed_foods.py` only ever upserts rows whose source is `usda`, so
these cannot be overwritten by a catalog rebuild either.

**It is per 100 g already**, which is the shape `foods` stores, so no
serving-size arithmetic is needed and none is done. That matters: the
label scanner (MEAL-8) has to convert from a per-serving panel and
refuses when the serving size is unreadable. Here there is nothing to
convert and therefore nothing to get wrong.

**Sodium and salt are both published.** Sodium is taken and salt is
ignored — never converted. Same rule as the label scanner: the ~2.5x
factor between them is exactly the kind of silent arithmetic that turns
a readable number into a wrong one.

Nothing is written by this module. It returns a candidate; the caller
shows it and the user confirms.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

#: Open Food Facts asks every client to identify itself, and rate-limits
#: anonymous traffic harder. This is the courtesy they request.
_UA = "myvitals/1.0 (self-hosted personal health tracker)"

_BASE = "https://world.openfoodfacts.org/api/v2/product"

#: Only what `foods` stores. Asking for the whole product document pulls
#: images, tags and translations that are megabytes for one lookup.
_FIELDS = (
    "code,product_name,brands,quantity,serving_size,nutriments,"
    "ingredients_text,categories_tags"
)

#: OFF key -> our column. Everything absent stays NULL: a product whose
#: fibre was never entered is not a food with no fibre.
_NUTRIENTS: dict[str, str] = {
    "energy-kcal_100g": "kcal",
    "fat_100g": "fat_g",
    "saturated-fat_100g": "saturated_fat_g",
    "carbohydrates_100g": "carbs_g",
    "sugars_100g": "sugar_g",
    "proteins_100g": "protein_g",
    "fiber_100g": "fiber_g",
    # Sodium, never salt. OFF publishes both and they differ by ~2.5x.
    "sodium_100g": "sodium_mg",
}


class BarcodeLookupError(RuntimeError):
    """The lookup could not be completed — network, or a bad response."""


def _num(v: Any) -> float | None:
    """A number, or None. Never a zero standing in for an absent value."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # OFF occasionally carries negative or absurd values from bad edits.
    return f if 0 <= f < 100_000 else None


def _display_name(product: dict[str, Any]) -> str | None:
    """"Lay's Classic Potato Chips" — brand first, as it reads on the pack.

    Brands arrive as a comma-separated list that frequently repeats the
    product name ("Nutella, Ferrero, Yum yum"), so only the first is used
    and only when the name does not already contain it.
    """
    name = (product.get("product_name") or "").strip()
    if not name:
        return None
    brands = (product.get("brands") or "").split(",")
    brand = brands[0].strip() if brands else ""
    if brand and brand.lower() not in name.lower():
        return f"{brand} {name}"
    return name


async def lookup(code: str, timeout: float = 12.0) -> dict[str, Any] | None:
    """One product by barcode, mapped to the shape `foods` stores.

    Returns None when the barcode is simply not in the database, which is
    an ordinary outcome and not an error — OFF is strong on European and
    supermarket own-brands and thinner on US regional products.
    """
    code = "".join(ch for ch in code if ch.isdigit())
    if not (7 <= len(code) <= 14):
        raise BarcodeLookupError("that is not a barcode")

    url = f"{_BASE}/{code}.json"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                url, params={"fields": _FIELDS}, headers={"User-Agent": _UA},
            )
    except httpx.HTTPError as e:
        raise BarcodeLookupError(f"could not reach Open Food Facts: {e}") from e

    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise BarcodeLookupError(
            f"Open Food Facts returned {r.status_code}",
        )
    try:
        body = r.json()
    except ValueError as e:
        raise BarcodeLookupError("Open Food Facts sent a malformed reply") from e

    if body.get("status") != 1:
        return None
    product = body.get("product") or {}
    name = _display_name(product)
    if not name:
        # A row with a barcode and no name is not usable as a food, and
        # inventing "Unknown product" would put it in the catalog forever.
        return None

    # OFF's own taxonomy, most general first ("plant-based-foods" before
    # "spreads"). The LAST recognised tag is kept because it is the most
    # specific, and specificity is what decides a kitchen shelf: peanut
    # butter is a spread, not merely a plant-based food.
    tags = [
        t for t in (product.get("categories_tags") or [])
        if isinstance(t, str) and t.startswith("en:")
    ]

    nutriments = product.get("nutriments") or {}
    out: dict[str, Any] = {
        "barcode": code,
        "name": name[:255],
        "source": "openfoodfacts",
        "ingredients": (product.get("ingredients_text") or "").strip()[:2000] or None,
        # Kept verbatim for the confirm screen: "1 oz (28.3 g)" tells the
        # user which pack they are looking at, which is the only reliable
        # way to catch a wrong OFF entry before it is saved.
        # Stored so the pantry can shelve it. Without this every scanned
        # product landed in "Other" — twelve of one user's fifteen
        # uncategorised pantry rows were barcode scans.
        "category": (tags[-1] if tags else None),
        "category_tags": tags,
        "package_size": (product.get("quantity") or "").strip()[:120] or None,
        "serving_size_text": (product.get("serving_size") or "").strip()[:120] or None,
    }
    for src, dest in _NUTRIENTS.items():
        v = _num(nutriments.get(src))
        if dest == "sodium_mg" and v is not None:
            # OFF publishes sodium in GRAMS per 100 g; the column is mg.
            v = v * 1000.0
        out[dest] = v
    log.info("openfoodfacts %s -> %s", code, name[:60])
    return out
