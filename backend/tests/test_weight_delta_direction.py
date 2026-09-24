"""A weight gain is not automatically bad news — OG2-A5.

Two web surfaces decided that down is good, in opposite corners of the app
and with the same wrong answer:

* ``Weight.vue`` declared ``deltaCls(kg, lowerIsBetter = true)`` and called it
  bare for the 7-day, 30-day and range figures.
* ``BodyMetrics.vue`` passed a hard-coded ``invert`` to ``Delta.vue`` on the
  Today screen, which is opened far more often than /weight.

So a user gaining toward a goal had their progress painted red on both.

The server already had a position and neither screen asked for it. The
``MetricSpec`` for bodyweight in ``analytics/compare.py`` is
``better="context"``, and its docstring says why in as many words: whether
+2 lb is good depends entirely on whether the user is cutting or bulking,
"and the app does not get to assume". ``context`` means render neutral — not
"pick lower and hope".

``goalState.ts`` had already settled the principle for the goals surface: the
tone comes from the server and is not derived client-side, because a client
inferring "went down, therefore bad" would eventually paint a broken sobriety
streak as a warning. The same reasoning applies here and had not reached
these two files.

The only thing that can settle the direction is the user's own goal, so the
rule now takes one, and with no goal set the figure renders uncoloured.

There is no test runner on the frontend — ``frontend/package.json`` has no
vitest and there are no ``*.test.*`` files under ``frontend/src`` — so this
guards the rule by reading the sources, the way
``test_local_day_boundary.py`` guards the UTC-date bug. That is a weaker
check than executing the helper and it is worth replacing when a runner
lands.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend" / "src"
HELPER = FRONTEND / "weightDirection.ts"
WEIGHT_VIEW = FRONTEND / "views" / "Weight.vue"
BODY_CARD = FRONTEND / "components" / "today" / "BodyMetrics.vue"
DELTA = FRONTEND / "components" / "today" / "Delta.vue"
PHONE_WEIGHT = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "vitals" / "WeightDetailScreen.kt"
)
PHONE_TOKENS = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "AppTokens.kt"
)


class TestTheRuleExistsInOnePlace:
    def test_the_helper_is_present(self):
        assert HELPER.exists(), "the shared weight-direction rule is gone"

    def test_it_refuses_without_a_goal(self):
        """The heart of it. No goal means no direction, so no colour."""
        src = HELPER.read_text()
        assert "goal == null" in src or "goal == null) return \"neutral\"" in src
        assert '"neutral"' in src

    def test_it_carries_a_noise_band(self):
        """A card that fires on water weight is wrong most weeks.

        GOAL-STATE measured this and recorded the reasoning; openGym's
        equivalent notably lacks one, and a 0.1 kg scale wobble in the wrong
        direction painted it red.
        """
        src = HELPER.read_text()
        assert "WEIGHT_NOISE_BAND_KG" in src
        assert "1.0" in src

    def test_the_two_unit_variants_are_named_not_guessed(self):
        """Two callers work in pounds and one in kilograms.

        The GOAL-STATE note closes by saying that when adding a field here,
        ask which unit it is in — three bugs in that release were sign or
        unit errors of this exact shape. A single unit-blind helper taking
        whatever the caller had would reproduce them.
        """
        src = HELPER.read_text()
        assert "weightDeltaTone" in src
        assert "weightDeltaToneLb" in src
        assert "WEIGHT_NOISE_BAND_LB" in src


class TestNeitherSurfaceAssumesADirection:
    def test_the_weight_view_no_longer_defaults_to_lower_is_better(self):
        src = WEIGHT_VIEW.read_text()
        # Only the signature matters; the phrase also appears in the comment
        # explaining what was removed, which should stay.
        assert not re.search(r"function deltaCls\([^)]*lowerIsBetter", src), (
            "the down-is-good default is back in Weight.vue"
        )
        # UI-4: the tone is no longer derived in the view at all — it is the
        # server's `stats.tone` / `delta_7d.tone` (analytics/detail_stats.py,
        # same GOAL-STATE noise band), rendered through a fixed colour map.
        assert "TONE_COLOR[" in src and ".tone" in src
        assert "weightDeltaTone(" not in src, "Weight.vue is deriving tone again"

    def test_the_today_card_no_longer_hard_codes_invert(self):
        src = BODY_CARD.read_text()
        assert not re.search(r'suffix=" lb"\s+invert', src), (
            "BodyMetrics still hard-codes invert on the weight delta"
        )
        assert "weightDeltaToneLb" in src

    def test_the_remaining_gap_to_goal_is_not_judged(self):
        """"12 lb to go" is a distance, not progress.

        It was coloured green whenever the user was ABOVE their goal, which
        is backwards for anyone cutting and meaningless for anyone else. A
        distance does not improve or worsen, so it takes no tone.
        """
        src = WEIGHT_VIEW.read_text()
        assert "deltaCls(stats.latest - goalKg" not in src
        # UI-4: the goal distance is a status chip with no `status`, which
        # renders muted — a distance takes no tone.
        assert '<StatusChip :text="goalText" />' in src


class TestTheGenericDeltaKeepsItsHonestUses:
    def test_invert_still_exists_for_metrics_that_have_a_direction(self):
        """Resting HR genuinely is better lower. The prop is not the bug.

        Removing it would push those callers into inventing their own rule,
        which is the failure this whole task is about.
        """
        src = DELTA.read_text()
        assert "invert?: boolean" in src

    def test_an_explicit_tone_overrides_the_sign(self):
        """A caller that worked the direction out must not be second-guessed."""
        src = DELTA.read_text()
        assert "tone?:" in src
        i_tone = src.index("if (props.tone)")
        i_invert = src.index("props.invert ?")
        assert i_tone < i_invert, "the sign heuristic must not run first"

    def test_a_data_driven_invert_is_left_alone(self):
        """Hero.vue passes `:invert="a.invert"` from its data and is correct.

        This task removes assumptions, not the mechanism — a sweep that
        stripped every invert would break the metrics that legitimately have
        a direction.
        """
        hero = FRONTEND / "components" / "today" / "Hero.vue"
        if hero.exists():
            assert ':invert="a.invert"' in hero.read_text()


class TestToneVocabulary:
    def test_away_from_goal_is_amber_not_rose(self):
        """GOAL-STATE: amber, never rose — rose is for the crisis surfaces.

        Being two pounds off a target is worth noticing and is not a crisis.
        UI-4 moved the judgement to the server; the view only maps the
        server's tone to a colour, and caution maps to amber.
        """
        src = WEIGHT_VIEW.read_text()
        m = re.search(r"TONE_COLOR[^=]*=\s*\{([^}]*)\}", src)
        assert m, "Weight.vue no longer maps the server tone through TONE_COLOR"
        body = m.group(1)
        assert "caution: AMBER" in body
        assert "#ff5d7a" not in body and "#ef4444" not in body

    def test_neutral_styles_nothing(self):
        """An unjudgeable figure must not borrow the reassurance of green.

        Same rule as MEAL-2's `unknown` fat verdict rendering grey: "cannot
        judge" and "fine" are different answers and must not look alike.
        """
        src = HELPER.read_text()
        tail = src[src.index("export function weightDeltaClass"):]
        assert ': ""' in tail


class TestThePhoneAgrees:
    """OG2-D4, then UI-4.

    OG2-D4 gave the phone a goal and a private copy of the three-way rule
    (`weightDeltaTone`, with the band converted to pounds). UI-4 deleted that
    copy: the tone is computed once on the server
    (`analytics/detail_stats.weight_tone`, GOAL-STATE's noise band) and both
    clients render it. These pin that the copy stays gone and the parts of
    OG2-D4 that were about DRAWING survive.
    """

    def test_the_phone_no_longer_derives_the_tone(self):
        src = PHONE_WEIGHT.read_text()
        assert "fun weightDeltaTone" not in src
        assert "WEIGHT_NOISE_BAND_LB" not in src
        assert "s.tone" in src or "it.tone" in src

    def test_the_goal_comes_with_the_series(self):
        """The goal rides in the same response as the stats it colours, so
        the two cannot come from different moments."""
        assert "goalKg" in PHONE_WEIGHT.read_text()

    def test_the_goal_is_folded_into_the_chart_domain(self):
        """A goal outside the plotted range does not widen an axis on its own.

        It then vanishes precisely when the user is furthest from the target,
        which is when they most want to see the gap.
        """
        src = PHONE_WEIGHT.read_text()
        assert "includeLo = goal" in src
        assert "includeHi = goal" in src

    def test_the_verdict_colours_are_tokens_not_literals(self):
        """Caution is the amber token, never Bad; no hex literals."""
        src = PHONE_WEIGHT.read_text()
        tone = src[src.index("private fun toneColor"):]
        tone = tone[: tone.index("\n}\n")]
        assert '"caution" -> NeonMV.Amber' in tone
        assert "NeonMV.Bad" not in tone
        assert "0xFFFBBF24" not in src, "the hard-coded amber is back"
        assert "0xFF60A5FA" not in src, "the hard-coded blue is back"


class TestTheServerOwnsTheRule:
    def test_server_tone_uses_the_goal_state_band(self):
        src = (REPO / "backend" / "src" / "myvitals" / "analytics" / "detail_stats.py").read_text()
        assert "WEIGHT_NOISE_BAND_KG" in src
        from myvitals.analytics.detail_stats import weight_tone
        assert weight_tone(-3.0, 95.0, None) == "neutral"
        assert weight_tone(3.0, 95.0, 90.0) == "caution"
        assert weight_tone(-3.0, 95.0, 90.0) == "positive"
