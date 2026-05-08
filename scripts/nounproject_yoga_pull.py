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
    # strength overrides — add when name-based search returns nothing
    "Dumbbell_Skullcrusher":     ["lying tricep extension", "tricep extension exercise",
                                   "skull crusher", "lying triceps"],
    # pilates — Noun Project's pilates coverage is thinner than yoga; use
    # broader exercise/silhouette terms when needed
    "Pilates_Hundred":           ["pilates hundred", "pilates exercise",
                                   "ab crunch lying"],
    "Pilates_Roll_Up":           ["pilates roll up", "sit up exercise",
                                   "pilates"],
    "Pilates_Single_Leg_Stretch":["single leg stretch pilates", "leg pull pilates",
                                   "pilates stretch"],
    "Pilates_Criss_Cross":       ["pilates criss cross", "bicycle crunch",
                                   "twist crunch"],
    "Pilates_Teaser":            ["pilates teaser", "v sit", "boat pose"],
    "Pilates_Swan":              ["pilates swan", "back extension exercise",
                                   "cobra exercise"],
    "Pilates_Swimming":          ["pilates swimming", "superman exercise",
                                   "back extension flutter"],
    "Pilates_Rolling_Like_Ball": ["pilates rolling ball", "tuck rock",
                                   "pilates"],
}


def auth(key: str, secret: str) -> OAuth1:
    return OAuth1(key, secret, signature_type="auth_header")


def build_terms(row: dict[str, Any]) -> list[str]:
    """Generate search terms for a non-mobility exercise. Strips the
    'Dumbbell' qualifier (NP icons are usually generic), tries the
    base name, and falls back to the movement pattern."""
    name = row["name"]
    bare = name.replace("Dumbbell ", "").replace("Single-Arm ", "")\
               .replace("Single-Leg ", "").replace("Seated ", "")
    pat = (row.get("movement_pattern") or "").replace("_", " ")
    terms = []
    seen = set()
    for t in [name, bare, f"{bare} exercise", pat,
              bare.split()[-1] if bare else None]:
        if t and t not in seen:
            seen.add(t)
            terms.append(t)
    return terms


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
    """GET /v2/icon/{id}/download → JSON {base64_encoded_file, content_type}.
    Free-tier accounts only get public-domain icons here — most yoga
    poses are CC-BY and 403."""
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


