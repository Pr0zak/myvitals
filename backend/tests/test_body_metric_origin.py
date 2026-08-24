"""Where a weight reading came from, and how its companions attach.

Two defects, both found while researching how to get a Garmin Index
Smart Scale into the app, and both latent rather than theoretical.

**Health Connect is a bus, not a source.** Several apps can write a
WeightRecord to it and the phone flattened every one of them to
`source = "health_connect"`. That is harmless while exactly one app
writes weight; it stops being harmless the moment a second one does. On
this install that second writer is one toggle away — enabling Garmin
Connect's Health Connect export would put Garmin and Google Health
readings in the same column under the same label, permanently
indistinguishable, and the server upserts on `time` alone with ON
CONFLICT DO NOTHING, so a same-instant collision silently discards the
loser with no record of which it was.

**A scale writes three records, not one.** Weight, body fat and lean mass
arrive separately from a single step onto the scale, at approximately —
not exactly — the same instant. The old join matched on an exact
`Instant.toString()`, so one millisecond of writer drift left the
percentage stranded as its own row with a null weight, which the
`["time"]`-keyed upsert could never merge afterwards. The reading
survived; the body composition was divorced from the weight it belonged
to, which for a body-composition scale is most of the point of owning
one.
"""
from __future__ import annotations

import pathlib
import re

from myvitals.api.ingest import BodyMetricSample
from myvitals.db import models

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
MAPPER = (
    pathlib.Path(__file__).resolve().parents[2]
    / "android/app/src/main/kotlin/app/myvitals/health/DataMapper.kt"
)


# ------------------------------------------------------------ schema


def test_origin_is_separate_from_source():
    """`source` means the PIPE for this table — "health_connect",
    "garmin", "fitbit", "manual" — and two of those values come from ZIP
    importers that have no package name at all. Overloading it would
    break the meaning of every historical row."""
    cols = {c.key: c for c in models.BodyMetric.__table__.columns}
    assert "origin" in cols
    assert cols["origin"].nullable, "must be additive over existing rows"
    assert cols["source"].type.length == 32, "source stays the short pipe label"


def test_origin_is_wide_enough_for_a_health_connect_package_name():
    """Health Connect's synthetic package names run to 65 characters.
    `source` allows 32, which would truncate them into collisions."""
    cols = {c.key: c for c in models.BodyMetric.__table__.columns}
    synthetic = (
        "com.android.healthconnect.phone.j435c75937c893553bd649c1c4c380d31"
    )
    assert len(synthetic) > 32, "the premise of this test"
    assert cols["origin"].type.length >= len(synthetic)


def test_origin_is_optional_on_the_wire():
    """An older phone build must keep posting successfully rather than
    422-ing on a field it does not know about."""
    s = BodyMetricSample(time="2026-08-24T12:00:00Z", weight_kg=115.4)
    assert s.origin is None


# ------------------------------------------------- the companion join


def _mapper_source() -> str:
    return MAPPER.read_text()


def test_the_companion_join_is_no_longer_exact_string_equality():
    src = _mapper_source()
    assert "fatByTs" not in src, "the exact-timestamp map is the bug"
    assert "claimNearest" in src


def test_the_tolerance_is_stated_and_bounded():
    """Loose enough for writer jitter between three records from one
    weigh-in, far tighter than the gap between two genuine weigh-ins."""
    src = _mapper_source()
    m = re.search(r"COMPANION_TOLERANCE_S\s*=\s*(\d+)L", src)
    assert m, "the tolerance must be a named constant, not a literal"
    seconds = int(m.group(1))
    assert 30 <= seconds <= 600, f"{seconds}s is outside a defensible range"


def test_a_companion_record_can_only_be_claimed_once():
    """Without removal from the pool, one body-fat reading could attach
    to two different weigh-ins and be double-counted."""
    src = _mapper_source()
    assert "pool.remove(best)" in src


def test_unclaimed_companions_are_still_kept():
    """A body-fat percentage typed in by hand has no weight to attach to
    and must not be silently dropped — absent is not zero, here as
    everywhere else in this codebase."""
    src = _mapper_source()
    assert "orphanFat" in src and "orphanLean" in src
    assert "fatPool.map" in src


def test_provenance_is_carried_on_every_body_metric_path():
    """Weight, orphaned fat and orphaned lean mass all need it — an
    orphan row with no origin is exactly as ambiguous as the weight rows
    this change exists to disambiguate."""
    src = _mapper_source()
    body = src[src.index("val fatPool"):src.index("return IngestBatch")]
    assert body.count("dataOrigin.packageName") == 3, (
        "expected weight + orphan fat + orphan lean to carry origin"
    )


def test_the_pipe_label_is_unchanged():
    """1,243 existing rows say "health_connect", "garmin" or "fitbit".
    Repurposing that column would rewrite their meaning."""
    src = _mapper_source()
    # Scoped to the body-metric block: BloodPressureSample further down
    # legitimately carries the same pipe label and is not in scope here.
    body = src[src.index("val fatPool"):src.index("return IngestBatch")]
    assert body.count('source = "health_connect"') == 3


# -------------------------------------------------- upsert semantics


def test_body_metrics_still_upsert_do_nothing():
    """Deliberate. Switching to DO UPDATE would let an orphan row — which
    carries a NULL weight — overwrite a real weight reading at the same
    instant. Losing the second copy of a duplicate is recoverable;
    nulling a real measurement is not.
    """
    src = (SRC / "api" / "ingest.py").read_text()
    call = src[src.index("if batch.body_metrics:"):]
    call = call[:call.index("counts[")]
    assert "update_cols" not in call, (
        "body metrics must stay ON CONFLICT DO NOTHING"
    )
