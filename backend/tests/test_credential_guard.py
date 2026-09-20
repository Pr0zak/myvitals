"""The credential guard was replaced with _credentials_missing.

This test ensures the old pattern `cfg.anthropic_api_key` used as a
truthiness guard (not comparison) does not regress elsewhere in the codebase.
All AI surfaces that check credentials should use `_credentials_missing(cfg)`
instead, which correctly handles all provider types (Anthropic, claude_cli,
openai_compatible, ollama) and their auth requirements.
"""
from __future__ import annotations

import pathlib
import re


def _find_old_guards() -> list[str]:
    """Find lines that use cfg.anthropic_api_key as a truthiness guard.

    We're looking for patterns like:
    - if not cfg.anthropic_api_key:
    - if cfg.anthropic_api_key:
    - and not cfg.anthropic_api_key
    - or cfg.anthropic_api_key

    But NOT:
    - cfg.anthropic_api_key == something
    - cfg.anthropic_api_key is None
    - cfg.anthropic_api_key is not None
    - In integrations/llm/ (where _credentials_missing is defined)
    """
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"

    bad_patterns = [
        r'if\s+(not\s+)?cfg\.anthropic_api_key\s*:',
        r'and\s+(not\s+)?cfg\.anthropic_api_key\s*(?=\)|,|;|$)',
        r'or\s+(not\s+)?cfg\.anthropic_api_key\s*(?=\)|,|;|$)',
    ]

    bad_lines = []

    for path in sorted(src.rglob("*.py")):
        # Skip integrations/llm/ - that's where _credentials_missing lives
        if "integrations/llm" in str(path):
            continue
        # Skip alembic
        if "alembic" in path.parts:
            continue

        content = path.read_text()
        for i, line in enumerate(content.split("\n"), 1):
            # Skip lines that have comparison operators - those are intentional
            if any(op in line for op in [" == ", " is ", "is None", "is not None"]):
                continue

            for pattern in bad_patterns:
                if re.search(pattern, line):
                    rel_path = path.relative_to(src.parent.parent)
                    bad_lines.append(f"{rel_path}:{i} — {line.strip()}")

    return bad_lines


def test_no_old_credential_guard_pattern():
    """The old `cfg.anthropic_api_key` truthiness guard should not exist.

    This prevents regression of the SA-S2/SA-S3 findings: the provider
    may not have an API key (e.g. claude_cli uses OAuth), so checking for
    a key is incorrect for most providers.
    """
    bad = _find_old_guards()
    assert not bad, "Found old credential guard pattern:\n" + "\n".join(bad)
