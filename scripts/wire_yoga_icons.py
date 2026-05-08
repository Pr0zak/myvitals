#!/usr/bin/env python3
"""Wire a folder of SVG icons into the yoga catalog entries.

Usage:
    scripts/wire_yoga_icons.py <svg_folder> [--dry-run]

Steps performed:
1. For each yoga pose in `backend/src/myvitals/data/exercises_supplement.json`
   that has movement_pattern == "mobility", look for a matching SVG file
   in <svg_folder> via several name conventions (Pigeon_Pose.svg,
   pigeon_pose.svg, pigeon-pose.svg, "Pigeon Pose.svg").
2. If found, copy the SVG to
   `backend/src/myvitals/data/img/<pose-id>/0.svg` and update the
   catalog row's `image_front` to `/exercises/img/<pose-id>/0.svg`.
   The phone + web catalog already prefer `image_front` when set.
3. Print a per-pose summary.

The script is idempotent — running again with a new folder simply
overwrites existing copies.

Source-of-icons examples:
- The Noun Project: sign up free, search "yoga pose", download SVGs.
  Save with the pose name as filename (e.g., "Downward Dog.svg").
- Flaticon: same flow.
- Custom: whatever naming, this script's matcher is forgiving.

Then deploy: tar + ssh + docker compose build backend.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# Paths in the repo — script lives in scripts/, the rest is relative.
ROOT = Path(__file__).resolve().parent.parent
SUPPLEMENT = ROOT / "backend/src/myvitals/data/exercises_supplement.json"
IMG_BASE = ROOT / "backend/src/myvitals/data/img"


def candidates(pose_id: str, name: str) -> list[str]:
    """Filename variants to look for in the source folder."""
    variants = {
        f"{pose_id}.svg",
        f"{pose_id.lower()}.svg",
        f"{pose_id.replace('_', '-').lower()}.svg",
        f"{name}.svg",
        f"{name.lower()}.svg",
        f"{name.replace(' ', '-').lower()}.svg",
        f"{name.replace(' ', '_').lower()}.svg",
        f"{name.lower().replace(' pose', '')}.svg",
    }
    return list(variants)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("svg_folder", type=Path)
    ap.add_argument("--dry-run", action="store_true",
                    help="report matches without copying or editing JSON")
    args = ap.parse_args()
    if not args.svg_folder.is_dir():
        raise SystemExit(f"not a directory: {args.svg_folder}")
    if not SUPPLEMENT.exists():
        raise SystemExit(f"not found: {SUPPLEMENT}")

    rows = json.loads(SUPPLEMENT.read_text())
    yoga = [r for r in rows if r.get("movement_pattern") == "mobility"]
    print(f"Found {len(yoga)} yoga poses in supplement.")

    matched = 0
    for r in yoga:
        pose_id = r["id"]
        name = r["name"]
        src = None
        for cand in candidates(pose_id, name):
            p = args.svg_folder / cand
            if p.is_file():
                src = p
                break
        if src is None:
            print(f"  [skip] {pose_id:<28} no SVG match for '{name}'")
            continue
        dest_dir = IMG_BASE / pose_id
        dest = dest_dir / "0.svg"
        rel = f"/exercises/img/{pose_id}/0.svg"
        if args.dry_run:
            print(f"  [dry]  {pose_id:<28} {src.name}  →  {rel}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            r["image_front"] = rel
            print(f"  [ok]   {pose_id:<28} {src.name}  →  {rel}")
        matched += 1

    if not args.dry_run and matched:
        SUPPLEMENT.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        print(f"\nWrote {SUPPLEMENT.relative_to(ROOT)} ({matched} entries updated)")
        print("\nNext: deploy backend so the new images are served.")
    elif args.dry_run:
        print(f"\nDry run complete — {matched}/{len(yoga)} would update.")
    else:
        print("\nNothing matched. Check the SVG folder + filenames.")


if __name__ == "__main__":
    main()
