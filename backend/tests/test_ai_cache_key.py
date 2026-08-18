"""AI cache keys and standing instructions — TD-9.

The bug: `ai_summaries` is keyed by payload hash so the same data never
re-bills, which is right. But tone was not in the key, and tone changes the
answer. Switching Supportive to Blunt returned the stale Supportive card.

It was not a uniform oversight, which is the interesting part. The five
/coach/* endpoints hashed {"kind", "tone", "p"} correctly; the seven older
ones -- /explain, /verdict, /summary and the four /strength/* surfaces --
hashed the bare payload. The author knew the rule and missed the earlier call
sites, which is the argument for one function rather than a convention.
"""

from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

from myvitals.api.ai import _ai_cache_key
from myvitals.integrations import claude


def _cfg(tone="supportive", instructions=None):
    return SimpleNamespace(tone=tone, custom_instructions=instructions)


PAYLOAD = {"hrv": 62, "rhr": 51}


def test_tone_changes_the_cache_key():
    """The original bug, stated directly."""
    supportive = _ai_cache_key(_cfg("supportive"), "summary", PAYLOAD)
    blunt = _ai_cache_key(_cfg("blunt"), "summary", PAYLOAD)
    assert supportive != blunt


def test_standing_instructions_change_the_cache_key():
    """An instruction can change the recommendation, not merely its wording,
    so a cached card produced without it is the wrong answer."""
    plain = _ai_cache_key(_cfg(), "summary", PAYLOAD)
    with_note = _ai_cache_key(
        _cfg(instructions="Rehabbing a left shoulder — no overhead pressing."),
        "summary", PAYLOAD,
    )
    assert plain != with_note


def test_whitespace_only_instructions_do_not_bust_the_cache():
    """Opening the field, adding a space and saving must not re-bill every
    surface. Trimmed on the way into the key and on the way into the prompt."""
    assert _ai_cache_key(_cfg(), "summary", PAYLOAD) == \
        _ai_cache_key(_cfg(instructions="   \n  "), "summary", PAYLOAD)


def test_same_inputs_produce_the_same_key():
    """The cache has to actually hit, or the daily limit stops meaning
    anything."""
    assert _ai_cache_key(_cfg(), "summary", PAYLOAD) == \
        _ai_cache_key(_cfg(), "summary", dict(PAYLOAD))


def test_kind_separates_surfaces_built_from_the_same_payload():
    assert _ai_cache_key(_cfg(), "summary", PAYLOAD) != \
        _ai_cache_key(_cfg(), "verdict", PAYLOAD)


def test_a_config_without_the_column_still_hashes():
    """Mid-rollout the app can run against a database that has not taken
    migration 0049 yet. That must degrade to "no instructions", not 500."""
    legacy = SimpleNamespace(tone="blunt")
    assert _ai_cache_key(legacy, "summary", PAYLOAD)


# --------------------------------------------------------------------------
# The prompt side
# --------------------------------------------------------------------------

def test_instructions_are_appended_under_a_fixed_heading():
    """Appended, never prepended: they augment the base rules rather than
    replacing them, and a prompt cannot be made to look like it opens with
    user-supplied text."""
    out = claude.personalise("BASE RULES", _cfg(instructions="No overhead pressing."))
    assert out.startswith("BASE RULES")
    assert "## Additional instructions from the user" in out
    assert out.index("BASE RULES") < out.index("No overhead pressing.")


def test_instructions_are_length_capped():
    """Unbounded text in the cached prefix would inflate every request, and
    this is a prompt-injection surface aimed at the model's own guardrails."""
    out = claude.personalise("BASE", _cfg(instructions="x" * 5000))
    assert out.count("x") == claude.MAX_CUSTOM_INSTRUCTIONS


def test_empty_instructions_leave_the_prompt_byte_identical():
    """Prompt caching depends on the prefix being stable. A user who has set
    nothing must get exactly the prompt they got before this feature."""
    assert claude.personalise("BASE", _cfg()) == "BASE"
    assert claude.personalise("BASE", _cfg(instructions="")) == "BASE"
    assert claude.personalise("BASE", None) == "BASE"


# --------------------------------------------------------------------------
# Structural guards — the reason the bug survived as long as it did
# --------------------------------------------------------------------------

def _ai_source() -> str:
    import myvitals.api.ai as mod
    return pathlib.Path(mod.__file__).read_text()


def test_no_endpoint_builds_a_cache_key_by_hand():
    """Every surface must key through _ai_cache_key.

    A bare hash_payload(payload) is exactly what left seven endpoints
    tone-blind, and it looks entirely reasonable at the call site.
    """
    offenders = [
        f"line {i + 1}: {ln.strip()}"
        for i, ln in enumerate(_ai_source().splitlines())
        if re.search(r"payload_hash\s*=\s*hash_payload\(", ln)
    ]
    assert not offenders, (
        "These build a cache key without the tone and standing instructions, "
        "so changing either returns a stale card. Use _ai_cache_key(cfg, "
        "kind, payload):\n  " + "\n  ".join(offenders)
    )


def test_every_system_prompt_carries_the_config():
    """_cached_system(text) without cfg silently drops the user's standing
    instructions for that one surface — the same class of omission as the
    cache-key bug, in the other direction."""
    src = pathlib.Path(claude.__file__).read_text()
    offenders = []
    for i, ln in enumerate(src.splitlines()):
        if "_cached_system(" not in ln or "def _cached_system" in ln:
            continue
        if not re.search(r"_cached_system\(.*,\s*cfg\)", ln):
            offenders.append(f"line {i + 1}: {ln.strip()}")
    assert not offenders, (
        "These build a system prompt without passing cfg, so the user's "
        "standing instructions are dropped:\n  " + "\n  ".join(offenders)
    )
