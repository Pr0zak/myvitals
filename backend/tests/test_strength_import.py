"""IMPORT-1: strength-log CSV parsers + exercise resolution."""
from __future__ import annotations

from myvitals.integrations.strength_import import (
    detect_source, group_sessions, parse_rows, resolve_exercise, _to_lb,
)

STRONG = (
    "Date;Workout Name;Duration;Exercise Name;Set Order;Weight;Reps;RPE;Notes\n"
    "2021-09-14 09:22:53;Push A;1h 2min;Dumbbell Bench Press;W;20;10;;\n"
    "2021-09-14 09:22:53;Push A;1h 2min;Dumbbell Bench Press;1;40;8;8;\n"
    "2021-09-14 09:22:53;Push A;1h 2min;Dumbbell Bench Press;2;40;7;9;hard\n"
    "2021-09-14 09:22:53;Push A;1h 2min;Barbell Squat;1;100;5;;\n"
)
HEVY = (
    "title,start_time,end_time,exercise_title,superset_id,set_index,set_type,weight_kg,reps,rpe\n"
    "Leg Day,2021-09-15 17:00:00,2021-09-15 18:00:00,Goblet Squat,,0,warmup,20,10,\n"
    "Leg Day,2021-09-15 17:00:00,2021-09-15 18:00:00,Goblet Squat,,1,normal,40,8,9\n"
)
FITNOTES = (
    "Date,Exercise,Category,Weight,Weight Unit,Reps,Comment\n"
    "2021-09-16,Dumbbell Curl,Arms,15,lbs,12,\n"
    "2021-09-16,Dumbbell Curl,Arms,15,lbs,10,burn\n"
)


class TestDetect:
    def test_detect(self):
        assert detect_source(["Workout Name", "Set Order", "Weight"]) == "strong"
        assert detect_source(["title", "set_index", "weight_kg"]) == "hevy"
        assert detect_source(["Exercise", "Category", "Weight Unit"]) == "fitnotes"
        assert detect_source(["random", "columns"]) is None


class TestUnits:
    def test_kg_to_lb(self):
        assert _to_lb(40, "kg") == 88.2
        assert _to_lb(40, "lb") == 40.0
        assert _to_lb(None, "kg") is None


class TestResolve:
    def test_exact_catalog_name_matches(self):
        slug, matched = resolve_exercise("Dumbbell Bench Press")
        assert matched and slug and "import_" not in slug

    def test_parenthetical_equipment_matches(self):
        # Strong/Hevy emit "Bench Press (Dumbbell)" — must land on the same
        # catalog slug as "Dumbbell Bench Press" (token-set match).
        paren, m1 = resolve_exercise("Bench Press (Dumbbell)")
        plain, m2 = resolve_exercise("Dumbbell Bench Press")
        assert m1 and m2 and paren == plain

    def test_token_stemming(self):
        # Plural/singular collapse to the same token set (drives matching).
        from myvitals.integrations.strength_import import _tokens
        assert _tokens("Dumbbell Curls") == _tokens("Dumbbell Curl")
        assert _tokens("Bench Press (Dumbbell)") == _tokens("Dumbbell Bench Press")

    def test_no_antonym_mismatch(self):
        # The old difflib matcher filed 'Incline ...' under 'Decline ...'.
        # Token-set match must NEVER map incline onto a decline slug.
        slug, matched = resolve_exercise("Incline Dumbbell Bench Press")
        assert "decline" not in slug.lower()
        # If not an exact catalog token-set, it degrades (kept by name).
        if not matched:
            assert slug.startswith("import_")

    def test_offcatalog_barbell_degrades(self):
        # Barbell Squat isn't in the dumbbell/bench/bodyweight catalog.
        slug, matched = resolve_exercise("Barbell Squat")
        assert not matched and slug.startswith("import_")

    def test_stable_raw_slug(self):
        a, _ = resolve_exercise("Barbell Squat")
        b, _ = resolve_exercise("Barbell Squat")
        assert a == b  # re-import idempotency depends on stable ids


class TestStrong:
    def test_parse_and_group(self):
        rows = parse_rows(STRONG, "strong", strong_unit="kg")
        # 4 rows (warmup + 2 working bench + 1 squat)
        assert len(rows) == 4
        bench = [r for r in rows if "Bench" in r["exercise"]]
        assert bench[0]["set_type"] == "warmup"          # 'W' set order
        assert bench[1]["weight_lb"] == 88.2             # 40 kg -> lb
        assert bench[2]["rating"] == 2                   # RPE 9 -> rating 2
        sessions = group_sessions(rows, "strong")
        assert len(sessions) == 1                        # one Push A session
        ses = sessions[0]
        assert len(ses["exercises"]) == 2
        # set numbers renumbered 1..N within each exercise
        bench_ex = [e for e in ses["exercises"] if "Bench" in e["exercise"]][0]
        assert [s["set_number"] for s in bench_ex["sets"]] == [1, 2, 3]
        assert ses["seed"].startswith("import:strong:")


class TestHevy:
    def test_setindex_and_kg(self):
        rows = parse_rows(HEVY, "hevy", strong_unit="lb")
        assert len(rows) == 2
        assert rows[0]["set_type"] == "warmup"
        assert rows[0]["set_number"] == 1                # 0-based -> 1-based
        assert rows[1]["weight_lb"] == 88.2              # always kg


class TestFitnotes:
    def test_perrow_unit_and_numbering(self):
        rows = parse_rows(FITNOTES, "fitnotes", strong_unit="kg")
        assert len(rows) == 2
        assert rows[0]["weight_lb"] == 15.0              # lbs, no conversion
        assert [r["set_number"] for r in rows] == [1, 2]  # numbered by row order
        sessions = group_sessions(rows, "fitnotes")
        assert len(sessions) == 1                        # grouped by date alone


class TestReimportSeedStable:
    def test_seed_deterministic(self):
        s1 = group_sessions(parse_rows(STRONG, "strong"), "strong")[0]["seed"]
        s2 = group_sessions(parse_rows(STRONG, "strong"), "strong")[0]["seed"]
        assert s1 == s2


class TestTwoADay:
    def test_same_day_same_name_stay_separate(self):
        # Two "Push A" sessions on the same calendar day at different times
        # must NOT merge (keyed on the exact start time).
        csv_text = (
            "Date;Workout Name;Exercise Name;Set Order;Weight;Reps\n"
            "2021-09-14 07:00:00;Push A;Dumbbell Bench Press;1;40;8\n"
            "2021-09-14 18:00:00;Push A;Dumbbell Bench Press;1;42;8\n"
        )
        sessions = group_sessions(parse_rows(csv_text, "strong"), "strong")
        assert len(sessions) == 2
        assert sessions[0]["seed"] != sessions[1]["seed"]
