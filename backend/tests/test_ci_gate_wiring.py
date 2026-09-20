"""SA-G1: nothing ran the tests, so a red guard test was invisible.

`.github/workflows/tests.yml` runs pytest, the ruff F-code gate, and the
Android unit tests. That file alone is not the fix — the fix is that
`images.yml` (which builds and pushes the `:latest` image the CT's
auto-update cron pulls within 15 minutes) and `android-release.yml` (which
signs and publishes the APK) both `needs:` a job that calls it as a
reusable workflow. A human silently dropping that `needs:` line later, or
editing tests.yml so it no longer actually calls pytest, would recreate
exactly the blind spot this finding closed — and nothing would say so,
which is the whole shape of bug this batch exists to catch (see
test_parity_map_completeness.py and test_local_day_boundary.py for the
same "the guard itself can silently stop guarding" concern).

This can't run the workflows — no test in this repo can execute GitHub
Actions — so it is deliberately narrow: it parses the YAML and asserts the
structural wiring that makes the gate real rather than decorative. That is
the one thing about this finding a test genuinely can hold still.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    path = WORKFLOWS / name
    assert path.exists(), f"{path} is missing"
    with open(path) as f:
        return yaml.safe_load(f)


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare `on:` key as the boolean True (YAML 1.1
    # quirk) even though GitHub's own parser treats it as the literal
    # string "on". Every workflow in this repo is written that way, so
    # read whichever key actually came back.
    return workflow.get("on") or workflow.get(True) or {}


def _job_steps_text(job_spec: dict) -> str:
    """Every `run:` and `uses:` string in a job's steps, joined."""
    parts = []
    for step in job_spec.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        parts.append(str(step.get("run", "")))
        parts.append(str(step.get("uses", "")))
    return "\n".join(parts)


def _all_jobs_text(workflow: dict) -> str:
    return "\n".join(_job_steps_text(job) for job in workflow["jobs"].values())


def _job_calling_tests_workflow(workflow: dict) -> str | None:
    """Name of the job that invokes tests.yml as a reusable workflow, if any."""
    for name, spec in workflow["jobs"].items():
        uses = spec.get("uses")
        if isinstance(uses, str) and uses.endswith("workflows/tests.yml"):
            return name
    return None


def _job_matching(workflow: dict, needle: str) -> str | None:
    """Name of the job whose steps mention `needle`, if any."""
    for name, spec in workflow["jobs"].items():
        if needle in _job_steps_text(spec):
            return name
    return None


def _needs(job_spec: dict) -> list[str]:
    needs = job_spec.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def test_tests_workflow_is_callable_by_other_workflows():
    wf = _load("tests.yml")
    assert "workflow_call" in _triggers(wf), (
        "tests.yml must declare `workflow_call` — that's the only way "
        "images.yml / android-release.yml can `needs:` it"
    )


def test_tests_workflow_actually_runs_pytest():
    wf = _load("tests.yml")
    assert "pytest" in _all_jobs_text(wf), (
        "tests.yml has a job but it doesn't invoke pytest — this is "
        "exactly the 'gate that doesn't run anything' SA-G1 describes"
    )


def test_tests_workflow_actually_runs_the_ruff_gate():
    wf = _load("tests.yml")
    text = _all_jobs_text(wf)
    assert "ruff check" in text
    # F821 (undefined name) is the class of bug that shipped two
    # NameErrors to production and is the one this gate must never
    # let regress — see the finding's evidence.
    assert "F821" in text or text.count("--select F") > 0 or "select F" in text


def test_tests_workflow_actually_runs_the_android_unit_tests():
    wf = _load("tests.yml")
    text = _all_jobs_text(wf)
    assert "testDebugUnitTest" in text or ":app:test" in text


def test_image_build_is_gated_on_the_tests_workflow():
    wf = _load("images.yml")
    tests_job = _job_calling_tests_workflow(wf)
    assert tests_job is not None, (
        "images.yml must call tests.yml as a reusable workflow"
    )
    build_job_name = _job_matching(wf, "docker/build-push-action")
    assert build_job_name is not None, "couldn't find the image build/push job"
    build_job = wf["jobs"][build_job_name]
    assert tests_job in _needs(build_job), (
        f"the '{build_job_name}' job must `needs: [{tests_job}]` — "
        "without it a red suite still produces `:latest`, which the "
        "CT's auto-update cron pulls within 15 minutes"
    )


def test_android_release_is_gated_on_the_tests_workflow():
    wf = _load("android-release.yml")
    tests_job = _job_calling_tests_workflow(wf)
    assert tests_job is not None, (
        "android-release.yml must call tests.yml as a reusable workflow"
    )
    release_job_name = _job_matching(wf, "assembleRelease")
    assert release_job_name is not None, "couldn't find the APK build job"
    release_job = wf["jobs"][release_job_name]
    assert tests_job in _needs(release_job), (
        f"the '{release_job_name}' job must `needs: [{tests_job}]`"
    )
