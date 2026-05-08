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

# Per-muscle search terms — anatomical qualifiers ("anatomy", "muscle")
# disambiguate from random tattoo / character art results.
SEARCH_TERMS: dict[str, list[str]] = {
    "chest":      ["chest muscle anatomy", "pectoral muscle"],
    "back":       ["back muscle anatomy", "latissimus muscle", "upper back"],
    "shoulders":  ["shoulder muscle anatomy", "deltoid muscle"],
    "abs":        ["abs muscle anatomy", "abdominal muscle", "six pack"],
    "biceps":     ["biceps muscle anatomy", "biceps"],
    "triceps":    ["triceps muscle anatomy", "triceps"],
    "forearms":   ["forearm muscle anatomy", "forearm"],
    "glutes":     ["glute muscle anatomy", "buttocks muscle"],
    "quads":      ["quadriceps muscle", "thigh muscle anatomy"],
    "hamstrings": ["hamstring muscle", "back of thigh muscle"],
    "calves":     ["calf muscle anatomy", "gastrocnemius"],
}

# Priority list — chanut-is (10/11) covers everything except hamstrings;
# hafizcreative.id (10/11) covers everything except biceps. Together:
# 11/11 with a near-uniform line-art style.
PREFER_CREATORS = [
    "chanut-is", "hafizcreative.id",
    "foxytigerson", "imginationlol", "hiddemaru", "kmgdesignid",
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
            if fallback is None:
                fallback = results[0]
            for hit in results:
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
