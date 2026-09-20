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

SA-G3 — "both changed" is not "both changed the same way". A pair where
both files moved in the range used to print as a bare "good" and vanish
from the output. That catches a surface shipped to one client and
forgotten on the other; it says nothing about a fix landing on only one
side while both files happen to have unrelated edits in the same range.
Semantic diffing isn't tractable here, so this does NOT try to tell
whether the same behaviour moved. Instead it demotes the "good" list to
a "confirm these match" list a human is expected to eyeball before
tagging, and adds a cheap, deliberately-crude proxy: when both sides
changed but by wildly different amounts, that pair is annotated as
worth a closer look (`asymmetric()` below). Neither the confirm list nor
the asymmetry flag affects the exit code — only a one-sided gap does —
because a "please confirm" list that fails the build on every release
becomes a check nobody reads within a month. (The evidence for this
finding named 1d006a7 as an asymmetric-looking miss; checked against
that commit's actual diff, HeartRate.vue changed 19 lines and
HrDetailScreen.kt changed 21 — nearly identical, not asymmetric. That
commit does not demonstrate the proxy catching anything; it is kept
honest here rather than claimed as a validated example.)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each pair: (web_path, phone_path, optional notes). Both relative to repo root.
PAIRS: list[tuple[str, str, str]] = [
    # ── Meals: recipes, pantry, food lookup (MEAL-1) ──
    # Three web views map onto one phone screen with three tabs, so all
    # three rows point at MealsScreen.kt. That is deliberate: a change to
    # any one of the web views should still make the checker ask whether
    # the phone tab moved with it.
    ("frontend/src/views/meals/Recipes.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/MealsScreen.kt",
     "Recipes — list, editor, nutrition totals"),
    ("frontend/src/views/meals/Pantry.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/MealsScreen.kt",
     "Pantry — what is in the house, expiry"),
    ("frontend/src/views/meals/Foods.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/MealsScreen.kt",
     "Food lookup + user-entered foods"),
    ("frontend/src/components/FoodPicker.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/FoodPicker.kt",
     "Food type-ahead search"),
    ("frontend/src/components/QuantityPicker.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/QuantityPicker.kt",
     "Quantity + unit picker offering the food's own measures"),
    ("frontend/src/components/PhotoPantry.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/PhotoPantry.kt",
     "Add to pantry from a photo (MEAL-7)"),
    ("frontend/src/components/PackageScan.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/PackageScan.kt",
     "Scan a packaged food from several photos (MEAL-8)"),
    ("frontend/src/views/meals/Foods.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/MealsScreen.kt",
     "Food lookup + nutrition-label scanning (MEAL-8)"),
    ("frontend/src/views/meals/Nutrition.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/MealsScreen.kt",
     "Diet settings + standalone fat check (MEAL-2)"),
    ("frontend/src/components/FatAssessment.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/FatAssessmentCard.kt",
     "Per-meal fat verdict card (MEAL-2)"),
    ("frontend/src/views/meals/Plan.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/PlanShoppingTabs.kt",
     "Weekly meal plan grid (MEAL-3)"),
    ("frontend/src/views/meals/Shopping.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/PlanShoppingTabs.kt",
     "Shopping list + Walmart deep links (MEAL-3)"),
    ("frontend/src/views/meals/Suggest.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/SuggestTab.kt",
     "AI meal suggestions (MEAL-4)"),
    # Direction A — the daily screen, paired across surfaces.
    ("frontend/src/views/meals/Today.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/TodayTab.kt",
     "Today — totals, recents, meal slots, one door to the rest"),
    ("frontend/src/views/meals/Log.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/LogTab.kt",
     "Food log — per-meal fat, complete/partial days (MEAL-5)"),
    ("frontend/src/views/meals/CanMake.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/CanMakeTab.kt",
     "What can I make — coverage ratio + missing-by-one (MEAL-6)"),
    ("frontend/src/views/meals/Prep.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/meals/PrepTab.kt",
     "Weekend component prep planner (MEAL-9)"),
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
    # SA-G2. Drill-in from StrengthToday's week-ahead strip (tap a day ->
    # /workout/strength/day/:date). Unregistered since both files were
    # written; six one-sided commits had already passed unflagged.
    ("frontend/src/views/workout/StrengthDayView.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthDayViewScreen.kt",
     "Single day drill-in (workout by date)"),
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
    # SA-G2. Five vitals-detail pairs that had gone unregistered since both
    # files were written -- one-sided commits ranged from 5 (Measurements)
    # to 27 (SkinTemp.vue<->VitalsDetailScreen.kt) with the gate blind to
    # all of it. BloodPressure.vue is the worse case: it was actively
    # declared web-only below, asserting there is no phone half while
    # BpDetailScreen.kt has existed (and been one-sided-edited 17 times)
    # the whole time.
    ("frontend/src/views/Steps.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/StepsDetailScreen.kt",
     "Steps detail view"),
    # Hrv.vue and SkinTemp.vue both render through the phone's generic
    # Vital-parametrized screen (Vital.HRV / Vital.SKIN_TEMP) rather than a
    # dedicated one -- the same many-to-one shape as the Meals rows above,
    # so either changing without the other is still worth a look.
    ("frontend/src/views/Hrv.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsDetailScreen.kt",
     "HRV detail view"),
    ("frontend/src/views/SkinTemp.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/VitalsDetailScreen.kt",
     "Skin temperature detail view"),
    ("frontend/src/views/BloodPressure.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/BpDetailScreen.kt",
     "Blood pressure log + trend"),
    ("frontend/src/views/Measurements.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/vitals/MeasurementsScreen.kt",
     "Body circumference log + trend"),
    ("frontend/src/utils/muscleIcon.ts",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/MuscleIcon.kt",
     "Muscle anatomy chip resolver"),
    # DAY-1: the unified single-day view.
    ("frontend/src/views/Day.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/DayScreen.kt",
     "Unified day view"),
    # DOW-1: per-weekday step goals. The web has a standalone component;
    # the phone renders it inline in Settings, so this pairs the component
    # against the screen that owns the phone half.
    ("frontend/src/components/StepsScheduleEditor.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/SettingsScreen.kt",
     "Per-weekday step goal editor"),
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
    # OG3-B2. The muscle-volume audit is a standalone component on web and
    # is rendered inline by the history screen on the phone, so the gate saw
    # every change to it as a one-sided change and flagged
    # StrengthHistory.vue as the missing half — which it is not.
    ("frontend/src/components/MuscleVolume.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/strength/StrengthHistoryScreen.kt",
     "Weekly muscle-volume audit (#WP-4, OG3-B2)"),
    # OG3-D1. Same shape: the data-health card is its own component on web
    # and lives inside Settings on the phone. Both render one response from
    # `/query/data-health`, so a field added to it has to reach both.
    ("frontend/src/components/DataHealthCard.vue",
     "android/app/src/main/kotlin/app/myvitals/ui/SettingsScreen.kt",
     "Per-stream freshness + integration status (HEALTH-1, OG3-D1)"),
]

