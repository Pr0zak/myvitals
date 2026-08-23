"""MEAL-9: the weekly component prep planner.

Three properties matter more than anything else here, and each one is a
place where a plausible-looking implementation is actively harmful rather
than merely wrong.

**The model never emits a number the user reads.** Every other AI surface
in this app narrates observations; this one issues a week of
instructions, and a wall of invented calorie figures looks exactly as
authoritative as a real one. The tool schema has no nutrition field at
all, the prompt forbids stating one, and every figure on the finished
plan is computed from the food catalog.

**Slot budgets are not renormalised.** A plan covering lunch and dinner
gets 0.65 of the day, not a rescale to 1.0. Renormalising would prescribe
a 1,150 kcal lunch to someone eating 2,295 a day — wrong in a way that is
very hard to notice, because every individual number still looks sane.

**Nothing is scored as adherence.** Skipping a meal or eating out
releases its portions back into the ledger. A planner that turns red on
Wednesday is a planner that gets deleted in week two, which is the
failure mode the whole feature is shaped around avoiding.
"""
from __future__ import annotations

import ast
import json
import pathlib
from datetime import date

import pytest

from myvitals.analytics import foods as F
from myvitals.analytics import prep as P
from myvitals.analytics import targets as T
from myvitals.integrations import claude as C

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _code_only(src: str) -> str:
    """Source with comments and docstrings stripped via the AST.

    Assertions that match a module's own explanatory prose have produced
    several false failures in this project — including one that matched
    the comment explaining why the forbidden thing was absent.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _chicken() -> dict:
    """A real catalog row, so the arithmetic is tested against real data."""
    hits = F.search("chicken breast", ingredients_only=True, limit=5)
    assert hits, "catalog should contain a plain chicken breast"
    return hits[0]


# --------------------------------------------------------- slot budgets


def test_partial_slot_coverage_is_not_renormalised():
    """The headline correctness property of the whole planner.

    Lunch + dinner is 65% of a day. If those two slots were rescaled to
    100%, a 2,295 kcal target would prescribe a 1,060 kcal lunch and a
    1,236 kcal dinner — each individually plausible, together a 45%
    overshoot repeated every day for a week.
    """
    b = P.slot_budgets(2295, 163, ["lunch", "dinner"])
    assert b["covered_share"] == 0.65
    assert b["per_slot"]["lunch"]["kcal"] == round(2295 * 0.30)
    assert b["per_slot"]["dinner"]["kcal"] == round(2295 * 0.35)
    total = sum(s["kcal"] for s in b["per_slot"].values())
    assert total < 2295, "covered slots must not add up to the whole day"


def test_uncovered_share_is_reported_not_hidden():
    """The client has to be able to say 'breakfast is not included'
    rather than presenting the week as 800 kcal short of target."""
    b = P.slot_budgets(2295, 163, ["lunch", "dinner"])
    assert b["uncovered_share"] == 0.35
    assert b["uncovered_kcal"] == round(2295 * 0.35)


def test_full_day_coverage_leaves_nothing_uncovered():
    b = P.slot_budgets(2000, 150, ["breakfast", "lunch", "dinner", "snack"])
    assert b["covered_share"] == 1.0
    assert b["uncovered_kcal"] == 0


def test_no_target_yields_null_budgets_not_zero():
    """A missing target is unknown, not a budget of nothing."""
    b = P.slot_budgets(None, None, ["dinner"])
    assert b["per_slot"]["dinner"]["kcal"] is None
    assert b["per_slot"]["dinner"]["protein_g"] is None


def test_unknown_slot_names_fall_back_rather_than_crash():
    b = P.slot_budgets(2000, 150, ["brunch", "elevenses"])
    assert b["slots"] == ["lunch", "dinner"]


# ----------------------------------------------------- component costing


def test_component_portions_divide_the_batch():
    food = _chicken()
    out = P.resolve_components(
        [{"id": 1, "name": "Roast chicken", "kind": "protein",
          "food_id": 7, "quantity": 1000, "unit": "g", "portions": 4}],
        {7: food},
    )[0]
    assert out["grams_total"] == 1000
    assert out["grams_per_portion"] == 250
    assert out["unresolved"] is False
    assert out["per_portion"]["protein_g"] > 0


def test_a_component_with_no_food_is_weighable_but_not_costable():
    """The generic unit table turns "2 cup" into 480 g with no idea what
    is in the cup. That weight is still worth having — it portions the
    batch and it goes on the shopping list — but it is not a licence to
    attach nutrition to it, and zero would be the worst answer of all.
    """
    out = P.resolve_components(
        [{"id": 1, "name": "Mystery sauce", "kind": "sauce",
          "food_id": None, "quantity": 2, "unit": "cup", "portions": 4}],
        {},
    )[0]
    assert out["grams_per_portion"] == 120.0, "weight still portions the batch"
    assert out["per_portion"] is None, "but there is nothing to cost it with"
    assert out["unresolved"] is True
    assert out["unresolved_reason"] == "no food matched"


def test_unconvertible_unit_names_the_real_problem():
    """'No food matched' and 'that unit will not convert' need different
    fixes, so they must not collapse into one message."""
    food = _chicken()
    out = P.resolve_components(
        [{"id": 1, "name": "Chicken", "kind": "protein", "food_id": 7,
          "quantity": 3, "unit": "handful", "portions": 3}],
        {7: food},
    )[0]
    assert out["unresolved"] is True
    assert "convert" in out["unresolved_reason"]


def test_portions_floor_at_one():
    """A zero-portion batch would divide by zero, and a batch that
    yields nothing is not a thing anyone cooks."""
    out = P.resolve_components(
        [{"id": 1, "name": "X", "kind": "other", "food_id": None,
          "quantity": 100, "unit": "g", "portions": 0}], {},
    )[0]
    assert out["portions"] == 1


# ---------------------------------------------------------- meal costing


def test_meal_sums_its_components_by_portion_share():
    food = _chicken()
    comps = P.resolve_components(
        [{"id": 1, "name": "Chicken", "kind": "protein", "food_id": 7,
          "quantity": 1000, "unit": "g", "portions": 4}],
        {7: food},
    )
    by_id = {c["id"]: c for c in comps}
    full = P.cost_meal([{"component_id": 1, "portions": 1}], by_id)
    half = P.cost_meal([{"component_id": 1, "portions": 0.5}], by_id)
    assert full["grams"] == 250
    assert half["grams"] == 125
    assert half["nutrition"]["protein_g"] == pytest.approx(
        full["nutrition"]["protein_g"] / 2, rel=0.01,
    )


def test_uncostable_component_counts_as_unresolved_in_the_meal():
    """The meal reports what it could not cost instead of understating
    its own total."""
    comps = P.resolve_components(
        [{"id": 1, "name": "Sauce", "kind": "sauce", "food_id": None,
          "quantity": 1, "unit": "cup", "portions": 4}], {},
    )
    out = P.cost_meal([{"component_id": 1, "portions": 1}],
                      {c["id"]: c for c in comps})
    assert out["unresolved_count"] == 1
    assert out["nutrition"] is None


def test_missing_component_reference_does_not_silently_vanish():
    out = P.cost_meal([{"component_id": 999, "portions": 1}], {})
    assert out["unresolved_count"] == 1


# ---------------------------------------------------------- the ledger


def _ledger_fixture():
    comps = [
        {"id": 1, "name": "Chicken", "kind": "protein", "portions": 4},
        {"id": 2, "name": "Rice", "kind": "grain", "portions": 5},
    ]
    meals = [
        {"day": date(2026, 8, 24), "status": "accepted",
         "uses": [{"component_id": 1, "portions": 1},
                  {"component_id": 2, "portions": 1}]},
        {"day": date(2026, 8, 25), "status": "suggested",
         "uses": [{"component_id": 1, "portions": 1},
                  {"component_id": 2, "portions": 1}]},
        {"day": date(2026, 8, 26), "status": "suggested",
         "uses": [{"component_id": 1, "portions": 1}]},
    ]
    return comps, meals


def test_skipping_a_meal_returns_its_portions_to_the_ledger():
    """This is the flexibility feature, stated as arithmetic. Eating out
    on Wednesday must leave the app able to say 'a portion of chicken is
    spare', not able to say the week has gone wrong."""
    comps, meals = _ledger_fixture()
    before = {r["component_id"]: r["spare"]
              for r in P.leftover_ledger(comps, meals)}
    meals[1]["status"] = "eating_out"
    after = {r["component_id"]: r["spare"]
             for r in P.leftover_ledger(comps, meals)}
    assert after[1] == before[1] + 1
    assert after[2] == before[2] + 1


