#!/usr/bin/env python3
"""Pre-release parity gate.

Surface which user-facing surfaces (web ↔ phone pairs) changed in the
commit range, and warn when only one side of a paired surface was
modified. The release skill runs this before tagging so a single-side
change becomes a deliberate choice (with a flag to override) rather
than an accidental drift.

Usage:
    scripts/parity_check.py [<since-ref>]   # default: previous tag

Pairs encode the rule: if a web file changed, the phone file in the
same row should usually have changed too (and vice versa). One-sided
changes are valid in some cases — e.g. web-only QA pages, phone-only
notification logic — but they should be acknowledged.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each pair: (web_path, phone_path, optional notes). Both relative to repo root.
PAIRS: list[tuple[str, str, str]] = [
    ("frontend/src/views/Trails.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/trails/TrailsScreen.kt",
     "Trails list + status grouping"),
    ("frontend/src/views/TrailsMap.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/trails/TrailsScreen.kt",
     "Trails aggregate map (phone has TrailsOverviewMap inside TrailsScreen.kt)"),
    ("frontend/src/views/workout/StrengthCatalog.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthCatalogScreen.kt",
     "Strength catalog rows + filter chips"),
    ("frontend/src/views/workout/StrengthEquipment.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthEquipmentScreen.kt",
     "Equipment editor (training prefs paired separately via StrengthTrainingPrefsScreen.kt)"),
    ("frontend/src/views/Fasting.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/FastingScreen.kt",
     "Fasting protocol picker + active fast + history (#FAST family)"),
    ("frontend/src/views/workout/StrengthToday.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthTodayScreen.kt",
     "Today's workout + set logging UI"),
    ("frontend/src/views/workout/StrengthHistory.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthHistoryScreen.kt",
     "Workout history list + calendar"),
    ("frontend/src/views/Sober.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/SoberHomeScreen.kt",
     "Sober streak + history"),
    ("frontend/src/views/Activities.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivitiesScreen.kt",
     "Activities list"),
    ("frontend/src/views/Today.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsScreen.kt",
     "Today / vitals dashboard"),
    ("frontend/src/views/Sleep.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsScreen.kt",
     "Sleep view (phone surfaces it inside VitalsScreen)"),
    ("frontend/src/views/HeartRate.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsScreen.kt",
     "Heart rate view"),
    ("frontend/src/views/Weight.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsScreen.kt",
     "Weight view"),
    ("frontend/src/utils/muscleIcon.ts",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/MuscleIcon.kt",
     "Muscle anatomy chip resolver"),
]

# Paths that are intentionally web-only (don't trigger a parity warning
# when they change without a phone counterpart).
WEB_ONLY_OK = {
    "frontend/src/views/YogaIconSamples.vue",  # internal QA / icon audit
    "frontend/src/views/Logs.vue",
    "frontend/src/views/Settings.vue",
    "frontend/src/views/Goals.vue",
    "frontend/src/views/Trends.vue",
    "frontend/src/views/Calendar.vue",
    "frontend/src/views/Insights.vue",
    "frontend/src/views/Compare.vue",
    "frontend/src/views/Alerts.vue",
    "frontend/src/views/BloodPressure.vue",
    "frontend/src/views/Log.vue",
}


def changed_files(since: str) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-only", f"{since}...HEAD"],
        check=True, capture_output=True, text=True,
    )
    return {line for line in out.stdout.splitlines() if line}


def previous_tag() -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "describe", "--tags", "--abbrev=0"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def main() -> int:
    since = sys.argv[1] if len(sys.argv) > 1 else previous_tag()
    changed = changed_files(since)
    if not changed:
        print(f"No changes since {since}")
        return 0

    # Bucket the changed files
    web = {f for f in changed if f.startswith("frontend/")}
    phone = {f for f in changed if f.startswith("android/")}
    other = changed - web - phone

    print(f"Changes since {since}:")
    print(f"  web:   {len(web)}")
    print(f"  phone: {len(phone)}")
    print(f"  other: {len(other)}\n")

    issues: list[str] = []
    matched_pairs: list[str] = []
    for web_path, phone_path, note in PAIRS:
        web_changed = web_path in changed
        phone_changed = phone_path in changed
        if web_changed and phone_changed:
            matched_pairs.append(f"  {note}")
        elif web_changed and not phone_changed:
            if web_path in WEB_ONLY_OK:
                continue
            issues.append(
                f"  WEB-ONLY: {web_path}\n"
                f"     expected paired change in: {phone_path}\n"
                f"     note: {note}"
            )
        elif phone_changed and not web_changed:
            issues.append(
                f"  PHONE-ONLY: {phone_path}\n"
                f"     expected paired change in: {web_path}\n"
                f"     note: {note}"
            )

    if matched_pairs:
        print("Paired changes (good):")
        print("\n".join(matched_pairs))
        print()
    if issues:
        print("⚠ Parity gaps — confirm each is intentional:")
        print("\n".join(issues))
        print(
            "\nIf intentional (e.g. follow-up phone release tagged separately), "
            "re-run release with --skip-parity-check."
        )
        return 1

    print("✓ All paired surfaces have matching changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
