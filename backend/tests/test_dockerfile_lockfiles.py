"""SA-S4: neither image was built from a lockfile.

Both Dockerfiles resolved fresh from floating ranges on every build —
`uv sync` against `pyproject.toml`'s `>=` constraints, `pnpm install`
against `package.json`'s `^` constraints — and both `uv.lock` and a pnpm
lockfile were absent/gitignored. So two builds of the *same* git tag could
land different dependency graphs, and nothing recorded which one actually
shipped. Fixed by committing `backend/uv.lock` + `frontend/pnpm-lock.yaml`
and switching both Dockerfiles to a frozen install (`uv sync --frozen`,
`pnpm install --frozen-lockfile`), which turns a lockfile/manifest drift
into a hard build failure instead of a silent re-resolve.

No test here spins up Docker — that's slow, and "does the image build" is
what CI's own build step already proves. What a test CAN hold still is the
wiring: that the Dockerfiles actually reference the lockfiles and pass the
frozen flag, that the lockfiles are committed and not re-gitignored, and
that the committed backend lockfile doesn't already have the exact drift
this finding warned a frozen install would fail loudly on (see
`test_ci_gate_wiring.py` for the same "the guard can silently stop
guarding" concern applied to CI wiring instead of Dockerfiles).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _text(path: pathlib.Path) -> str:
    assert path.exists(), f"{path} is missing"
    return path.read_text()


def test_backend_dockerfile_copies_and_freezes_the_lockfile():
    text = _text(ROOT / "backend" / "Dockerfile")
    assert re.search(r"COPY\s+pyproject\.toml\s+uv\.lock\s+\./", text), (
        "backend/Dockerfile must COPY uv.lock alongside pyproject.toml "
        "before the first `uv sync` — a frozen install has nothing to "
        "freeze against otherwise"
    )
    assert "uv sync --frozen" in text, (
        "backend/Dockerfile must install with --frozen so a lockfile / "
        "pyproject.toml drift fails the build instead of silently "
        "re-resolving to whatever is newest on the registry today"
    )


def test_frontend_dockerfile_copies_and_freezes_the_lockfile():
    text = _text(ROOT / "frontend" / "Dockerfile")
    assert re.search(r"COPY\s+package\.json\s+pnpm-lock\.yaml\s+\./", text), (
        "frontend/Dockerfile must COPY pnpm-lock.yaml alongside package.json"
    )
    assert "pnpm install --frozen-lockfile" in text, (
        "frontend/Dockerfile must install with --frozen-lockfile so a "
        "lockfile / package.json drift fails the build instead of "
        "silently re-resolving"
    )


def test_lockfiles_are_committed_and_not_gitignored():
    backend_lock = ROOT / "backend" / "uv.lock"
    frontend_lock = ROOT / "frontend" / "pnpm-lock.yaml"
    assert backend_lock.exists(), (
        "backend/uv.lock must be committed — it's what `uv sync --frozen` "
        "builds from"
    )
    assert frontend_lock.exists(), (
        "frontend/pnpm-lock.yaml must be committed — it's what "
        "`pnpm install --frozen-lockfile` builds from"
    )

    # Bare-line match, not substring: a re-added `uv.lock` (or a
    # `frontend/pnpm-lock.yaml`) line would silently exclude the exact
    # file this finding just committed, recreating the original bug.
    ignore_lines = {
        line.strip()
        for line in _text(ROOT / ".gitignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert "uv.lock" not in ignore_lines
    assert "pnpm-lock.yaml" not in ignore_lines
    assert "frontend/pnpm-lock.yaml" not in ignore_lines


def test_committed_uv_lock_matches_pyproject_toml():
    """A frozen install fails outright on drift — assert there isn't any,
    so a lockfile left behind by a manifest edit is caught here rather
    than as a build failure in the image job.

    Runs fully offline (`--offline`): uv only needs to verify the lock's
    own consistency against pyproject.toml's constraints, not re-resolve
    against the index, so this can't flake on a sandboxed CI runner's
    network policy.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv binary not on PATH in this environment")

    result = subprocess.run(
        [uv, "lock", "--check", "--offline"],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "backend/uv.lock has drifted from pyproject.toml — regenerate it "
        "with `uv lock` in backend/ as its own reviewed change (not "
        "folded into an unrelated commit) before committing:\n"
        f"{result.stdout}\n{result.stderr}"
    )
