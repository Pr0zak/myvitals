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

from ..auth import require_query

router = APIRouter(prefix="/api/update", dependencies=[Depends(require_query)])

TRIGGER_FILE = Path("/var/lib/myvitals/update-requested")
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