def test_skipped_and_eaten_out_behave_identically():
    comps, meals = _ledger_fixture()
    meals[1]["status"] = "skipped"
    a = P.leftover_ledger(comps, meals)
    meals[1]["status"] = "eating_out"
    b = P.leftover_ledger(comps, meals)
    assert a == b


def test_over_assignment_is_reported_as_short():
    """A plan that assigns more chicken than was cooked leaves a meal
    late in the week with nothing behind it — worth saying out loud."""
    comps = [{"id": 1, "name": "Chicken", "kind": "protein", "portions": 2}]
    meals = [
        {"day": date(2026, 8, 24), "status": "suggested",
         "uses": [{"component_id": 1, "portions": 1}]}
        for _ in range(3)
    ]
    row = P.leftover_ledger(comps, meals)[0]
    assert row["short"] is True
    assert row["spare"] == -1


def test_exact_balance_is_neither_spare_nor_short():
    comps = [{"id": 1, "name": "Rice", "kind": "grain", "portions": 2}]
    meals = [
        {"day": date(2026, 8, 24), "status": "accepted",
         "uses": [{"component_id": 1, "portions": 1}]},
        {"day": date(2026, 8, 25), "status": "accepted",
         "uses": [{"component_id": 1, "portions": 1}]},
    ]
    row = P.leftover_ledger(comps, meals)[0]
    assert row["spare"] == 0
    assert row["short"] is False


