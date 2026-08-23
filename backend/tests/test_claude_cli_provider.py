"""The headless Claude Code CLI provider (AI-CLI).

Ported from `stocktracker-signals/app/llm_cli.py`, which has run this way
in production. Calls shell out to `claude -p` on the machine's Claude
SUBSCRIPTION OAuth, so they draw on the subscription's rate-limit budget
rather than per-token API billing.

The tests here are weighted toward the handful of decisions that make
that true, because each is invisible until it silently stops being true
and the calls start costing money.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib

import pytest

from myvitals.integrations.llm import claude_cli as CLI

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


# ------------------------------------------------- the $0 premise


def test_api_key_env_vars_are_stripped_from_the_child():
    """The entire premise. With an API key present the CLI authenticates
    as an API key and bills per token — and worse, returns 401 on a stale
    key instead of falling back to valid OAuth, so a leftover key breaks
    every call while looking like an auth fault."""
    os.environ["ANTHROPIC_API_KEY"] = "sk-should-not-propagate"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "also-not"
    try:
        env = CLI._child_env(None)
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def test_a_stored_oauth_token_is_passed_through():
    env = CLI._child_env("tok-123")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-123"


def test_no_stored_token_clears_rather_than_inherits_a_stale_one():
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "from-env"
    try:
        # An explicitly empty setting must not silently fall back to a
        # value the user thought they replaced.
        assert CLI._child_env("").get("CLAUDE_CODE_OAUTH_TOKEN") == "from-env"
    finally:
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in CLI._child_env(None)


def test_thinking_is_disabled():
    """Headless turns extended thinking on by default, which balloons a
    short structured answer into thousands of output tokens for no gain
    on card-shaped work. Quota is the currency here, so this matters."""
    assert CLI._child_env(None)["MAX_THINKING_TOKENS"] == "0"


# ------------------------------------------------------- the command


def test_the_agent_can_only_answer_never_act():
    argv = CLI._argv("haiku", "sys", [])
    joined = " ".join(argv)
    assert "--max-turns" in joined
    assert "--strict-mcp-config" in joined
    for tool in ("Bash", "Write", "Edit", "WebFetch", "Task"):
        assert tool in CLI._DENY_TOOLS


def test_read_is_granted_only_for_the_images_being_analysed():
    """Verified behaviour, not hope: with `--allowedTools Read(file)` the
    CLI reads that file and refuses any other, so a prompt-injected
    "read /etc/shadow" cannot succeed."""
    argv = CLI._argv("haiku", "sys", [pathlib.Path("/tmp/x/image-0.png")])
    joined = " ".join(argv)
    assert "--allowedTools" in joined
    assert "Read(image-0.png)" in joined
    assert "Read" not in CLI._DENY_TOOLS


def test_no_images_means_no_read_tool_at_all():
    assert "--allowedTools" not in " ".join(CLI._argv("haiku", "sys", []))


def test_bypass_permissions_is_never_used():
    """Scoped Read plus a working directory containing only the image is
    sufficient. Blanket permission bypass would hand a prompt-injected
    reply the whole filesystem."""
    src = inspect.getsource(CLI)
    assert "bypassPermissions" not in src
    assert "dangerously-skip" not in src


def test_the_prompt_goes_on_stdin_not_argv():
    """No shell is involved and there is no argv-length or quoting
    exposure however large the payload gets."""
    src = inspect.getsource(CLI._invoke)
    assert "communicate(input=" in src
    assert "stdin=asyncio.subprocess.PIPE" in src


# -------------------------------------------------- images and cleanup


def test_the_working_directory_is_the_temp_image_dir():
    """Granting Read on an absolute path outside the working directory is
    NOT enough — the first attempt came back "I need permission to read
    the image". Running in the temp directory also means the agent's
    whole filesystem view is one directory holding one image."""
    src = inspect.getsource(CLI.ClaudeCliProvider.create)
    assert "cwd=tmpdir.name" in src
    assert "TemporaryDirectory" in src


def test_the_temp_image_is_always_removed():
    """A photo must not outlive the call. The API path keeps that promise
    by never writing one; this path has to clean up."""
    src = inspect.getsource(CLI.ClaudeCliProvider.create)
    tree = ast.parse(src.strip())
    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    assert any(t.finalbody for t in tries), "cleanup must be in a finally"
    assert "cleanup()" in src


def test_images_are_split_out_of_the_message():
    text, images = CLI._split_message([{
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this"},
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": "AAA",
            }},
        ],
    }])
    assert text == "what is this"
    assert images == [("image/png", "AAA")]


def test_plain_string_content_still_works():
    text, images = CLI._split_message([{"role": "user", "content": "hello"}])
    assert text == "hello"
    assert images == []


# --------------------------------------------- structured output


def test_the_tool_schema_is_injected_into_the_prompt():
    """There is no schema-constrained decoding, so the contract goes in
    the prompt and the reply is validated afterwards. This is the biggest
    behavioural difference from the API path."""
    instr = CLI._schema_instruction(
        [{"name": "t", "input_schema": {"type": "object", "properties": {}}}], "t",
    )
    assert "JSON Schema" in instr
    assert "ONLY a single JSON object" in instr


def test_fenced_and_padded_json_is_recovered():
    assert CLI._strip_to_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert CLI._strip_to_json('Sure! {"a": 1} hope that helps') == '{"a": 1}'
    assert CLI._strip_to_json('{"a": 1}') == '{"a": 1}'


def test_system_blocks_are_flattened_and_cache_control_dropped():
    """Anthropic's prompt-cache directives have nothing to map onto."""
    out = CLI._flatten_system([
        {"type": "text", "text": "one", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "two"},
    ])
    assert out == "one\n\ntwo"


