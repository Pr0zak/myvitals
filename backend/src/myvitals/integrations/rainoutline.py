"""RainoutLine (https://rainoutline.com) trail-status scraper.

Each customer is keyed by a 10-digit DNIS. The page fragment endpoint
`/search/dnis_refresh/{dnis}/updated/0` returns just the trail rows
(no header chrome) and is what the page uses for its 30-second
self-refresh — much friendlier to parse than the full page.

We poll it on a 15-minute APScheduler interval, persist every reading
to `trail_status_snapshots` (hypertable), and emit a `trail_alerts`
row whenever a trail's status differs from its previous snapshot AND
the user has subscribed to that trail.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import models, session as _session

log = logging.getLogger(__name__)

# DNIS is supplied per-deployment via the RAINOUTLINE_DNIS env var.
# If unset, the poller and fetch helpers no-op and log a warning so
# the rest of the app still runs.
SOURCE_URL = "https://rainoutline.com/search/dnis_refresh/{dnis}/updated/0"
USER_AGENT = "myvitals-trail-poller/0.7 (+self-hosted)"

# RainoutLine's CSS classes map to status codes
STATUS_FROM_CLASS = {
    "status0": "open",
    "status1": "pending",
    "status2": "closed",
    "status3": "unknown",
}


@dataclass
class TrailReading:
    extension: int
    name: str
    status: str
    comment: str | None
    source_ts: datetime | None


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

# Each row contains a status span, a name link with the extension in
# the href, an "Updated" cell with relative time, and a precise
# timestamp in a `clue` span.
_ROW_RE = re.compile(
    r'<span class="(status[0-3])">([^<]+)</span>.*?'
    r'href="[^"]*?/extension/\d+/(\d+)"[^>]*>([^<]+)</a>',
    re.S,
)
_CLUE_RE = re.compile(r'<span class="clue">([^<]+)</span>', re.S)
_COMMENT_RE = re.compile(
    r'<span class="comment">([^<]*)</span>', re.S,
)


def _slugify(name: str) -> str:
    """Slug used for stable URLs / dedup keys."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:64] or "trail"


def _parse_source_ts(raw: str) -> datetime | None:
    """RainoutLine ships timestamps as `5/6/26 6:52 pm` (Central time
    implied). Best-effort parse; returns None on failure."""
    raw = raw.strip()
    for fmt in ("%m/%d/%y %I:%M %p", "%m/%d/%Y %I:%M %p"):
        try:
            naive = datetime.strptime(raw, fmt)
            # Assume Central time; the slight DST ambiguity isn't worth
            # solving for a self-hosted single-user app.
            return naive.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_dnis_refresh(html: str) -> list[TrailReading]:
    """Parse the dnis_refresh fragment HTML into a list of trail readings.

    Tolerates missing comments, missing timestamps, and odd ordering.
    Re-runs over each row's substring rather than relying on global state."""
    readings: list[TrailReading] = []
    # Split HTML into per-row chunks. The structure isn't strictly
    # one row per <tr>, but the ROW_RE will match each (status, link)
    # pair and we use the surrounding context for clue/comment.
    matches = list(_ROW_RE.finditer(html))
    for i, m in enumerate(matches):
        status_class, _, ext_str, name = m.groups()
        ext = int(ext_str)
        # Look for clue / comment spans between this match and the next
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        chunk = html[m.start():end]
        clue = _CLUE_RE.search(chunk)
        comment = _COMMENT_RE.search(chunk)
        readings.append(TrailReading(
            extension=ext,
            name=name.strip(),
            status=STATUS_FROM_CLASS.get(status_class, "unknown"),
            comment=comment.group(1).strip() if comment else None,
            source_ts=_parse_source_ts(clue.group(1)) if clue else None,
        ))
    return readings


# ------------------------------------------------------------------
# Fetch + persist
# ------------------------------------------------------------------

async def _resolve_dnis(db: AsyncSession | None = None) -> str | None:
    """Look up the DNIS in trail_status_config first; fall back to the
    RAINOUTLINE_DNIS env var so fresh installs can boot before anyone
    visits Settings."""
    own = db is None
    if own:
        db = _session.SessionLocal()
    try:
        cfg = await db.get(models.TrailStatusConfig, 1)  # type: ignore[union-attr]
        if cfg and cfg.dnis:
            return cfg.dnis
    finally:
        if own:
            await db.close()  # type: ignore[union-attr]
    return settings.rainoutline_dnis


