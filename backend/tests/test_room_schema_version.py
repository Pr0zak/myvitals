"""The Room schema version must move whenever the Room entities do.

SA-C3 added an index to the `logs` entity and left `version = 4`. Room hashes
the schema and compares that hash when it opens the file, so the mismatch threw
`IllegalStateException: Room cannot verify the data integrity` on a device
holding the older database. `fallbackToDestructiveMigration()` did NOT save it:
that only applies when the version NUMBER changes, and this change did not move
it. The database became unopenable, `SyncWorker`'s strength flush threw on every
tick, and the phone — the only path watch telemetry has into this system — sent
nothing for nine hours across two releases while reporting 13/13 permissions
granted.

Nothing in the suite could see it. The backend tests never look at Kotlin's
persistence layer, and the Android unit tests construct no database. So this
test pins a fingerprint of the entity declarations against the declared version:
change an entity and the fingerprint moves, and the only way to make the test
pass again is to bump the version deliberately — at which point you have to
decide, consciously, between writing a migration and accepting the destructive
fallback. That decision is the thing that was skipped.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

DB_KT = (
    Path(__file__).resolve().parents[2]
    / "android/app/src/main/kotlin/app/myvitals/data/AppDatabase.kt"
)

# Bump BOTH of these together, and only after deciding what happens to the
# buffered-write tables. `buffered_strength_sets` and `buffered_workout_writes`
# hold sets and status patches logged while offline; a destructive fallback
# throws away exactly the writes that could not be delivered yet.
EXPECTED_VERSION = 5
EXPECTED_ENTITY_FINGERPRINT = "acaadae565672af4"


def _source() -> str:
    assert DB_KT.is_file(), f"{DB_KT} is missing"
    return DB_KT.read_text()


def _declared_version(src: str) -> int:
    m = re.search(r"@Database\((?:.|\n)*?version\s*=\s*(\d+)", src)
    assert m, "could not find `version = N` inside the @Database annotation"
    return int(m.group(1))


def entity_fingerprint(src: str) -> str:
    """Hash every @Entity block and the data class that follows it.

    Deliberately includes indices and column declarations, because an index is
    exactly what moved last time and it is easy to read as cosmetic.
    """
    blocks = re.findall(
        r"@Entity\((?:.|\n)*?\)\s*data class \w+\((?:.|\n)*?\n\)", src
    )
    assert blocks, "found no @Entity declarations to fingerprint"
    normalised = "\n".join(
        re.sub(r"//.*", "", re.sub(r"\s+", " ", b)).strip() for b in sorted(blocks)
    )
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def test_declared_version_matches_the_one_this_test_pins():
    assert _declared_version(_source()) == EXPECTED_VERSION, (
        "AppDatabase's @Database version changed without updating "
        "EXPECTED_VERSION here. If that was deliberate, update this test AND "
        "confirm a Migration exists for the step — see MIGRATION_4_5."
    )


def test_entities_have_not_changed_without_a_version_bump():
    fingerprint = entity_fingerprint(_source())
    assert fingerprint == EXPECTED_ENTITY_FINGERPRINT, (
        f"The Room entities changed (fingerprint {fingerprint}) while "
        f"version stayed at {EXPECTED_VERSION}. Room compares a schema hash on "
        "open, so shipping this makes the database unopenable on any device "
        "holding the old one — and fallbackToDestructiveMigration does NOT "
        "cover it, because that only fires when the version number moves. "
        "Bump the version, add a Migration (dropping the buffered-write tables "
        "loses offline sets and status patches), then update "
        "EXPECTED_VERSION and EXPECTED_ENTITY_FINGERPRINT here."
    )


def test_a_migration_exists_for_every_version_step():
    src = _source()
    version = _declared_version(src)
    declared = {
        (int(a), int(b))
        for a, b in re.findall(r"Migration\((\d+)\s*,\s*(\d+)\)", src)
    }
    registered = re.search(r"\.addMigrations\(([^)]*)\)", src)
    assert registered, (
        "no .addMigrations(...) call — a Migration that is never registered "
        "does nothing, which is indistinguishable from not writing one"
    )
    # Only the most recent step is pinned: earlier versions predate this guard
    # and the project accepted destructive fallback for them on purpose.
    assert (version - 1, version) in declared, (
        f"no Migration({version - 1}, {version}) found. If the destructive "
        "fallback is genuinely the right call for this step, say so in a "
        "comment and relax this test — but do it deliberately."
    )
    assert f"MIGRATION_{version - 1}_{version}" in registered.group(1), (
        f"MIGRATION_{version - 1}_{version} exists but is not passed to "
        ".addMigrations()"
    )