# ------------------------------------------------------- keeping food


def test_protein_used_past_its_fridge_life_warns():
    """Cooked chicken is good for about four days. A model will assign it
    to day five cheerfully, because the grid still looks balanced."""
    start = date(2026, 8, 24)
    comps = [{"id": 1, "name": "Roast chicken", "kind": "protein",
              "portions": 5}]
    meals = [{"day": start + __import__("datetime").timedelta(days=4),
              "status": "suggested",
              "uses": [{"component_id": 1, "portions": 1}]}]
    warns = P.keeps_until_warnings(comps, meals, start)
    assert warns and "Roast chicken" in warns[0]


def test_a_skipped_late_meal_does_not_trigger_a_warning():
    """Nothing is being eaten on day five, so there is nothing to warn
    about — a warning here would be noise attached to a decision the user
    already made."""
    start = date(2026, 8, 24)
    comps = [{"id": 1, "name": "Roast chicken", "kind": "protein",
              "portions": 5}]
    meals = [{"day": start + __import__("datetime").timedelta(days=4),
              "status": "skipped",
              "uses": [{"component_id": 1, "portions": 1}]}]
    assert P.keeps_until_warnings(comps, meals, start) == []


def test_sauce_keeps_longer_than_protein():
    start = date(2026, 8, 24)
    day5 = [{"day": start + __import__("datetime").timedelta(days=4),
             "status": "suggested",
             "uses": [{"component_id": 1, "portions": 1}]}]
    sauce = [{"id": 1, "name": "Peanut sauce", "kind": "sauce", "portions": 5}]
    assert P.keeps_until_warnings(sauce, day5, start) == []


# ---------------------------------------------------------- day rollup


def test_day_totals_exclude_meals_that_were_skipped():
    budgets = P.slot_budgets(2000, 150, ["lunch", "dinner"])
    meals = [
        {"day": date(2026, 8, 24), "slot": "lunch", "status": "accepted",
         "est_kcal": 600, "est_protein_g": 45, "est_fat_g": 20},
        {"day": date(2026, 8, 24), "slot": "dinner", "status": "eating_out",
         "est_kcal": 700, "est_protein_g": 50, "est_fat_g": 25},
    ]
    row = P.day_rollup(meals, 2000, 150, budgets)[0]
    assert row["planned_kcal"] == 600
    assert row["off_plan"] == 1


