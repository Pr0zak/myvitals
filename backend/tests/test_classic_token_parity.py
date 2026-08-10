"""`ClassicTokens` must stay byte-identical to the classic `MV` palette.

This lives in the backend suite because pytest is the repo's only enforced
gate; the thing it guards is in the Android tree. `scripts/parity_check.py`
already sets the precedent of a Python check reading both trees.

Why it matters: the vitals detail screens were migrated off hard-coded `MV.*`
onto `LocalAppTokens`, so the neon shell can restyle them. The entire safety
argument for that migration is that the DEFAULT token values are exactly what
the screens rendered before, which confines the risk to the neon shell. If
someone "tidies" a hex value in one file and not the other, the classic shell
changes appearance silently and nothing else would catch it — there is no
screenshot test on this project.
"""
import pathlib
import re

import pytest

UI = (pathlib.Path(__file__).resolve().parents[2]
      / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals" / "ui")
THEME = UI / "Theme.kt"
TOKENS = UI / "AppTokens.kt"

# (MV name, AppTokens field). Only the tokens the shared screens use.
PAIRS = [
    ("Bg", "bg"),
    ("SurfaceContainer", "surfaceContainer"),
    ("OnSurface", "onSurface"),
    ("OnSurfaceVariant", "onSurfaceVariant"),
    ("OnSurfaceDim", "onSurfaceDim"),
    ("Red", "red"),
]


def _colour(src: str, name: str, after: str) -> str | None:
    """The 0xAARRGGBB literal assigned to `name`, searching after `after`.

    Anchoring on the containing block matters: `MV` and the Material colour
    scheme below it both assign similar names.
    """
    if after not in src:
        return None
    tail = src[src.index(after):]
    m = re.search(rf"\b{name}\s*=\s*Color\(0x([0-9A-Fa-f]{{8}})\)", tail)
    return m.group(1).upper() if m else None


def test_the_files_this_guard_reads_still_exist():
    """A guard that silently passes when its inputs move is worthless."""
    assert THEME.is_file(), f"missing {THEME}"
    assert TOKENS.is_file(), f"missing {TOKENS}"


@pytest.mark.parametrize("mv_name,token_field", PAIRS)
def test_classic_tokens_match_the_mv_palette(mv_name, token_field):
    theme = THEME.read_text()
    tokens = TOKENS.read_text()

    mv = _colour(theme, mv_name, "object MV {")
    classic = _colour(tokens, token_field, "val ClassicTokens")

    assert mv is not None, f"couldn't find MV.{mv_name} in Theme.kt"
    assert classic is not None, (
        f"couldn't find ClassicTokens.{token_field} in AppTokens.kt"
    )
    assert mv == classic, (
        f"MV.{mv_name} is 0x{mv} but ClassicTokens.{token_field} is 0x{classic}. "
        "The shared detail screens render with ClassicTokens outside the neon "
        "shell, so this divergence silently restyles the classic shell."
    )
