"""Guards on the pre-migration backup hook (BK-1).

These assert a *deployment* invariant rather than application behaviour,
which is unusual for this suite, but the invariant is worth pinning: the
backend image's CMD runs `alembic upgrade head` on start, so the recreate
inside auto-update.sh applies schema migrations unattended. The dump has
to happen before that recreate, and a failure has to stop the update
rather than be swallowed.

Both are one-line edits away from silently regressing, and neither shows
up in any runtime test — the failure mode is "we had no restore point",
discovered only when a restore point is needed.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
AUTO_UPDATE = DEPLOY / "auto-update.sh"
BACKUP = DEPLOY / "backup.sh"


def test_backup_script_exists_and_is_executable():
    assert BACKUP.is_file(), "deploy/backup.sh is missing"
    mode = BACKUP.stat().st_mode
    assert mode & stat.S_IXUSR, (
        "deploy/backup.sh is not executable; auto-update.sh guards on -x and "
        "would silently skip the pre-migration dump"
    )


def test_auto_update_dumps_before_recreating_containers():
    """The dump must precede the recreate, not follow it.

    A dump taken after `docker compose up --force-recreate` is worthless:
    the new image's CMD has already run `alembic upgrade head` by then, so
    the dump captures the post-migration state — exactly the state you
    would be trying to recover *from*.
    """
    text = AUTO_UPDATE.read_text()

    backup_call = text.find("--pre-update")
    assert backup_call != -1, "auto-update.sh never calls backup.sh --pre-update"

    # The first force-recreate after the "update detected" branch is the one
    # that applies migrations. Anything earlier in the file is commentary.
    detected = text.find("update detected")
    assert detected != -1
    recreate = text.find("--force-recreate", detected)
    assert recreate != -1, "no --force-recreate found after the update-detected branch"

    assert backup_call < recreate, (
        "backup.sh --pre-update runs AFTER the container recreate; the dump "
        "would capture post-migration state and be useless for rollback"
    )


def test_failed_pre_update_dump_aborts_the_update():
    """A non-zero exit from backup.sh has to stop the update.

    `set -euo pipefail` does not save us here: the call is inside an `if !`
    test, which suppresses errexit by design. The explicit exit is the only
    thing preventing a migration from running with no fresh restore point.
    """
    text = AUTO_UPDATE.read_text()
    match = re.search(
        r"if\s+!\s+\"\$\(dirname \"\$0\"\)/backup\.sh\" --pre-update;\s*then(.*?)fi",
        text,
        re.DOTALL,
    )
    assert match, "the pre-update call is not wrapped in a failure branch"
    assert "exit 1" in match.group(1), (
        "a failed pre-update dump does not abort auto-update.sh"
    )


@pytest.mark.parametrize("mode", ["--pre-update", "--now", "--list"])
def test_backup_script_handles_documented_modes(mode: str):
    text = BACKUP.read_text()
    assert mode in text, f"backup.sh does not handle documented mode {mode}"


def test_backup_verifies_the_dump_header():
    """pg_dump can exit 0 having written nothing usable.

    Custom-format dumps always begin with the ASCII magic 'PGDMP'. Without
    this check a zero-byte or error-text file gets promoted out of .partial
    and sits there looking like a valid restore point.
    """
    assert "PGDMP" in BACKUP.read_text(), (
        "backup.sh does not validate the pg_dump magic header"
    )


def test_backup_writes_atomically():
    text = BACKUP.read_text()
    assert ".partial" in text, (
        "backup.sh writes dumps in place; an interrupted run would leave a "
        "truncated file indistinguishable from a good one"
    )


def test_no_nightly_backup_cron_was_added():
    """Deliberate absence, pinned so it does not drift back in.

    PBS already snapshots the whole CT nightly to a separate host. A second
    nightly dump on a 36 GB rootfs that has had a disk-pressure incident
    would risk crossing auto-update.sh's 85% reclaim trigger, which would
    then destroy the deploy rollback window. If this ever becomes wanted,
    it needs a destination that is not the CT rootfs.
    """
    crons = list(DEPLOY.glob("*.cron"))
    assert crons, "expected the existing cron files to still be present"
    for cron in crons:
        assert "backup.sh" not in cron.read_text(), (
            f"{cron.name} schedules backup.sh; see docs/operations.md for why "
            "backups are pre-update only rather than nightly"
        )


# ── SA-O3: the retention policy is executed, not just read ───────────────
#
# A fatal bash syntax error in prune_old shipped past this file once, because
# every test above reads backup.sh as text and none of them runs it. `[[ a >= b ]]`
# is not valid bash — [[ ]] has < and > for string comparison but no >=, and the
# parse error is raised for the whole script, so `backup.sh --pre-update` would
# have failed on every invocation. auto-update.sh runs that before every
# migration and a failed dump blocks the update by design, so the blast radius
# was every unattended upgrade. These two tests execute the script instead.

def test_backup_script_parses_as_bash():
    """A syntax error anywhere in the script breaks every invocation of it."""
    out = subprocess.run(
        ["bash", "-n", str(BACKUP)], capture_output=True, text=True
    )
    assert out.returncode == 0, f"backup.sh does not parse:\n{out.stderr}"


def test_prune_old_keeps_the_oldest_dump_per_day_within_the_window(tmp_path):
    """Run prune_old for real against fabricated dumps and check what survives.

    Retention is the point of the script: a pre-update restore point has to
    outlive the time it takes to notice the bug it exists for. Asserting on the
    surviving filenames is the only way to know the policy does what it says.
    """
    import datetime as _dt

    def stamp(days_ago: int, hour: int) -> str:
        d = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
        return d.replace(hour=hour, minute=0, second=0, microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    # two dumps on each of days 0, 1 and 9 — the last is outside a 5-day window
    plan = {
        "a": stamp(0, 3), "b": stamp(0, 21),
        "c": stamp(1, 4), "d": stamp(1, 22),
        "e": stamp(9, 5), "f": stamp(9, 23),
    }
    for name, taken in plan.items():
        (tmp_path / f"myvitals-{name}.dump").write_bytes(b"PGDMP fake")
        (tmp_path / f"myvitals-{name}.dump.meta").write_text(f"taken={taken}\n")

    # prune_old is not reachable without running main(), which would try to
    # reach a database — so lift the function definition out and drive it directly.
    body = BACKUP.read_text()
    start = body.index("prune_old() {")
    end = body.index("\nfree_mb()", start)
    script = (
        "set -uo pipefail\n"
        f'BACKUP_DIR="{tmp_path}"\n'
        'log() { :; }\n'
        + body[start:end]
        + "\nprune_old 1 5\n"
    )
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, f"prune_old failed:\n{out.stderr}"

    survived = sorted(p.stem.split("-")[-1] for p in tmp_path.glob("myvitals-*.dump"))
    # oldest of each in-window day survives; the out-of-window day is dropped
    assert "a" in survived, f"oldest dump of today was pruned: {survived}"
    assert "c" in survived, f"oldest dump of yesterday was pruned: {survived}"
    assert "e" not in survived and "f" not in survived, (
        f"a 9-day-old dump survived a 5-day window: {survived}"
    )
    for name in survived:
        assert (tmp_path / f"myvitals-{name}.dump.meta").exists(), (
            f"dump {name} survived but its .meta was pruned"
        )