def test_day_budget_is_the_covered_share_not_the_whole_day():
    """A plan covering lunch and dinner is not 35% short of target; it
    simply does not include breakfast. Comparing against the full day
    would nag the user about a gap the app created itself."""
    budgets = P.slot_budgets(2000, 150, ["lunch", "dinner"])
    meals = [{"day": date(2026, 8, 24), "slot": "lunch", "status": "accepted",
              "est_kcal": 600, "est_protein_g": 45, "est_fat_g": 20}]
    row = P.day_rollup(meals, 2000, 150, budgets)[0]
    assert row["budget_kcal"] == round(2000 * 0.65)


def test_meals_within_a_day_are_ordered_by_slot():
    budgets = P.slot_budgets(2000, 150, ["breakfast", "lunch", "dinner"])
    meals = [
        {"day": date(2026, 8, 24), "slot": "dinner", "status": "accepted"},
        {"day": date(2026, 8, 24), "slot": "breakfast", "status": "accepted"},
        {"day": date(2026, 8, 24), "slot": "lunch", "status": "accepted"},
    ]
    row = P.day_rollup(meals, 2000, 150, budgets)[0]
    assert [m["slot"] for m in row["meals"]] == ["breakfast", "lunch", "dinner"]


def test_no_adherence_score_is_computed_anywhere():
    """Deliberate absence. Scoring a week that life interrupted is the
    behaviour that makes people delete meal planners."""
    code = _code_only((SRC / "analytics" / "prep.py").read_text())
    for word in ("adherence", "compliance", "streak", "missed_days"):
        assert word not in code.lower()


# -------------------------------------------------- shopping-list shape


def test_components_convert_to_shopping_lines_the_aggregator_accepts():
    """Reusing the recipe planner's aggregator is what keeps the two
    shopping lists agreeing about whether you need chicken."""
    from myvitals.analytics import shopping as S

    food = _chicken()
    comps = P.resolve_components(
        [{"id": 1, "name": "Chicken breast", "kind": "protein", "food_id": 7,
          "quantity": 1000, "unit": "g", "portions": 4}],
        {7: food},
    )
    needs = S.aggregate_needs(P.component_shopping_lines(comps))
    assert len(needs) == 1
    need = next(iter(needs.values()))
    assert need.grams == 1000
    assert need.food_id == 7


# ---------------------------------------------- the AI contract itself


def test_the_tool_schema_has_no_nutrition_field_at_all():
    """The single most important assertion in this file.

    Give the model an `est_kcal` field and it will fill it, plausibly and
    wrongly, and the client will render it beside a real figure computed
    from the catalog. Earlier surfaces here do accept model estimates,
    but those describe one hypothetical meal; this describes a week aimed
    at a deficit, where a 20% error compounds across fifteen meals into a
    plan that does the opposite of what it claims.
    """
    def field_names(node, acc):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    acc.update(v)
                field_names(v, acc)
        elif isinstance(node, list):
            for v in node:
                field_names(v, acc)
        return acc

    names = {n.lower() for n in field_names(C.PREP_PLAN_TOOL, set())}
    for banned in ("kcal", "calorie", "calories", "protein", "protein_g",
                   "macros", "fat", "fat_g", "carbs", "carbs_g",
                   "est_kcal", "nutrition"):
        assert banned not in names, f"tool schema must not ask for {banned}"


def test_the_prompt_forbids_stating_numbers():
    sys = C._prep_plan_system("blunt").lower()
    assert "do not state calories" in sys
    assert "server computes" in sys


def test_the_prompt_teaches_components_not_seven_dinners():
    sys = C._prep_plan_system("supportive").lower()
    assert "component batch cooking" in sys
    assert "seven" in sys and "dinner" in sys


def test_the_prompt_states_the_fridge_life_rule():
    sys = C._prep_plan_system("blunt").lower()
    assert "4 days" in sys or "four days" in sys


def test_the_prompt_keeps_the_fat_target_medical_and_never_invents_one():
    """The same layered safeguard the suggestion card uses. A null target
    is not permission to guess a limit."""
    sys = C._prep_plan_system("data").lower()
    assert "medical" in sys
    assert "do not invent one" in sys


