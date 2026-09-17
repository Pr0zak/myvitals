"""Seeded invariant probe for the weight rounder — OG3-M3.

A different genre from everything else in this suite. The 113 other test
files assert named cases: this input gives that output. A probe asserts a
PROPERTY across a wide sweep of generated inputs, and reports the first
input that breaks it. openGym keeps two of these (`fatigue-monotonic-probe`,
`warmup-invariants`), and the idea is worth having even though the specific
models behind theirs were refused here on measurement.

It earns its place on this particular function for a reason the rest of the
suite cannot cover. `round_weight` and `deload_round` are the micro-loader
rounder — the distinguishing feature, the thing no other app in this
category does — and on this user's actual equipment the micro-loader path is
completely unexercised, because `wrist_weights_lb` is EMPTY. Every real
session runs the coarse branch. A regression in the fine-grained half would
pass the existing tests, ship, and be invisible until somebody bought a pair
of wrist weights.

Seeded, never random. An unseeded probe that fails once and passes on rerun
is worse than no probe: it trains you to re-run the suite instead of reading
it. `random.Random(SEED)` gives the same sweep every time, and widening the
sweep is a deliberate edit to this file rather than a coin flip in CI.
"""

from __future__ import annotations

import random

from myvitals.analytics import strength as s

SEED = 20260917
#: Enough to cover the interesting combinations without slowing the suite;
#: the whole file runs in well under a second.
CASES = 400

#: Rack shapes worth sweeping. The first is this user's real one, where the
#: rounder's fine path never runs; the rest are the setups it was built for.
RACKS = [
    ([5, 10, 15, 20, 25, 30, 35, 40, 45, 50], []),
    ([5, 10, 15, 20, 25, 30, 35, 40, 45, 50], [1.5]),
    ([5, 10, 15, 20, 25, 30, 35, 40, 45, 50], [1.5, 2.0]),
    ([10, 20, 30, 40], [1.25, 2.5]),
    ([8, 12, 16, 20, 24], [0.5, 1.0, 2.0]),
]


def _cases():
    rng = random.Random(SEED)
    for _ in range(CASES):
        pairs, micros = RACKS[rng.randrange(len(RACKS))]
        target = round(rng.uniform(2.0, 70.0), 2)
        yield pairs, micros, target


class TestRoundWeight:
    def test_it_always_returns_a_loadable_weight(self):
        """The whole contract. A weight the rack cannot make is not a
        prescription, it is a number."""
        for pairs, micros, target in _cases():
            out = s.round_weight(target, pairs, micros)
            loadable = set(s.valid_dumbbell_loads(pairs, micros))
            assert out in loadable, (
                f"round_weight({target}, {pairs}, {micros}) = {out}, which "
                "this rack cannot load"
            )

    def test_it_never_overshoots_by_more_than_the_tie_margin(self):
        """Documented behaviour: never recommend MORE than asked for,
        except within 0.25 lb where the tie-break prefers the lighter side.

        Overshooting matters more than undershooting here. A prescription
        heavier than intended is a set the user may fail; lighter is a set
        they complete.
        """
        for pairs, micros, target in _cases():
            out = s.round_weight(target, pairs, micros)
            if out is None:
                continue
            lightest = min(s.valid_dumbbell_loads(pairs, micros))
            if out > target + 0.25:
                # Only legitimate when the rack cannot go lighter at all.
                assert out == lightest, (
                    f"round_weight({target}) = {out}, above target with "
                    f"{lightest} available"
                )

    def test_it_is_monotonic_in_the_target(self):
        """A heavier ask never returns a lighter weight.

        The property most likely to break silently under a refactor of the
        tie-break, and the one no single named case can catch.
        """
        rng = random.Random(SEED + 1)
        for pairs, micros in RACKS:
            prev = None
            for t in [round(x * 0.37, 2) for x in range(5, 200)]:
                out = s.round_weight(t, pairs, micros)
                if prev is not None and out is not None:
                    assert out >= prev - 1e-9, (
                        f"{pairs}/{micros}: target {t} rounded to {out}, "
                        f"below the previous {prev}"
                    )
                prev = out
            rng.random()  # keep the seeded stream advancing per rack

    def test_more_micro_loaders_never_land_further_from_the_target(self):
        """The distinguishing feature, stated as a property.

        Owning finer increments must never produce a WORSE prescription
        than owning none. This is the invariant that would catch the
        micro-loader path regressing on equipment this user does not have —
        which is exactly the regression the rest of the suite cannot see.
        """
        pairs = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        rng = random.Random(SEED + 2)
        for _ in range(CASES):
            target = round(rng.uniform(4.0, 55.0), 2)
            coarse = s.round_weight(target, pairs, [])
            fine = s.round_weight(target, pairs, [1.5, 2.0])
            if coarse is None or fine is None:
                continue
            assert abs(fine - target) <= abs(coarse - target) + 1e-9, (
                f"target {target}: micro-loaders gave {fine} against the "
                f"coarse rack's {coarse} — finer equipment made it worse"
            )


