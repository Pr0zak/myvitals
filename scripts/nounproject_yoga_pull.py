#!/usr/bin/env python3
"""Pull yoga-pose SVGs from The Noun Project API and wire them into
the catalog. Single-shot: searches for each of the 15 mobility poses,
picks the best match, downloads the SVG, writes it under
backend/src/myvitals/data/img/<pose-id>/0.svg, and updates the
supplement's `image_front` field.

Setup
-----
1. Sign up free at https://thenounproject.com/developers/
2. Create an app — you get an API key + secret.
3. The free tier covers ~$5 of usage which is enough for 15 icons
   plus searches.
4. Export the credentials (or pass via --key / --secret):
       export NOUNPROJECT_KEY=...
       export NOUNPROJECT_SECRET=...

Usage
-----
    pip install requests_oauthlib
    scripts/nounproject_yoga_pull.py [--style line] [--color a78bfa]
    scripts/nounproject_yoga_pull.py --dry-run  # search only, don't download

Notes
-----
- The Noun Project v2 API uses OAuth1 (HMAC-SHA1) signed requests.
- SVGs are returned as base64 inside a JSON envelope.
- Attribution (CC-BY) is required for free-tier downloads — the
  script writes a NOUNPROJECT_ATTRIBUTIONS.md alongside the icons
  with each creator's name.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import requests
    from requests_oauthlib import OAuth1
except ImportError:
    print("Install requests + requests_oauthlib first:\n"
          "  pip install requests requests_oauthlib", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SUPPLEMENT = ROOT / "backend/src/myvitals/data/exercises_supplement.json"
IMG_BASE = ROOT / "backend/src/myvitals/data/img"
ATTRIB_PATH = IMG_BASE / "NOUNPROJECT_ATTRIBUTIONS.md"

API_BASE = "https://api.thenounproject.com/v2"

# Search terms tuned per pose — Noun Project's yoga coverage uses
# common pose names; some need the word "yoga" appended to skip
# unrelated icons.
SEARCH_TERMS: dict[str, list[str]] = {
    "Downward_Dog":              ["downward dog yoga", "downward facing dog"],
    "Childs_Pose":               ["child pose yoga", "child's pose"],
    "Cat_Cow":                   ["cat cow yoga", "cat pose yoga"],
    "Cobra_Pose":                ["cobra pose yoga"],
    "Pigeon_Pose":               ["pigeon pose yoga"],
    "Forward_Fold":              ["forward fold yoga", "standing forward bend"],
    "Warrior_2":                 ["warrior 2 yoga", "warrior pose"],
    "Triangle_Pose":             ["triangle pose yoga", "trikonasana"],
    "Seated_Forward_Bend":       ["seated forward bend yoga"],
    "Reclined_Spinal_Twist":     ["reclined twist yoga", "spinal twist"],
    "Bridge_Pose":               ["bridge pose yoga"],
    "Lizard_Pose":               ["lizard pose yoga"],
    "Half_Pigeon_Forward_Fold":  ["pigeon yoga", "half pigeon"],
    "Thread_The_Needle":         ["thread needle yoga", "shoulder stretch"],
    "Happy_Baby":                ["happy baby yoga"],
}


def auth(key: str, secret: str) -> OAuth1:
    return OAuth1(key, secret, signature_type="auth_header")


def search_icon(session: requests.Session, oa: OAuth1, query: str,
                style: str = "line", limit: int = 10) -> list[dict[str, Any]]:
    """Hit /v2/icon. Returns the raw `icons` list."""
    r = session.get(
        f"{API_BASE}/icon",
        params={"query": query, "limit": limit,
                "styles": style, "thumbnail_size": 84},
        auth=oa, timeout=20,
    )
    if r.status_code == 401:
        sys.exit("401 from Noun Project — check key/secret + that "
                 "your app is approved.")
    r.raise_for_status()
    return r.json().get("icons", [])


def download_svg(session: requests.Session, oa: OAuth1,
                 icon_id: str | int, color_hex: str) -> bytes:
    """GET /v2/icon/{id}/download → JSON {base64_encoded_file, content_type}."""
    r = session.get(
        f"{API_BASE}/icon/{icon_id}/download",
        params={"filetype": "SVG", "color": color_hex},
        auth=oa, timeout=20,
    )
    r.raise_for_status()
    body = r.json()
    encoded = body.get("base64_encoded_file") or body.get("data")
    if not encoded:
        raise RuntimeError(f"download response missing base64 payload: {body}")
    return base64.b64decode(encoded)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("NOUNPROJECT_KEY"))
    ap.add_argument("--secret", default=os.environ.get("NOUNPROJECT_SECRET"))
    ap.add_argument("--style", default="line",
                    choices=["line", "solid"], help="icon style filter")
    ap.add_argument("--color", default="a78bfa",
                    help="hex color (no #) for the SVG fill")
    ap.add_argument("--dry-run", action="store_true",
                    help="search only — don't download or modify the supplement")
    ap.add_argument("--only", help="run a single pose id (e.g. Pigeon_Pose)")
    args = ap.parse_args()
    if not args.key or not args.secret:
        sys.exit("Need --key + --secret (or NOUNPROJECT_KEY / "
                 "NOUNPROJECT_SECRET env vars).")
    if not SUPPLEMENT.exists():
        sys.exit(f"missing: {SUPPLEMENT}")

    rows = json.loads(SUPPLEMENT.read_text())
    yoga = [r for r in rows if r.get("movement_pattern") == "mobility"]
    if args.only:
        yoga = [r for r in yoga if r["id"] == args.only]

    session = requests.Session()
    oa = auth(args.key, args.secret)

    attributions: list[str] = []
    matched = 0

    for r in yoga:
        pose_id = r["id"]
        terms = SEARCH_TERMS.get(pose_id, [r["name"]])
        chosen: dict[str, Any] | None = None
        used_term = None
        for term in terms:
            try:
                results = search_icon(session, oa, term, style=args.style)
            except Exception as e:  # noqa: BLE001
                print(f"  [err]  {pose_id:<28} search '{term}' → {e}")
                continue
            if results:
                chosen = results[0]
                used_term = term
                break
        if chosen is None:
            print(f"  [skip] {pose_id:<28} no match across {len(terms)} terms")
            continue

        icon_id = chosen.get("id") or chosen.get("icon_id")
        creator = (chosen.get("creator") or {}).get("name") or "unknown"
        attribution = chosen.get("attribution") or \
            f"Icon by {creator} from The Noun Project"

        if args.dry_run:
            print(f"  [dry]  {pose_id:<28} id={icon_id} term='{used_term}' "
                  f"by {creator}")
            matched += 1
            continue

        try:
            svg = download_svg(session, oa, icon_id, args.color)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {pose_id:<28} download id={icon_id} → {e}")
            continue

        dest_dir = IMG_BASE / pose_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "0.svg"
        dest.write_bytes(svg)
        rel = f"/exercises/img/{pose_id}/0.svg"
        r["image_front"] = rel
        attributions.append(f"- **{r['name']}** — {attribution}")
        print(f"  [ok]   {pose_id:<28} {creator:<24} → {rel}")
        matched += 1

    if args.dry_run:
        print(f"\nDry run: {matched}/{len(yoga)} would download.")
        return

    if matched:
        SUPPLEMENT.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        IMG_BASE.mkdir(parents=True, exist_ok=True)
        ATTRIB_PATH.write_text(
            "# Yoga icon attributions\n\n"
            "Icons used under CC-BY from The Noun Project.\n\n"
            + "\n".join(attributions) + "\n"
        )
        print(f"\nWrote {SUPPLEMENT.relative_to(ROOT)} ({matched} entries).")
        print(f"Attributions → {ATTRIB_PATH.relative_to(ROOT)}")
        print("\nNext: deploy backend (tar + ssh + docker compose build).")
    else:
        print("\nNothing downloaded.")


if __name__ == "__main__":
    main()