def test_search_terms_are_required_so_components_can_be_costed():
    item = C.PREP_PLAN_TOOL["input_schema"]["properties"]["components"]["items"]
    assert "food_search" in item["required"]
    assert "portions" in item["required"]


def test_portion_balance_is_stated_as_a_rule():
    sys = C._prep_plan_system("blunt").lower()
    assert "portions" in sys and "must equal" in sys


# ------------------------------------------------------------- targets


def test_targets_refuse_rather_than_guess_when_the_profile_is_thin():
    out = T.compute_targets(
        weight_kg=None, height_cm=180, birth_date=date(1978, 8, 18),
        sex="male", activity_level="light", goal_weight_kg=90.7,
        today=date(2026, 8, 23),
    )
    assert out["ok"] is False
    assert "weight" in out["missing"]


def test_targets_are_always_labelled_an_estimate():
    """Mifflin-St Jeor is an equation applied to a profile, not a
    measurement. Real expenditure varies 10-15% between people with
    identical numbers, and a client that renders this as fact is
    misrepresenting it."""
    out = T.compute_targets(
        weight_kg=114.3, height_cm=180, birth_date=date(1978, 8, 18),
        sex="male", activity_level="light", goal_weight_kg=90.7,
        today=date(2026, 8, 23),
    )
    assert out["basis"] == "estimate"
    assert out["caveat"]


def test_protein_is_scaled_to_goal_weight_when_losing():
    """Scaling to CURRENT weight while dieting prescribes protein for a
    body the user is trying not to have — 229 g rather than 181 g here,
    which is both unnecessary and hard to eat in a deficit."""
    out = T.compute_targets(
        weight_kg=114.3, height_cm=180, birth_date=date(1978, 8, 18),
        sex="male", activity_level="light", goal_weight_kg=90.7,
        today=date(2026, 8, 23),
    )
    assert out["protein_range_g"] == [round(90.7 * 1.6), round(90.7 * 2.0)]


def test_deficit_never_takes_a_man_below_the_floor():
    """A 500 kcal deficit off a small TDEE is how a nominally sensible
    formula prescribes semi-starvation."""
    out = T.compute_targets(
        weight_kg=50, height_cm=155, birth_date=date(1950, 1, 1),
        sex="male", activity_level="sedentary", goal_weight_kg=45,
        today=date(2026, 8, 23),
    )
    assert out["target_kcal"] >= T.MIN_MALE_KCAL
    assert out["hit_floor"] is True
    # The reported deficit is the one actually applied, not the one asked
    # for — otherwise the projected loss rate is a fiction.
    assert out["deficit_kcal"] < T.DEFAULT_DEFICIT_KCAL


def test_maintaining_applies_no_deficit():
    out = T.compute_targets(
        weight_kg=80, height_cm=180, birth_date=date(1990, 1, 1),
        sex="male", activity_level="moderate", goal_weight_kg=80,
        today=date(2026, 8, 23),
    )
    assert out["deficit_kcal"] == 0
    assert out["expected_loss_kg_per_week"] == 0.0


def test_the_known_real_profile_lands_where_it_should():
    """A regression anchor on this user's actual numbers, so a refactor
    of the equation shows up as a diff rather than as a slowly wrong
    calorie target."""
    out = T.compute_targets(
        weight_kg=114.3, height_cm=180, birth_date=date(1978, 8, 18),
        sex="male", activity_level="light", goal_weight_kg=90.7,
        today=date(2026, 8, 23),
    )
    assert out["age"] == 48
    assert out["bmr_kcal"] == pytest.approx(2038, abs=8)
    assert out["target_kcal"] == pytest.approx(2300, abs=15)
    assert 145 <= out["protein_g"] <= 181


# ------------------------------------------------- weight-goal units