async def fetch(dnis: str | None = None) -> str:
    dnis = dnis or await _resolve_dnis()
    if not dnis:
        raise RuntimeError("RAINOUTLINE_DNIS not configured (set via Settings)")
    url = SOURCE_URL.format(dnis=dnis)
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text


async def _ensure_trail(
    db: AsyncSession, dnis: str, reading: TrailReading, now: datetime,
) -> models.Trail:
    """Find-or-create the Trail row; touch last_seen_at on every poll."""
    stmt = (
        select(models.Trail)
        .where(models.Trail.dnis == dnis)
        .where(models.Trail.extension == reading.extension)
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = models.Trail(
            dnis=dnis,
            extension=reading.extension,
            name=reading.name,
            slug=_slugify(f"{reading.name}-{reading.extension}"),
            last_seen_at=now,
        )
        db.add(row)
        await db.flush()
    else:
        # Names sometimes change ("Hodge Park" → "Hodge Park - North")
        if row.name != reading.name:
            row.name = reading.name
        row.last_seen_at = now
    return row


async def _latest_status(
    db: AsyncSession, trail_id: int, before: datetime,
) -> str | None:
    """Most recent status for a trail strictly before `before`. Used to
    diff against the new reading and decide whether to alert."""
    stmt = (
        select(models.TrailStatusSnapshot.status)
        .where(models.TrailStatusSnapshot.trail_id == trail_id)
        .where(models.TrailStatusSnapshot.fetched_at < before)
        .order_by(models.TrailStatusSnapshot.fetched_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    return row[0] if row else None


def _should_alert(notify_on: str, prev: str | None, new: str) -> bool:
    if prev is None:
        return False  # first sighting — no flip
    if prev == new:
        return False
    if notify_on == "any":
        return True
    if notify_on == "open_only":
        return new == "open"
    if notify_on == "close_only":
        return new == "closed"
    return False


async def poll_and_persist(dnis: str | None = None) -> dict:
    """Run one fetch cycle. Returns a count summary suitable for logging."""
    dnis = dnis or await _resolve_dnis()
    if not dnis:
        log.info("rainoutline: DNIS not configured — skipping poll")
        return {"fetched": 0, "snapshots": 0, "alerts": 0, "skipped": True}
    html = await fetch(dnis)
    readings = parse_dnis_refresh(html)
    if not readings:
        log.warning("rainoutline: parsed 0 readings — site format may have changed")
        return {"fetched": 0, "snapshots": 0, "alerts": 0}

    now = datetime.now(timezone.utc)
    snap_count = 0
    alert_count = 0
    async with _session.SessionLocal() as db:
        # Build subscribed-trail-ids set in one query
        subs = (await db.execute(
            select(models.TrailSubscription.trail_id, models.TrailSubscription.notify_on)
        )).all()
        notify_by_id = {tid: notify for tid, notify in subs}

        for r in readings:
            trail = await _ensure_trail(db, dnis, r, now)
            prev = await _latest_status(db, trail.id, now)
            db.add(models.TrailStatusSnapshot(
                fetched_at=now,
                trail_id=trail.id,
                status=r.status,
                comment=r.comment,
                source_ts=r.source_ts,
            ))
            snap_count += 1
            if trail.id in notify_by_id:
                if _should_alert(notify_by_id[trail.id], prev, r.status):
                    db.add(models.TrailAlert(
                        trail_id=trail.id,
                        from_status=prev,
                        to_status=r.status,
                        source_ts=r.source_ts,
                        created_at=now,
                    ))
                    alert_count += 1
        await db.commit()

    log.info(
        "rainoutline: %d readings, %d snapshots, %d alerts (dnis=%s)",
        len(readings), snap_count, alert_count, dnis,
    )
    return {"fetched": len(readings), "snapshots": snap_count, "alerts": alert_count}


def iter_open(readings: Iterable[TrailReading]) -> Iterable[TrailReading]:
    """Convenience for callers that just want the open trails."""
    return (r for r in readings if r.status == "open")
