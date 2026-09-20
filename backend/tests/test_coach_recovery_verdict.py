"""SA-N4: the Coach hero must not re-threshold recovery_score client-side.

`CoachHub.vue`'s "Today's Read" hero decided strong/balanced/low by
re-thresholding the raw `recovery_score` at 70/50 in JavaScript — numbers
picked independently of the recovery TILE's own server-decided 65/30 banding
in `analytics/tiles.py` (`GOOD`/`TYPICAL`/`WATCH`). That is exactly the
"server decides, client renders" rule this app otherwise holds to (see
`test_weight_delta_direction.py` for the same class of bug on a different
screen), and it was not cosmetic: measured against production (SA-N4,
docs/sa-findings.json), the hero and the tile sitting on the same page told
different stories on 53.7% of scored days, and the hero's own verdict
flipped from the previous scored day to the next 55.7% of the time — worse
than a coin flip.

There is no frontend test runner (`frontend/package.json` has no vitest and
there are no `*.test.*` files under `frontend/src`), so — same as
`test_local_day_boundary.py` and `test_weight_delta_direction.py` — this
pins the fix by reading source rather than executing it. Weaker than a real
unit test, worth replacing once a runner lands.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
COACH_HUB = REPO / "frontend" / "src" / "views" / "CoachHub.vue"
TILES = REPO / "backend" / "src" / "myvitals" / "analytics" / "tiles.py"


def _read_tone_body() -> str:
    src = COACH_HUB.read_text()
    i = src.index("const readTone = computed")
    j = src.index("\n});", i)
    return src[i:j]


class TestCoachHeroReadsTheTileNotARethreshold:
    def test_coach_hub_fetches_the_tiles_endpoint(self):
        """The hero can't read the tile's status without the tile data."""
        assert "summaryTiles" in COACH_HUB.read_text(), (
            "CoachHub no longer calls /summary/tiles — readTone has nothing "
            "server-decided left to read"
        )

    def test_read_tone_no_longer_rethresholds_the_raw_score(self):
        """The exact bug: deciding the verdict from `recovery_score` inside
        this computed, at thresholds nobody else in the app uses."""
        body = _read_tone_body()
        assert not re.search(r"rec\w*\s*>=\s*70", body), (
            "readTone is re-thresholding recovery_score at 70 again — that "
            "disagreed with the tile's 65 cutoff on ~54% of scored days"
        )
        assert not re.search(r"rec\w*\s*<\s*50", body), (
            "readTone is re-thresholding recovery_score at 50 again"
        )

    def test_read_tone_consumes_a_tile_status(self):
        body = _read_tone_body()
        assert "recoveryTile" in body and "status" in body, (
            "readTone must derive its verdict from the recovery tile's "
            "server-decided `status`, not its own comparison on the number"
        )

    def test_read_tone_uses_the_tiles_status_vocabulary(self):
        """`good` / `watch` are `analytics/tiles.py`'s own words for this
        tile. A hand-typed synonym here would silently never match and
        `readTone` would fall through to "balanced" on every day."""
        body = _read_tone_body()
        assert '"good"' in body
        assert '"watch"' in body


class TestTheTileStaysTheSingleSourceOfTheThreshold:
    def test_tiles_py_still_bands_recovery_at_65_30(self):
        """readTone no longer carries its own numbers at all — it trusts
        this function completely, so a silent drift here is now the only
        way the threshold could ever change. Pin it."""
        src = TILES.read_text()
        i = src.index('key="recovery"')
        j = src.rindex('carried("recovery_score")', 0, i)
        block = src[j:i]
        assert "rec >= 65" in block
        assert "rec >= 30" in block


class TestFlipRateMeasuredAgainstProduction:
    """Reproduces the SA-N4 headline number on a small fixture, and checks
    the fix actually reduces it rather than just moving the bug around.

    Not a claim that noise is gone — a single night of HRV against a 7-day
    baseline is still the input, and OG2-C1 already measured (and recorded
    in TODO.md) how volatile that raw score is day to day. This only checks
    that reading the tile's status stops the hero from disagreeing with the
    tile UNDERNEATH it, and stops firing "low" on merely-average nights.
    """

    @staticmethod
    def _tile_status(rec: float | None) -> str | None:
        if rec is None:
            return None
        if rec >= 65:
            return "good"
        if rec >= 30:
            return "typical"
        return "watch"

    @classmethod
    def _tone_old(cls, rec: float, tsb: float | None) -> str:
        form = tsb if tsb is not None else 0.0
        if rec >= 70 and form >= 0:
            return "strong"
        if rec < 50:
            return "low"
        return "balanced"

    @classmethod
    def _tone_new(cls, rec: float, tsb: float | None) -> str:
        status = cls._tile_status(rec)
        if status == "good" and tsb is not None and tsb >= 0:
            return "strong"
        if status == "watch":
            return "low"
        return "balanced"

    def test_new_tone_never_disagrees_with_a_good_or_watch_tile(self):
        """The one guarantee the fix makes: whenever the tile is confident
        (good or watch), the hero says the same thing modulo the extra TSB
        gate on "strong" — it can soften "good" to "balanced" when form is
        unknown/negative, but it can never call a `watch` tile "strong",
        and it can never call a `good` tile "low"."""
        for rec in range(0, 101):
            status = self._tile_status(float(rec))
            for tsb in (None, -10.0, 0.0, 10.0):
                tone = self._tone_new(float(rec), tsb)
                if status == "watch":
                    assert tone == "low", f"watch tile (rec={rec}) read as {tone}"
                if status == "good":
                    assert tone != "low", f"good tile (rec={rec}) read as low"

    def test_new_tone_reduces_flip_rate_on_the_sa_n4_fixture(self):
        """A trimmed slice of the sequence SA-N4 measured against
        production (recovery_score, tsb) in date order. Not the full 149
        days — just enough consecutive-day pairs to show the fix moves the
        number in the right direction, without hard-coding a health
        record's worth of real values into a test file."""
        seq = [
            (56.0, -8.8), (55.4, -5.4), (46.4, 1.8), (40.0, 1.9),
            (52.5, -7.7), (50.4, -9.2), (43.7, -6.6), (30.7, -9.7),
            (32.8, -6.0), (95.3, -2.9), (63.6, 2.0), (69.2, 3.3),
            (42.2, -6.1), (47.2, -2.9), (49.4, -3.4),
        ]
        old_flips = sum(
            1 for (r0, t0), (r1, t1) in zip(seq, seq[1:])
            if self._tone_old(r0, t0) != self._tone_old(r1, t1)
        )
        new_flips = sum(
            1 for (r0, t0), (r1, t1) in zip(seq, seq[1:])
            if self._tone_new(r0, t0) != self._tone_new(r1, t1)
        )
        assert new_flips < old_flips
