#!/usr/bin/env python3
"""Pull anatomical muscle-group icons from Noun Project for the 11
distinct primary_muscle values used in the catalog. Saves PNGs at
backend/src/myvitals/data/img/muscle/<muscle>/0.png so they can be
served via the existing /exercises/img static mount and referenced
from the catalog UI.

Doesn't touch exercises_supplement.json — these aren't exercises, just
visual chips. Future UI: small anatomy icon next to each exercise's
muscle label.

Setup mirrors scripts/nounproject_yoga_pull.py — needs NOUNPROJECT_KEY
and NOUNPROJECT_SECRET env vars (or sourced from
~/.config/myvitals/nounproject.env).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

ROOT = Path(__file__).resolve().parent.parent
IMG_BASE = ROOT / "backend/src/myvitals/data/img/muscle"
ATTRIB_PATH = IMG_BASE / "ATTRIBUTIONS.md"

# Per-muscle search terms. Order matters: list the most-specific term
# first so we anchor to a labeled-correctly icon vs the artist's
# generic "anatomy figure" (which gets returned for any muscle query
# and was causing 5 muscles to all use the same PNG).
SEARCH_TERMS: dict[str, list[str]] = {
    "chest":      ["pectoral muscle", "chest muscle"],
    "back":       ["latissimus dorsi", "lats muscle", "back muscle"],
    "shoulders":  ["deltoid muscle", "shoulder muscle"],
    "abs":        ["abdominal muscle", "rectus abdominis", "six pack abs"],
    "biceps":     ["biceps brachii", "biceps muscle"],
    "triceps":    ["triceps brachii", "triceps muscle"],
    "forearms":   ["forearm muscle", "brachioradialis"],
    "glutes":     ["gluteus muscle", "glute muscle"],
    "quads":      ["quadriceps muscle", "rectus femoris"],
    "hamstrings": ["hamstring muscle", "biceps femoris"],
    "calves":     ["gastrocnemius", "calf muscle"],
}

# Priority list — hafizcreative.id (10/11) has visually distinct icons
# per muscle and is rotated to the front. chanut-is's "anatomy" set
# returned the SAME generic glyph for 5 different muscle queries, so it
# drops to fallback. The puller now also enforces icon-id uniqueness
# across the run as a guardrail.
PREFER_CREATORS = [
    "hafizcreative.id", "chanut-is",
    "foxytigerson", "imginationlol", "hiddemaru", "kmgdesignid",
    "shmai.com",
]


def search_icon(session, oa, query: str, limit: int = 30) -> list[dict]:
    r = session.get(
        "https://api.thenounproject.com/v2/icon",
        params={"query": query, "limit": limit, "styles": "line"},
        auth=oa, timeout=20,
    )
    r.raise_for_status()
    return r.json().get("icons", [])


def cdn_png(session, icon_id: int | str, size: int = 200) -> bytes:
    url = f"https://static.thenounproject.com/png/{icon_id}-{size}.png"
    r = session.get(url, timeout=20)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"non-image response: {r.headers}")
    return r.content


def main() -> None:
    key = os.environ.get("NOUNPROJECT_KEY")
    secret = os.environ.get("NOUNPROJECT_SECRET")
    if not key or not secret:
        sys.exit("Need NOUNPROJECT_KEY + NOUNPROJECT_SECRET env vars.")

    oa = OAuth1(key, secret, signature_type="auth_header")
    session = requests.Session()
    pref = [c.lower() for c in PREFER_CREATORS]
    attributions: list[str] = []
    matched = 0
    used_icon_ids: set[int] = set()  # uniqueness guardrail

    for muscle, terms in SEARCH_TERMS.items():
        chosen = None
        used_term = None
        fallback = None
        best_idx = len(pref)

        for q in terms:
            try:
                results = search_icon(session, oa, q)
            except Exception as e:  # noqa: BLE001
                print(f"  [err]  {muscle:<12} search '{q}' → {e}")
                continue
            if not results:
                continue
            for hit in results:
                hit_id = int(hit.get("id") or hit.get("icon_id") or 0)
                if hit_id in used_icon_ids:
                    continue  # already-used by another muscle this run
                if fallback is None:
                    fallback = hit
                u = ((hit.get("creator") or {}).get("username") or "").lower()
                if u in pref:
                    idx = pref.index(u)
                    if idx < best_idx:
                        best_idx = idx
                        chosen = hit
                        used_term = f"{q} (by {u})"
                        if idx == 0:
                            break
            if chosen is not None and best_idx == 0:
                break

        if chosen is None:
            chosen = fallback
            if chosen is None:
                print(f"  [skip] {muscle:<12} no match")
                continue
            creator = (chosen.get("creator") or {}).get("username", "?")
            used_term = f"<fallback to {creator}>"

        icon_id = chosen.get("id") or chosen.get("icon_id")
        used_icon_ids.add(int(icon_id))
        creator_name = (chosen.get("creator") or {}).get("name") or "unknown"
        attribution = chosen.get("attribution") or \
            f"Icon by {creator_name} from The Noun Project"

        try:
            payload = cdn_png(session, icon_id)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {muscle:<12} download id={icon_id} → {e}")
            continue

        dest_dir = IMG_BASE / muscle
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "0.png").write_bytes(payload)
        attributions.append(f"- **{muscle.capitalize()}** — {attribution}")
        print(f"  [ok]   {muscle:<12} {creator_name:<30}  → "
              f"img/muscle/{muscle}/0.png  ({used_term})")
        matched += 1

    if matched:
        IMG_BASE.mkdir(parents=True, exist_ok=True)
        ATTRIB_PATH.write_text(
            "# Muscle icon attributions\n\nIcons used under CC-BY from "
            "The Noun Project.\n\n" + "\n".join(attributions) + "\n"
        )
        print(f"\n{matched}/{len(SEARCH_TERMS)} muscle icons pulled.")
        print(f"Attributions → {ATTRIB_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
