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
    # ── Vitality Neon shell (opt-in 6-tab redesign) — web view ↔ phone screen ──
    ("frontend/src/components/NeonNav.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/NeonAppShell.kt",
     "Neon 6-tab shell (Today/Body/Train/Trails/Coach/You)"),
    ("frontend/src/views/Rings.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/RingsScreen.kt",
     "Neon Today / rings home"),
    ("frontend/src/components/NarrativeCards.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/NarrativeCards.kt",
     "Narrative event cards + hypnogram"),
    ("frontend/src/components/HealthStatus.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/HealthStatus.kt",
     "Health status — rollup + readiness card"),
    ("frontend/src/components/FocusAreas.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/FocusAreas.kt",
     "Focus areas navigation grid"),
    ("frontend/src/components/MetricCard.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/MetricCard.kt",
     "Metric card — the single card vocabulary"),
    ("frontend/src/components/KeyMetrics.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/KeyMetrics.kt",
     "Key metrics section"),
    ("frontend/src/components/ActivityYearCalendar.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/ActivityCalendar.kt",
     "Per-activity-type year calendar (Activities + Train)"),
    ("frontend/src/utils/activityCategory.ts",
     "android/app/src/main/kotlin/app/myvitals/ui/common/ActivityCategory.kt",
     "Activity category -> label/colour palette (classic + neon)"),
    ("frontend/src/views/Body.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/BodyScreen.kt",
     "Neon Body / vitals grid"),
    ("frontend/src/views/Train.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/TrainHubScreen.kt",
     "Neon Train hub (strength + activities)"),
    # Coach is intentionally web-only in the neon shell — the phone neon Coach
    # tab + hub were removed in v0.7.309 (CoachHubScreen.kt deleted) per user
    # request; the classic phone shell + shared CoachScreen still exist. So
    # there is deliberately no phone↔web pair for the neon Coach hub.
    ("frontend/src/views/You.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/YouScreen.kt",
     "Neon You / personal hub"),
    ("frontend/src/views/Trails.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/trails/TrailsScreen.kt",
     "Trails list + status grouping"),
    ("frontend/src/views/TrailsMap.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/trails/TrailsScreen.kt",
     "Trails aggregate map (phone has TrailsOverviewMap inside TrailsScreen.kt)"),
    ("frontend/src/views/TrailVisits.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/trails/TrailVisitsScreen.kt",
     "Activities linked to one trail"),
    ("frontend/src/views/ActivitiesMap.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivityMapScreen.kt",
     "All-activities GPS map"),
    ("frontend/src/views/workout/StrengthCatalog.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthCatalogScreen.kt",
     "Strength catalog rows + filter chips"),
    ("frontend/src/views/workout/StrengthEquipment.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthEquipmentScreen.kt",
     "Equipment editor"),
    # Web keeps training prefs inside the equipment page; phone splits them
    # into a dedicated screen. Either phone file satisfies the web pair.
    ("frontend/src/views/workout/StrengthEquipment.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthTrainingPrefsScreen.kt",
     "Training preferences (level / split / goal / exercises-per-workout)"),
    ("frontend/src/views/Fasting.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/FastingScreen.kt",
     "Fasting protocol picker + active fast + history (#FAST family)"),
    ("frontend/src/views/Coach.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/CoachScreen.kt",
     "Multi-card AI coach surface (#COACH family)"),
    ("frontend/src/views/workout/StrengthToday.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthTodayScreen.kt",
     "Today's workout + set logging UI"),
    ("frontend/src/views/workout/StrengthHistory.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthHistoryScreen.kt",
     "Workout history list + calendar"),
    ("frontend/src/views/workout/StrengthCharts.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/WorkoutChartsScreen.kt",
     "Strength charts (volume / muscle map / progression / records / mesocycle)"),
    ("frontend/src/views/Sober.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/SoberHomeScreen.kt",
     "Sober streak + history"),
    ("frontend/src/views/Activities.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivitiesScreen.kt",
     "Activities list"),
    # TD-2 added this row. The pair had been unregistered since both files
    # were written, which is why the two surfaces were free to diverge on HR
    # zones for as long as they did — the web grew three different local zone
    # computations and the phone grew none, and nothing flagged it.
    ("frontend/src/views/ActivityDetail.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivityDetailScreen.kt",
     "Single activity detail (stats, map, HR series, HR zones, trail link)"),
    # Web keeps the activity type→icon resolver in a shared component;
    # phone keeps it inline in ActivitiesScreen.kt (iconForType).
    ("frontend/src/components/ActivityIcon.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/activities/ActivitiesScreen.kt",
     "Activity type→icon resolver"),
    ("frontend/src/views/Today.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/neon/RingsScreen.kt",
     "Today / home dashboard"),
    ("frontend/src/views/Sleep.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/SleepDetailScreen.kt",
     "Sleep view (phone surfaces it inside VitalsScreen)"),
    ("frontend/src/views/HeartRate.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/HrDetailScreen.kt",
     "Heart rate detail view"),
    # TD-3 added this row. The phone has had day navigation on its detail
    # screens since they were written and the web had none, which the gate
    # could not see because there was no web file to pair with DayNav.kt.
    ("frontend/src/components/DayNav.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/common/DayNav.kt",
     "Day picker (‹ date › + Today chip, off-today tint)"),
    ("frontend/src/views/Weight.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/WeightDetailScreen.kt",
     "Weight view"),
    ("frontend/src/utils/muscleIcon.ts",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/MuscleIcon.kt",
     "Muscle anatomy chip resolver"),
    # DAY-1: the unified single-day view.
    ("frontend/src/views/Day.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/DayScreen.kt",
     "Unified day view"),
    # TILE-1: the Key-metrics order editor. Both surfaces write the same
    # scoped endpoint, so a change to one side's control set almost always
    # needs the other.
    ("frontend/src/components/TileOrderEditor.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/TileOrderScreen.kt",
     "Key-metrics tile order editor"),
    # TD-7 moved Settings out of WEB_ONLY_OK. The pairing is STRUCTURAL, not
    # line-for-line: the phone owns Health Connect permissions and APK
    # install, the web owns historical imports, AI configuration and the
    # Strava cookie paste, and neither of those belongs on the other surface.
    # What must stay in step is the set of things a user can reach and
    # change at all -- the gate was blind to this pair while eight of the
    # web's twelve panes were unreachable by any click.
    ("frontend/src/views/Settings.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/SettingsScreen.kt",
     "Settings (structural pair — surface-specific panes are expected)"),
    ("frontend/src/views/Journal.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/JournalScreen.kt",
     "Journal / annotation entry surface (#LOG family)"),
]