class TestDeloadRound:
    def test_it_never_returns_more_than_full_weight(self):
        """A deload that adds load is a bug with a reassuring name."""
        rng = random.Random(SEED + 3)
        for pairs, micros, target in _cases():
            factor = round(rng.uniform(0.70, 1.0), 3)
            full = s.round_weight(target, pairs, micros)
            out = s.deload_round(target, factor, pairs, micros)
            if full is None or out is None:
                continue
            assert out <= full + 1e-9, (
                f"deload_round({target}, {factor}) = {out} against a full "
                f"weight of {full}"
            )

    def test_its_result_is_always_loadable_too(self):
        rng = random.Random(SEED + 4)
        for pairs, micros, target in _cases():
            factor = round(rng.uniform(0.70, 1.0), 3)
            out = s.deload_round(target, factor, pairs, micros)
            if out is None:
                continue
            assert out in set(s.valid_dumbbell_loads(pairs, micros))

    def test_a_deeper_deload_never_returns_a_heavier_weight(self):
        """Monotonic in the factor.

        Without this, the disproportion guard could produce the absurd
        result where asking for a 15% cut gives MORE weight than asking for
        10% — because one tripped the guard and the other did not. It does
        not, and this is what keeps it that way.
        """
        for pairs, micros in RACKS:
            for target in (7.5, 12.0, 17.5, 23.0, 31.0, 44.0):
                prev = None
                for factor in [1.0, 0.95, 0.925, 0.90, 0.85, 0.80, 0.75, 0.70]:
                    out = s.deload_round(target, factor, pairs, micros)
                    if prev is not None and out is not None:
                        assert out <= prev + 1e-9, (
                            f"{pairs}/{micros} at {target}: factor {factor} "
                            f"gave {out}, heavier than the previous {prev}"
                        )
                    prev = out

    def test_the_guard_stays_between_the_two_honest_answers(self):
        """The guard may pick an intermediate weight, but never an outside one.

        This assertion originally read "the guard only ever holds FULL
        weight", which was true and was the bug: snapping back to full made
        `deload_round` non-monotonic in its factor, and the monotonicity
        probe above caught it. The guard now takes the deepest cut it still
        considers proportionate.

        What must remain true is the bracket. The result is always at least
        as heavy as the naive rounded deload — that is the guard doing its
        job — and never heavier than full weight, which would be a deload
        that added load.
        """
        rng = random.Random(SEED + 5)
        for pairs, micros, target in _cases():
            factor = round(rng.uniform(0.85, 0.999), 3)
            full = s.round_weight(target, pairs, micros)
            deloaded = s.round_weight(target * factor, pairs, micros)
            out = s.deload_round(target, factor, pairs, micros)
            if None in (full, deloaded, out):
                continue
            assert deloaded - 1e-9 <= out <= full + 1e-9, (
                f"deload_round({target}, {factor}) = {out}, outside the "
                f"bracket [{deloaded}, {full}]"
            )
            assert out in set(s.valid_dumbbell_loads(pairs, micros))