# Paths that are intentionally web-only (don't trigger a parity warning
# when they change without a phone counterpart).
WEB_ONLY_OK = {
    # SA-G2 removed three stale entries that check_map_integrity() never
    # caught, because it only walks PAIRS -- this set had no equivalent
    # guard. All three name files confirmed gone via `git log`:
    #   - YogaIconSamples.vue: deleted outright, dead code (cb54ab4).
    #   - Alerts.vue: deleted outright, folded into the ALERTS-1
    #     consolidation (2e0aeef).
    #   - Log.vue (this top-level one, not meals/Log.vue): git-renamed to
    #     Journal.vue in the same commit (2e0aeef); Journal.vue has its own
    #     PAIRS row above. The unrelated frontend/src/views/meals/Log.vue
    #     (food log, MEAL-5) is a different feature that already pairs
    #     with LogTab.kt.
    "frontend/src/views/Logs.vue",
    "frontend/src/views/Goals.vue",
    "frontend/src/views/Trends.vue",
    "frontend/src/views/Calendar.vue",
    "frontend/src/views/Insights.vue",
    "frontend/src/views/Compare.vue",
    # SA-G2: confirmed genuinely web-only, not just unregistered --
    # ActivitiesCompare.vue (two-track GPS comparison) and Analytics.vue
    # (the ANALYTICS-1 tabbed hub) have no phone counterpart of any name;
    # CoachHub.vue's phone twin (CoachHubScreen.kt) was deliberately
    # deleted in v0.7.309 when the neon Coach tab was removed.
    "frontend/src/views/ActivitiesCompare.vue",
    "frontend/src/views/Analytics.vue",
    "frontend/src/views/CoachHub.vue",
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

    Resolved against ROOT rather than the current directory (SA-G2): this
    is called both from the CLI entry point (invoked from the repo root)
    and from the backend test suite (invoked from `backend/`), and a
    bare-relative `os.path.exists` silently "finds" nothing from the
    second location, which would have reported every single row as stale.
    """
    stale = []
    for web_path, phone_path, _label in PAIRS:
        for path in (web_path, phone_path):
            if not (ROOT / path).exists():
                stale.append(path)
    return stale


def all_web_views() -> set[str]:
    """Every web view under frontend/src/views/ — one file per route page."""
    return {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "frontend" / "src" / "views").rglob("*.vue")
    }


def all_phone_screens() -> set[str]:
    """Every phone Composable screen destination (`*Screen.kt`)."""
    return {p.relative_to(ROOT).as_posix() for p in (ROOT / "android").rglob("*Screen.kt")}


def unregistered_surfaces() -> tuple[list[str], list[str]]:
    """Web views / phone screens in neither PAIRS nor an opt-out set.

    check_map_integrity() (above) catches a row that points at a file which
    no longer exists, but says nothing about a file with no row at all —
    which is exactly how SA-G2 found six live pairs sitting invisible to
    this gate since the day both halves were written: nothing here was
    ever checking that PAIRS plus WEB_ONLY_OK is the full set of surfaces
    on either side. A surface belongs in exactly one of three places: a
    PAIRS row, WEB_ONLY_OK, or newly surfaced right here as a real gap.
    """
    web_registered = {web for web, _phone, _note in PAIRS}
    phone_registered = {phone for _web, phone, _note in PAIRS}
    web_gap = sorted(all_web_views() - web_registered - WEB_ONLY_OK)
    phone_gap = sorted(all_phone_screens() - phone_registered)
    return web_gap, phone_gap


# Cheap asymmetric-change-size proxy (SA-G3). Not semantic diffing -- it
# only asks "did one side change a lot more than the other", which is a
# weak signal but a free one. ASYMMETRY_MIN_LINES guards against noise on
# small commits (a 2-line vs 1-line "asymmetry" says nothing); the ratio
# guards against normal variance between a terse and a verbose surface.
ASYMMETRY_MIN_LINES = 8
ASYMMETRY_RATIO = 4


def diff_line_counts(paths: list[str], since: str) -> dict[str, int]:
    """Total changed lines (added+deleted) per path over the commit range.

    Uses the same `{since}...HEAD` range as `changed_files()` so the two
    stay consistent. A path with no textual diff in `--numstat` (binary
    file, or a rename/mode-only change) reports as `-` and is recorded as
    0 here -- treated as "no evidence" by `asymmetric()` below, not as
    proof the two sides matched.
    """
    if not paths:
        return {}
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--numstat", f"{since}...HEAD", "--", *paths],
        check=True, capture_output=True, text=True,
    )
    counts: dict[str, int] = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        try:
            counts[path] = int(added) + int(deleted)
        except ValueError:
            counts[path] = 0  # binary or otherwise unmeasurable
    return counts


def asymmetric(web_lines: int, phone_lines: int) -> bool:
    """True when one side's edit dwarfs the other's.

    A genuinely matched fix tends to be similar in size on both surfaces
    because the same logic moved on each. This will also happily pass two
    similarly-sized but totally unrelated changes -- it is a proxy, not a
    verifier, which is why it annotates the confirm-list below rather
    than failing the gate on its own.
    """
    hi, lo = max(web_lines, phone_lines), min(web_lines, phone_lines)
    return hi >= ASYMMETRY_MIN_LINES and hi >= ASYMMETRY_RATIO * max(lo, 1)


def main() -> int:
    stale = check_map_integrity()
    if stale:
        print("⚠ parity map references files that do not exist:")
        for path in stale:
            print(f"    {path}")
        print("  A row naming a deleted file checks nothing. Fix the map.")
        return 1

    web_gap, phone_gap = unregistered_surfaces()
    if web_gap or phone_gap:
        print("⚠ surfaces missing from the parity map (in neither PAIRS nor WEB_ONLY_OK):")
        for path in web_gap:
            print(f"    web:   {path}")
        for path in phone_gap:
            print(f"    phone: {path}")
        print(
            "  An unregistered surface is invisible to this gate. Add a PAIRS row for a "
            "genuine counterpart, or to WEB_ONLY_OK if it is genuinely web-only."
        )
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
    matched_pairs: list[tuple[str, str, str]] = []  # (note, web_path, phone_path)
    for (web_path, phone_path), note in note_by_pair.items():
        if web_path in changed and phone_path in changed:
            matched_pairs.append((note, web_path, phone_path))

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

    # SA-G3: "both files changed" is not "the same fix landed on both" --
    # semantic diffing isn't tractable here, so instead of reporting this
    # as a bare pass this asks a human to eyeball it, and flags the pairs
    # where change size makes that most worth doing (see asymmetric()).
    if matched_pairs:
        counts = diff_line_counts(
            sorted({path for _note, web_path, phone_path in matched_pairs
                    for path in (web_path, phone_path)}),
            since,
        )
        print("Confirm these match (both sides changed -- verify the same "
              "behaviour moved, not just both files):")
        for note, web_path, phone_path in matched_pairs:
            w, p = counts.get(web_path, 0), counts.get(phone_path, 0)
            line = f"  {note}\n     {web_path} ({w} lines) <-> {phone_path} ({p} lines)"
            if asymmetric(w, p):
                line += (
                    "\n     ⚠ change sizes are wildly different -- look closer before "
                    "assuming both sides carry the same fix"
                )
            print(line)
        print()

    if issues:
        print("⚠ Parity gaps — confirm each is intentional:")
        print("\n".join(issues))
        print(
            "\nIf intentional (e.g. follow-up phone release tagged separately), "
            "re-run release with --skip-parity-check."
        )
        return 1

    print("✓ No one-sided parity gaps.")
    if matched_pairs:
        print("  Eyeball the confirm list above before tagging -- this gate "
              "cannot tell whether the same fix landed on both sides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