# Paths that are intentionally web-only (don't trigger a parity warning
# when they change without a phone counterpart).
WEB_ONLY_OK = {
    "frontend/src/views/YogaIconSamples.vue",  # internal QA / icon audit
    "frontend/src/views/Logs.vue",
    "frontend/src/views/Goals.vue",
    "frontend/src/views/Trends.vue",
    "frontend/src/views/Calendar.vue",
    "frontend/src/views/Insights.vue",
    "frontend/src/views/Compare.vue",
    "frontend/src/views/Alerts.vue",
    "frontend/src/views/BloodPressure.vue",
    "frontend/src/views/Log.vue",
    "frontend/src/views/Watch.vue",      # phone surfaces watch via Today.vue tile
    # Coach.vue now paired with android/.../CoachScreen.kt — moved out
    # of WEB_ONLY_OK; the pair is registered above.
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


def check_map_integrity() -> list[str]:
    """Pair rows that point at files which no longer exist.

    A row naming a deleted file silently checks nothing — the gate keeps
    reporting green for a surface that has no counterpart any more. Worse,
    a row can point at the WRONG counterpart and still look healthy: this
    map had HeartRate.vue paired with the phone HOME screen rather than the
    HR detail screen, so a change to either was measured against a file
    that had no reason to move with it.
    """
    import os

    stale = []
    for web_path, phone_path, _label in PAIRS:
        for path in (web_path, phone_path):
            if not os.path.exists(path):
                stale.append(path)
    return stale


def main() -> int:
    stale = check_map_integrity()
    if stale:
        print("⚠ parity map references files that do not exist:")
        for path in stale:
            print(f"    {path}")
        print("  A row naming a deleted file checks nothing. Fix the map.")
        return 1

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

    # A web file can map to several phone files (and vice-versa) when one
    # surface splits a page the other keeps unified. Use OR semantics: a
    # changed web file is satisfied if ANY of its phone counterparts also
    # changed. Iterating pairs independently would false-flag the other
    # counterparts as "web-only".
    from collections import defaultdict
    web_to_phones: dict[str, list[str]] = defaultdict(list)
    phone_to_webs: dict[str, list[str]] = defaultdict(list)
    note_by_pair: dict[tuple[str, str], str] = {}
    for web_path, phone_path, note in PAIRS:
        web_to_phones[web_path].append(phone_path)
        phone_to_webs[phone_path].append(web_path)
        note_by_pair[(web_path, phone_path)] = note

    issues: list[str] = []
    matched_pairs: list[str] = []
    for (web_path, phone_path), note in note_by_pair.items():
        if web_path in changed and phone_path in changed:
            matched_pairs.append(f"  {note}")

    for web_path, phone_paths in web_to_phones.items():
        if web_path not in changed or web_path in WEB_ONLY_OK:
            continue
        if not any(p in changed for p in phone_paths):
            issues.append(
                f"  WEB-ONLY: {web_path}\n"
                f"     expected paired change in: {' OR '.join(phone_paths)}"
            )

    for phone_path, web_paths in phone_to_webs.items():
        if phone_path not in changed:
            continue
        if not any(w in changed for w in web_paths):
            issues.append(
                f"  PHONE-ONLY: {phone_path}\n"
                f"     expected paired change in: {' OR '.join(web_paths)}"
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
