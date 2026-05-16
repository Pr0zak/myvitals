"""UPDATE-1 — Settings UI release-check + apply endpoints.

The CT's host-side cron (deploy/myvitals-auto-update.cron) polls
GHCR every 15 min for new images. This module surfaces the same
mechanism to the dashboard:

  GET /api/update/check
    Compare local backend version vs latest GitHub release tag.

  POST /api/update/apply
    Drop a trigger file the host-side cron will see on its next
    minute tick, kicking off auto-update.sh immediately rather than
    waiting up to 15 min for the next routine run.

The trigger file path (`/var/lib/myvitals/update-requested`) lives
in a bind-mounted volume the host's auto-update.sh checks on every
invocation. The POST endpoint never executes docker commands
itself — it just writes the flag. Keeps the backend container
unprivileged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from ..auth import require_any

# NOTE: prefix is `/update`, NOT `/api/update`. The Caddy frontend
# does `uri strip_prefix /api` on incoming `/api/*` requests before
# proxying, so a browser call to `/api/update/check` arrives here as
# `/update/check`. Hard-coding `/api/update/...` in the route would
# get double-stripped and 404 through Caddy. Phone clients hitting
# port 8000 directly use the same path: `http://host:8000/update/check`
# (with explicit `/api` only when going via the web frontend).
#
# Auth: require_any (ingest OR query token). The phone Settings →
# "Backend updates" section reads /update/check too, and the phone
# only stores an ingest token. Same pattern as the sober endpoints —
# either token is sufficient for read + trigger here because the
# action gates aren't token-tier-aware.
router = APIRouter(prefix="/update", dependencies=[Depends(require_any)])

TRIGGER_FILE = Path("/var/lib/myvitals/update-requested")
LOG_FILE = Path("/var/lib/myvitals/auto-update.log")
GITHUB_REPO = "Pr0zak/myvitals"


def _semver_tuple(s: str) -> tuple[int, ...]:
    """Parse a 'vX.Y.Z' or 'X.Y.Z' string into a comparable tuple.
    Falls back to (0,) on parse failure so unknown versions sort last."""
    s = s.lstrip("v")
    parts: list[int] = []
    for chunk in s.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return (0,)
    return tuple(parts)


def _local_version() -> str:
    """Read the running backend version from pyproject's installed
    metadata. This is the same value /version returns."""
    try:
        from importlib.metadata import version
        return version("myvitals")
    except Exception:
        return "0.0.0"


@router.get("/check")
async def check_update() -> dict[str, Any]:
    """Compare local backend version against the latest GitHub release.

    Returns:
      current             — local backend version (e.g. "0.7.227")
      latest              — latest release version, or null on lookup failure
      latest_tag          — full tag string ("v0.7.227")
      latest_url          — release page URL
      latest_published_at — ISO timestamp
      release_notes       — first 1000 chars of the release body, for the UI
      update_available    — true when latest > current
      error               — null on success, else short error string
    """
    current = _local_version()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        return {
            "current": current,
            "latest": None,
            "latest_tag": None,
            "latest_url": None,
            "latest_published_at": None,
            "release_notes": None,
            "update_available": False,
            "error": f"{type(e).__name__}: {e}"[:160],
        }

    latest_tag = str(data.get("tag_name") or "")
    latest = latest_tag.lstrip("v") or None
    notes = (data.get("body") or "")[:1000]
    return {
        "current": current,
        "latest": latest,
        "latest_tag": latest_tag or None,
        "latest_url": data.get("html_url"),
        "latest_published_at": data.get("published_at"),
        "release_notes": notes,
        "update_available": (
            latest is not None
            and _semver_tuple(latest) > _semver_tuple(current)
        ),
        "error": None,
    }


@router.post("/apply", status_code=202)
async def apply_update() -> dict[str, Any]:
    """Request an immediate update by dropping a trigger file the
    host-side cron will pick up within ~1 minute.

    The actual recreate runs out-of-process in deploy/auto-update.sh
    on the host (not in the backend container), so this endpoint can
    return cleanly even though the backend will be killed seconds
    later. The dashboard should re-poll /api/update/check after ~30s
    to see the new version live.

    Idempotent — repeated POSTs just refresh the file's mtime.

    Returns 202 with `triggered=true` on success, or 200 with
    `triggered=false, error=...` when the trigger volume isn't
    mounted (the UI shows a "trigger volume missing" hint).
    """
    try:
        TRIGGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRIGGER_FILE.touch()
        return {"triggered": True, "trigger_path": str(TRIGGER_FILE)}
    except Exception as e:  # noqa: BLE001
        # The bind mount might not be set up yet — give the UI a clear
        # signal rather than a 500.
        return {
            "triggered": False,
            "error": f"{type(e).__name__}: {e}"[:160],
            "hint": "Trigger volume not mounted. See deploy/auto-update.sh "
                    "header for activation instructions.",
        }


@router.get("/status")
async def cron_status() -> dict[str, Any]:
    """Report the host cron's health for the Settings UI.

    The host-side cron writes to `/var/lib/myvitals/auto-update.log`
    (the bind-mounted shared volume); the backend reads it via the
    same mount. Stale log = cron probably not running.

    Returns:
      log_present       — whether the log file exists at all
      log_modified_at   — ISO timestamp of last write, null if absent
      stale_seconds     — seconds since last write, null if absent
      cron_healthy      — true when the routine 15-min cron has run
                          within the last 20 min (slack window)
      tail              — last 20 lines of the log, newest last
      trigger_pending   — true when an UI-triggered update is still
                          waiting to be picked up by the cron
    """
    out: dict[str, Any] = {
        "log_present": False,
        "log_modified_at": None,
        "stale_seconds": None,
        "cron_healthy": False,
        "tail": [],
        "trigger_pending": TRIGGER_FILE.exists(),
    }
    if not LOG_FILE.exists():
        return out
    out["log_present"] = True
    from datetime import datetime, timezone
    import time
    mtime = LOG_FILE.stat().st_mtime
    out["log_modified_at"] = datetime.fromtimestamp(
        mtime, tz=timezone.utc,
    ).isoformat()
    stale = int(time.time() - mtime)
    out["stale_seconds"] = stale
    # 20-min slack lets the 15-min cron miss exactly one tick before
    # we flag it unhealthy. Tight enough to catch real outages.
    out["cron_healthy"] = stale < 20 * 60
    try:
        lines = LOG_FILE.read_text(errors="replace").splitlines()
        out["tail"] = lines[-20:]
    except Exception:  # noqa: BLE001
        pass
    return out