def test_a_pound_goal_is_converted_not_read_as_kilograms():
    """Caught live, on real data, after this module first shipped.

    The /goals form stores the unit the user typed. This user's goal is
    "200 lb", and reading 200 as kilograms does not fail loudly — it
    concludes they are trying to GAIN 86 kg, applies no deficit, scales
    protein to current bodyweight, and returns a perfectly plausible
    2,795 kcal surplus target. Every number on the screen looked right.
    """
    assert T.goal_target_kg(200, "lb") == pytest.approx(90.72, abs=0.01)
    assert T.goal_target_kg(200, "lbs") == pytest.approx(90.72, abs=0.01)
    assert T.goal_target_kg(200, "POUNDS") == pytest.approx(90.72, abs=0.01)
    assert T.goal_target_kg(90.7, "kg") == 90.7
    assert T.goal_target_kg(90.7, None) == 90.7


def test_no_goal_target_is_none_not_zero():
    """"No goal set" and "goal of zero" must not collapse — a zero goal
    weight would prescribe the largest deficit the floor allows."""
    assert T.goal_target_kg(None, "lb") is None


def test_the_pound_goal_produces_a_deficit_not_a_surplus():
    """The end-to-end version of the bug: same profile, goal in pounds."""
    out = T.compute_targets(
        weight_kg=114.3, height_cm=180, birth_date=date(1978, 8, 18),
        sex="male", activity_level="light",
        goal_weight_kg=T.goal_target_kg(200, "lb"),
        today=date(2026, 8, 23),
    )
    assert out["deficit_kcal"] == 500
    assert out["target_kcal"] < out["tdee_kcal"]
    assert out["expected_loss_kg_per_week"] > 0


def test_every_weight_goal_reader_shares_one_conversion():
    """Three copies of `/ 2.20462` lived in api/ai.py. A fourth is how
    one surface starts disagreeing with the others about the goal."""
    code = _code_only((SRC / "api" / "ai.py").read_text())
    assert "2.20462" not in code
    code = _code_only((SRC / "integrations" / "claude.py").read_text())
    assert "2.20462" not in code


# ------------------------------------------- portion reconciliation


def test_the_prompt_spells_out_how_to_count_portions():
    """Stating the rule was not enough — the first live plan cooked 6
    portions of chicken and assigned 11.5. The prompt now says how to
    count, and the server reconciles regardless."""
    sys = C._prep_plan_system("blunt").lower()
    assert "add up every" in sys
    assert "size the batches to the budget" in sys


def test_the_prompt_gives_the_raw_weight_arithmetic():
    """Batches came back far under budget because the model was not
    connecting a raw purchase weight to a per-portion cooked serving."""
    sys = C._prep_plan_system("blunt").lower()
    assert "raw" in sys and "167 g" in sys


def test_reconciliation_scales_quantity_with_portions():
    """The invariant the repair must preserve: grams-per-portion is
    unchanged, so every per-meal figure the user already read stays the
    same and only the shopping quantity moves."""
    food = _chicken()
    before = P.resolve_components(
        [{"id": 1, "name": "Chicken", "kind": "protein", "food_id": 7,
          "quantity": 1200, "unit": "g", "portions": 6}],
        {7: food},
    )[0]
    # 11.5 portions demanded -> ceil to 12, quantity scaled 1200*12/6.
    after = P.resolve_components(
        [{"id": 1, "name": "Chicken", "kind": "protein", "food_id": 7,
          "quantity": 2400, "unit": "g", "portions": 12}],
        {7: food},
    )[0]
    assert before["grams_per_portion"] == after["grams_per_portion"]
    assert after["grams_total"] == before["grams_total"] * 2


def test_reconciliation_is_visible_in_the_source_not_silent():
    """A silently doubled shopping quantity erodes trust in every other
    number on the page, so the repair writes a note naming what changed."""
    code = _code_only((SRC / "api" / "meals.py").read_text())
    assert "Batch sizes were raised to cover the meals planned" in code


def test_the_lean_week_note_is_computed_at_generate_not_on_read():
    """Recomputing it in `_prep_hydrate` would turn a statement about the
    plan into a comment on the user's behaviour the moment they skipped a
    meal — which this feature never does."""
    src = (SRC / "api" / "meals.py").read_text()
    hydrate = src[src.index("async def _prep_hydrate"):src.index("@router.get(\"/prep/targets\"")]
    assert "0.8" not in hydrate
    assert "That is" not in hydrate