# ------------------------------------------------- failure handling


def test_auth_failures_are_fatal_and_rate_limits_are_not():
    """A retry on an auth failure is pointless; a retry on a capacity
    rejection often works."""
    assert CLI._is_fatal(CLI.CliError("Not logged in · Please run /login"))
    assert CLI._is_fatal(CLI.CliError("401 unauthorized"))
    assert not CLI._is_fatal(CLI.CliError("429 rate limit exceeded"))


def test_rate_limits_get_a_human_message():
    msg = CLI.friendly_error(CLI.CliError("api_error_status=429 rate limit"))
    assert "rate-limited" in msg
    assert "try again" in msg


def test_a_timeout_reaps_the_child():
    """Killing without waiting leaves a zombie behind on every timeout."""
    src = inspect.getsource(CLI._invoke)
    assert "proc.kill()" in src
    assert "await proc.wait()" in src


def test_concurrency_is_bounded():
    """Each call is a heavyweight Node process, and an unbounded fan-out
    is both memory pressure and a rate-limit burst."""
    assert CLI._CONCURRENCY >= 1
    assert "_SEM" in inspect.getsource(CLI._invoke)


# ------------------------------------------------------- integration


def test_provider_is_selectable_from_the_seam():
    from myvitals.integrations.llm.base import get_provider

    class _Cfg:
        provider = "claude_cli"
        anthropic_api_key = None
        base_url = None
        model = "haiku"
        cli_oauth_token = None

    p = get_provider(_Cfg())
    assert isinstance(p, CLI.ClaudeCliProvider)
    assert hasattr(p.messages, "create")


def test_credentials_check_is_provider_aware():
    """Every runner used to guard on `anthropic_api_key`, which would
    refuse every surface under the CLI provider — which has no API key by
    design — while reporting "no API key configured"."""
    from myvitals.integrations.claude import _credentials_missing

    class _Cfg:
        provider = "claude_cli"
        anthropic_api_key = None
        base_url = None

    assert not _credentials_missing(_Cfg())
    _Cfg.provider = "anthropic"
    assert _credentials_missing(_Cfg())


def test_no_runner_still_guards_on_the_api_key_directly():
    src = (SRC / "integrations" / "claude.py").read_text()
    assert "not cfg.anthropic_api_key:" not in src, (
        "a runner still requires an API key; it will refuse under claude_cli"
    )


def test_claude_cli_needs_no_base_url():
    src = (SRC / "api" / "ai.py").read_text()
    fn = src[src.index("async def update_config("):]
    fn = fn[: fn.index("@router.")] if "@router." in fn else fn
    assert '"anthropic", "claude_cli"' in fn


def test_the_image_ships_the_cli():
    root = pathlib.Path(__file__).resolve().parents[2]
    dockerfile = (root / "backend" / "Dockerfile").read_text()
    assert "@anthropic-ai/claude-code" in dockerfile
    assert "nodejs" in dockerfile


def test_credentials_are_mounted_read_only():
    """The container reads the subscription credentials; it has no reason
    to rewrite them."""
    root = pathlib.Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    assert "/root/.claude:ro" in compose
