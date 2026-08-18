"""The LLM provider seam — TD-8.

`integrations/claude.py` constructed AsyncAnthropic at each of its nineteen
call sites, so Anthropic was not a choice the app made once — it was baked
into every surface. These tests pin the two properties that make the seam
worth having rather than merely possible:

1. The safety machinery sits ABOVE the seam and is untouched. Payload-hash
   caching, the daily quota and the bounded payload builders do not know or
   care which provider answers, so swapping one changes who replies, not what
   is asked or how often.
2. The default path is genuinely unchanged. A config that never opens the new
   setting gets Anthropic, exactly as before.
"""

from __future__ import annotations

import inspect
import json
import pathlib
from types import SimpleNamespace

import pytest

from myvitals.integrations import claude
from myvitals.integrations.llm import LlmError, get_provider, validate_base_url
from myvitals.integrations.llm.openai_compat import (
    _flatten_system, _map_tool_choice, _map_tools,
)


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------

def test_an_unset_provider_still_means_anthropic():
    """Every existing row has a null provider. Nothing is migrated, so the
    default path must be bit-for-bit what it always was."""
    from myvitals.integrations.llm.anthropic_provider import AnthropicProvider

    cfg = SimpleNamespace(anthropic_api_key="sk-test", model="claude-haiku-4-5")
    assert isinstance(get_provider(cfg), AnthropicProvider)


def test_an_unknown_provider_is_refused_loudly():
    cfg = SimpleNamespace(provider="gpt5-please", anthropic_api_key="x")
    with pytest.raises(LlmError):
        get_provider(cfg)


def test_openai_compatible_requires_a_usable_base_url():
    cfg = SimpleNamespace(provider="ollama", base_url="", anthropic_api_key="")
    with pytest.raises(LlmError):
        get_provider(cfg)


# --------------------------------------------------------------------------
# SSRF surface
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://internal/",
    "http://user:hunter2@10.0.0.5/v1",
    "",
    "not-a-url",
])
def test_base_urls_that_are_never_legitimate_are_rejected(url):
    """This runs on a container that can reach the whole Proxmox cluster."""
    with pytest.raises(LlmError):
        validate_base_url(url)


def test_a_lan_address_is_allowed_because_that_is_the_point():
    """Blocking RFC1918 would defeat the feature: pointing at Ollama on the
    LAN is the entire reason for it. The mitigation is that only the single
    authenticated user can set this, and that it is logged when used."""
    assert validate_base_url("http://10.0.0.5:11434/v1/") == "http://10.0.0.5:11434/v1"


# --------------------------------------------------------------------------
# The translation layer
# --------------------------------------------------------------------------

def test_system_blocks_flatten_and_the_cache_directive_is_dropped():
    """The concrete form of "prompt caching is Anthropic-only": there is
    nothing on the OpenAI side to map cache_control to, so the same
    conversation costs full input rate every call. The Settings copy says so
    rather than letting the bill explain it."""
    blocks = [{"type": "text", "text": "RULES", "cache_control": {"type": "ephemeral"}}]
    assert _flatten_system(blocks) == "RULES"
    assert _flatten_system("plain") == "plain"
    assert _flatten_system(None) == ""


def test_anthropic_tools_map_to_openai_functions():
    tools = [{
        "name": "give_analysis",
        "description": "d",
        "input_schema": {"type": "object", "properties": {"headline": {"type": "string"}}},
    }]
    mapped = _map_tools(tools)
    assert mapped[0]["type"] == "function"
    assert mapped[0]["function"]["name"] == "give_analysis"
    # The schema has to travel intact or structured output degrades to prose.
    assert mapped[0]["function"]["parameters"]["properties"]["headline"]["type"] == "string"


def test_forced_tool_choice_maps_across():
    assert _map_tool_choice({"type": "tool", "name": "give_analysis"}) == {
        "type": "function", "function": {"name": "give_analysis"},
    }
    assert _map_tool_choice(None) is None


# --------------------------------------------------------------------------
# Structural — the safety machinery must stay above the seam
# --------------------------------------------------------------------------

def test_no_call_site_constructs_a_provider_directly():
    """A new surface that reaches for AsyncAnthropic bypasses the setting and
    silently pins itself to one vendor — which is the state this task
    started from."""
    src = pathlib.Path(claude.__file__).read_text()
    assert "AsyncAnthropic(" not in src, (
        "integrations/claude.py must construct providers via get_provider(cfg)"
    )


def test_quota_and_caching_do_not_know_about_providers():
    """The three things that make the AI layer safe live above the seam.

    If provider selection ever leaks into the quota check or the cache key,
    swapping providers would start changing how often the app calls out and
    what it re-bills — which is exactly what must not happen.
    """
    from myvitals.api import ai as ai_api

    for fn in (ai_api._check_and_bump_quota, ai_api._ai_cache_key):
        src = inspect.getsource(fn)
        assert "provider" not in src, f"{fn.__name__} must be provider-agnostic"


def test_malformed_tool_arguments_degrade_rather_than_raise():
    """Weak local models emit invalid JSON often enough that this cannot be
    an exception path. An empty dict is the same signal the call sites
    already handle for "no tool call happened"."""
    src = pathlib.Path(
        claude.__file__,
    ).parent.joinpath("llm", "openai_compat.py").read_text()
    assert "json.JSONDecodeError" in src
    assert "parsed = {}" in src
    # And the call sites really do treat an empty tool input as a fallback
    # rather than a crash.
    assert "if not tool_input:" in pathlib.Path(claude.__file__).read_text()


def test_usage_keys_are_renamed_so_quota_accounting_survives():
    src = pathlib.Path(
        claude.__file__,
    ).parent.joinpath("llm", "openai_compat.py").read_text()
    assert "prompt_tokens" in src and "completion_tokens" in src
    assert "input_tokens=" in src and "output_tokens=" in src


def test_the_response_shape_matches_what_call_sites_read():
    """The seam is Anthropic-shaped on purpose: every call site already reads
    resp.content blocks with a `type`, resp.model and resp.usage.*_tokens, so
    presenting that shape is what kept the nineteen sites to a two-line
    change each. A neutral third shape would have meant rewriting every
    extraction path in a 3000-line module for no behavioural gain."""
    from myvitals.integrations.llm.openai_compat import (
        _Response, _TextBlock, _ToolUseBlock,
    )

    r = _Response(content=[_TextBlock(text="hi"), _ToolUseBlock(name="t", input={"a": 1})])
    assert r.content[0].type == "text" and r.content[0].text == "hi"
    assert r.content[1].type == "tool_use" and r.content[1].name == "t"
    assert json.dumps(r.content[1].input) == '{"a": 1}'
    assert r.usage.input_tokens == 0 and r.usage.output_tokens == 0