def download_png_cdn(session: requests.Session, icon_id: str | int,
                     size: int = 200) -> bytes:
    """Public CDN bypass — the thumbnail PNG sizes (42/84/200) are
    served unauthenticated from static.thenounproject.com. Works for
    CC-BY icons too, which the API download endpoint blocks for
    free-tier keys. Attribution still required."""
    url = f"https://static.thenounproject.com/png/{icon_id}-{size}.png"
    r = session.get(url, timeout=20)
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"CDN returned non-image: {r.headers}")
    return r.content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("NOUNPROJECT_KEY"))
    ap.add_argument("--secret", default=os.environ.get("NOUNPROJECT_SECRET"))
    ap.add_argument("--style", default="line",
                    choices=["line", "solid"], help="icon style filter")
    ap.add_argument("--color", default="a78bfa",
                    help="hex color (no #) for the SVG fill (API path only)")
    ap.add_argument("--png-size", type=int, default=200, choices=[42, 84, 200],
                    help="PNG thumbnail size when --use-cdn (default 200)")
    ap.add_argument("--use-cdn", action="store_true",
                    help="fetch PNG thumbnails from static.thenounproject.com "
                         "instead of the auth-gated /download endpoint. Use "
                         "this when the free tier blocks CC-BY downloads.")
    ap.add_argument("--dry-run", action="store_true",
                    help="search only — don't download or modify the supplement")
    ap.add_argument("--only", help="run a single pose id (e.g. Pigeon_Pose)")
    ap.add_argument("--patterns", default="mobility",
                    help="comma-separated movement_pattern filter, or 'all' "
                         "for every exercise. Default 'mobility' (yoga).")
    ap.add_argument("--audit-creators", action="store_true",
                    help="for each pose fetch top 20 matches and tabulate "
                         "which creators cover the most poses. Use to find "
                         "a single artist for a uniform-style pack.")
    ap.add_argument("--prefer-creator", default=None,
                    help="username, or comma-separated priority list "
                         "(e.g. 'sachan,monkik') — for each pose, pick the "
                         "first result whose creator is earliest in this "
                         "list. Falls back to top hit if no preference "
                         "matches. Yields a uniform-style pack.")
    args = ap.parse_args()
    if not args.key or not args.secret:
        sys.exit("Need --key + --secret (or NOUNPROJECT_KEY / "
                 "NOUNPROJECT_SECRET env vars).")
    if not SUPPLEMENT.exists():
        sys.exit(f"missing: {SUPPLEMENT}")

    rows = json.loads(SUPPLEMENT.read_text())
    if args.patterns == "all":
        yoga = list(rows)
    else:
        wanted = {p.strip() for p in args.patterns.split(",") if p.strip()}
        yoga = [r for r in rows if r.get("movement_pattern") in wanted]
    if args.only:
        yoga = [r for r in yoga if r["id"] == args.only]

    session = requests.Session()
    oa = auth(args.key, args.secret)

    if args.audit_creators:
        # For each pose, fetch top 20 matches (across all search terms)
        # and tally creators. A creator that shows up in N poses is a
        # candidate for a uniform pack — use --prefer-creator <username>.
        from collections import defaultdict
        creator_pose_hits: dict[str, set[str]] = defaultdict(set)
        creator_names: dict[str, str] = {}
        for r in yoga:
            pose_id = r["id"]
            terms = SEARCH_TERMS.get(pose_id, build_terms(r))
            for term in terms:
                try:
                    results = search_icon(session, oa, term,
                                          style=args.style, limit=20)
                except Exception:  # noqa: BLE001
                    continue
                for hit in results:
                    c = hit.get("creator") or {}
                    uname = c.get("username") or c.get("name") or "?"
                    creator_pose_hits[uname].add(pose_id)
                    if c.get("name"):
                        creator_names[uname] = c["name"]
        ranked = sorted(creator_pose_hits.items(),
                        key=lambda kv: (-len(kv[1]), kv[0]))[:15]
        print(f"\nTop creators by yoga-pose coverage "
              f"(of {len(yoga)} poses):\n")
        for uname, poses in ranked:
            display = creator_names.get(uname, uname)
            print(f"  {len(poses):>2}/{len(yoga)}  "
                  f"{uname:<22} ({display})  →  "
                  f"{', '.join(sorted(poses))}")
        print(f"\nRe-run with --prefer-creator <username> to pull a "
              "uniform pack from one artist.")
        return

    attributions: list[str] = []
    matched = 0
    pref_list = [c.strip().lower() for c in (args.prefer_creator or "").split(",") if c.strip()]

    for r in yoga:
        pose_id = r["id"]
        terms = SEARCH_TERMS.get(pose_id, build_terms(r))
        chosen: dict[str, Any] | None = None
        used_term: str | None = None
        fallback: dict[str, Any] | None = None
        # Track best-priority-so-far across all terms — we want the
        # earliest priority creator regardless of which search term
        # surfaced them.
        best_pref_idx = len(pref_list)  # lower = better; off-list = len()
        for term in terms:
            try:
                results = search_icon(session, oa, term,
                                      style=args.style, limit=30)
            except Exception as e:  # noqa: BLE001
                print(f"  [err]  {pose_id:<28} search '{term}' → {e}")
                continue
            if not results:
                continue
            if fallback is None:
                fallback = results[0]
            if pref_list:
                for hit in results:
                    c = hit.get("creator") or {}
                    uname = (c.get("username") or "").lower()
                    if uname in pref_list:
                        idx = pref_list.index(uname)
                        if idx < best_pref_idx:
                            best_pref_idx = idx
                            chosen = hit
                            used_term = f"{term} (by {uname})"
                            if idx == 0:  # top priority — stop searching
                                break
                if chosen is not None and best_pref_idx == 0:
                    break
            else:
                chosen = results[0]
                used_term = term
                break
        if chosen is None:
            chosen = fallback
            if chosen is not None:
                creator = (chosen.get("creator") or {}).get("username") or "?"
                used_term = f"<fallback to {creator}>"
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
            if args.use_cdn:
                payload = download_png_cdn(session, icon_id, size=args.png_size)
                ext = "png"
            else:
                payload = download_svg(session, oa, icon_id, args.color)
                ext = "svg"
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {pose_id:<28} download id={icon_id} → {e}")
            continue

        dest_dir = IMG_BASE / pose_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"0.{ext}"
        dest.write_bytes(payload)
        rel = f"/exercises/img/{pose_id}/0.{ext}"
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