def test_the_prompt_forbids_multi_ingredient_components():
    """A component costs against exactly one catalog food, so a
    component named "roasted broccoli and bell pepper" resolves to
    broccoli and the peppers vanish from every total — silently, because
    a food DID match, so none of the unresolved machinery fires.

    Seen live on the second generated plan. The fix is structural on the
    model's side: combine ingredients in a MEAL, never in a component.
    """
    sys = C._prep_plan_system("blunt").lower()
    assert "one ingredient per component" in sys
    assert "silently vanish" in sys


# ------------------------------------------------- energy scaling


def _scale_fixture(protein_kcal=120.0, sauce_kcal=177.0, portions=2.0):
    comps = [
        {"id": 1, "kind": "protein", "per_portion": {"kcal": protein_kcal},
         "unresolved": False},
        {"id": 2, "kind": "sauce", "per_portion": {"kcal": sauce_kcal},
         "unresolved": False},
    ]
    meals = [{
        "day": date(2026, 8, 24), "status": "suggested",
        "uses": [{"component_id": 1, "portions": portions},
                 {"component_id": 2, "portions": 1}],
    }]
    return comps, meals


def test_a_light_plan_is_scaled_up():
    """Live plans came back at 40-63% of the budget for the slots they
    covered. Two prompt revisions did not fix it, and a planner that
    lands at 40% of target does the opposite of what it is for."""
    comps, meals = _scale_fixture()
    # 240 scalable + 177 fixed = 417 against a 600 budget.
    assert P.energy_scale_factor(comps, meals, 600) == pytest.approx(1.762, abs=0.01)


def test_the_sauce_is_never_scaled():
    """Fat per meal is a medical constraint here. Uniformly tripling the
    olive oil to close a calorie gap is the single worst way to close it,
    so sauce energy is held out of BOTH sides of the ratio and the factor
    applies only to what it actually multiplies."""
    assert "sauce" not in P.SCALABLE_KINDS
    comps, meals = _scale_fixture()
    factor = P.energy_scale_factor(comps, meals, 600)
    # Scalable 240 -> 240*factor, plus the untouched 177, lands on 600.
    assert 240 * factor + 177 == pytest.approx(600, abs=1.0)


def test_a_plan_already_at_budget_is_left_alone():
    comps, meals = _scale_fixture()
    assert P.energy_scale_factor(comps, meals, 420) == 1.0


def test_a_plan_over_budget_is_never_scaled_down():
    """A rich week is visible in the day totals and is the user's call.
    Silently cutting food is how an app talks someone into under-eating."""
    comps, meals = _scale_fixture()
    assert P.energy_scale_factor(comps, meals, 300) == 1.0


def test_the_factor_is_clamped_not_abandoned():
    """Getting a 28%-of-target week to 70% is still unambiguously closer
    to what was asked for than leaving it, and the day totals still show
    the remaining gap."""
    comps, meals = _scale_fixture()
    assert P.energy_scale_factor(comps, meals, 5000) == P.MAX_ENERGY_SCALE


def test_no_budget_means_no_scaling():
    """No target is unknown, not a licence to size portions freely."""
    comps, meals = _scale_fixture()
    assert P.energy_scale_factor(comps, meals, None) == 1.0
    assert P.energy_scale_factor(comps, meals, 0) == 1.0


def test_an_uncostable_component_cannot_drive_the_factor():
    """Its energy is unknown, so counting it as zero would inflate the
    apparent shortfall and scale everything else up to compensate."""
    comps, meals = _scale_fixture()
    comps[0]["unresolved"] = True
    comps[0]["per_portion"] = None
    # Only the sauce is costable, and it is not scalable.
    assert P.energy_scale_factor(comps, meals, 600) == 1.0


def test_skipped_meals_do_not_count_toward_the_budget():
    comps, meals = _scale_fixture()
    meals[0]["status"] = "skipped"
    assert P.energy_scale_factor(comps, meals, 600) == 1.0


def test_small_shortfalls_are_left_alone():
    """Scaling for 3% would churn every shopping quantity on each
    regenerate for no benefit."""
    comps, meals = _scale_fixture()
    assert P.energy_scale_factor(comps, meals, 430) == 1.0
