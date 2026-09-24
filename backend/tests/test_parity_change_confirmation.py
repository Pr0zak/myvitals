"""SA-G3: "both files changed" is not "the same fix landed on both sides".

`scripts/parity_check.py` used to print a matched pair (both web and phone
file touched in the commit range) as a bare "Paired changes (good)" and move
on. That is a real gap: the gate cannot tell whether the same behaviour
moved on both surfaces or the two files just happened to change for
unrelated reasons in the same range — semantic diffing isn't tractable
here. See the module docstring on `scripts/parity_check.py` for the full
rationale; this file tests the two things the redesign can actually
promise:

1. A matched pair is surfaced as a "confirm this" item for a human to
   eyeball, and — this is the part easy to get wrong — never fails the
   gate by itself. A "please confirm" list that turns every release red
   becomes a check nobody reads within a month (this is explicit in the
   finding's correction).
2. The wildly-asymmetric-change-size proxy (`asymmetric()`) fires on a
   genuinely lopsided pair and stays quiet on a balanced one, without
   ever flipping the exit code on its own.
3. A real one-sided gap still fails the gate exactly as before — the new
   confirm-list machinery must not have loosened that existing guarantee.

It also pins the fact-check the correction explicitly demanded before the
cited example could be quoted: the evidence for this finding named commit
1d006a7 (HeartRate.vue <-> HrDetailScreen.kt) as a case the asymmetric-size
proxy would have caught. Checked against the actual diff, it would not
have — the two files changed by nearly identical amounts that commit. That
commit is not usable evidence for the heuristic, and
`test_the_evidence_commit_is_not_actually_asymmetric` says so in code
rather than letting a comment repeat an unverified claim.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "parity_check.py"


def _load_parity_check():
    spec = importlib.util.spec_from_file_location("parity_check_g3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pc():
    return _load_parity_check()


# --- asymmetric(): the cheap change-size proxy ------------------------------

def test_asymmetric_fires_on_a_lopsided_pair(pc):
    assert pc.asymmetric(5, 200) is True


def test_asymmetric_is_quiet_on_a_balanced_pair(pc):
    assert pc.asymmetric(100, 100) is False


def test_asymmetric_ignores_small_commits(pc):
    # A 2-vs-3-line "asymmetry" is noise, not signal — below the minimum
    # size the proxy requires before it says anything.
    assert pc.asymmetric(2, 3) is False


def test_asymmetric_fires_when_one_side_has_no_measurable_change(pc):
    # A "changed" file with zero diffable lines (rename, mode-only change,
    # binary) opposite a real edit is the MOST suspicious shape, not the
    # least — it must not read as two sides quietly agreeing.
    assert pc.asymmetric(0, 50) is True


def test_the_evidence_commit_is_not_actually_asymmetric(pc):
    """Fact-check the correction demanded before the cited commit is quoted.

    The finding's evidence names 1d006a7 as a case the asymmetric-size
    proxy "would have flagged". Checked against the real diff, HeartRate.vue
    changed 19 lines and HrDetailScreen.kt changed 21 — essentially
    identical, not lopsided. The proxy correctly stays quiet on it; this
    commit does not demonstrate the heuristic catching anything, and the
    module docstring says so rather than repeating the unverified claim.
    """
    # This is the one test in the suite that reads real repository history, so
    # it cannot run where that history is absent. CI checks out shallow by
    # default, and a contributor may well have a truncated clone; skip rather
    # than fail, because the claim being pinned is about a past commit and not
    # about any code shipping today.
    if subprocess.run(
        ["git", "cat-file", "-e", "1d006a7~1"],
        cwd=ROOT, capture_output=True,
    ).returncode != 0:
        pytest.skip("commit 1d006a7 is not in this clone (shallow checkout)")

    # The commit's OWN diff, not `1d006a7~1...HEAD`: `diff_line_counts`
    # measures up to HEAD, so any later edit to either file (UI-4 rewrote
    # both) changed the numbers this pins without the claim changing at all.
    out = subprocess.run(
        ["git", "diff", "--numstat", "1d006a7~1", "1d006a7", "--",
         "frontend/src/views/HeartRate.vue",
         "android/app/src/main/kotlin/app/myvitals/ui/vitals/HrDetailScreen.kt"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    counts = {}
    for line in out.splitlines():
        added, deleted, path = line.split("\t")
        counts[path] = int(added) + int(deleted)
    web_lines = counts["frontend/src/views/HeartRate.vue"]
    phone_lines = counts[
        "android/app/src/main/kotlin/app/myvitals/ui/vitals/HrDetailScreen.kt"
    ]
    assert (web_lines, phone_lines) == (19, 21)
    assert pc.asymmetric(web_lines, phone_lines) is False


# --- main(): the confirm-list never fails the gate on its own --------------

def test_matched_pair_alone_does_not_fail_the_gate(pc, monkeypatch, capsys):
    """Even a lopsided matched pair must only ask for confirmation, not fail."""
    web_path, phone_path, _note = pc.PAIRS[0]
    monkeypatch.setattr(pc, "changed_files", lambda since: {web_path, phone_path})
    monkeypatch.setattr(
        pc,
        "diff_line_counts",
        lambda paths, since: {web_path: 3, phone_path: 400},
    )
    monkeypatch.setattr(sys, "argv", ["parity_check.py", "fake-since-ref"])

    rc = pc.main()
    out = capsys.readouterr().out

    assert rc == 0, "a matched pair must never fail the gate by itself"
    assert "Confirm these match" in out
    assert "wildly different" in out


def test_matched_pair_without_asymmetry_has_no_warning_annotation(pc, monkeypatch, capsys):
    web_path, phone_path, _note = pc.PAIRS[0]
    monkeypatch.setattr(pc, "changed_files", lambda since: {web_path, phone_path})
    monkeypatch.setattr(
        pc,
        "diff_line_counts",
        lambda paths, since: {web_path: 40, phone_path: 45},
    )
    monkeypatch.setattr(sys, "argv", ["parity_check.py", "fake-since-ref"])

    rc = pc.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "Confirm these match" in out
    assert "wildly different" not in out


def test_one_sided_gap_still_fails_the_gate(pc, monkeypatch):
    """The confirm-list redesign must not loosen the existing hard gap check."""
    web_path, _phone_path, _note = pc.PAIRS[0]
    monkeypatch.setattr(pc, "changed_files", lambda since: {web_path})
    monkeypatch.setattr(sys, "argv", ["parity_check.py", "fake-since-ref"])

    rc = pc.main()
    assert rc == 1
