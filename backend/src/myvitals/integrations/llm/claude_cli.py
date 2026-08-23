"""Headless Claude Code CLI, presented in the Anthropic shape.

When `ai_config.provider == "claude_cli"` every AI surface routes here
instead of the Messages API. Calls shell out to
`claude -p --output-format json` using the machine's logged-in
*subscription* OAuth credentials, so they draw on the Claude
subscription's rate-limit budget rather than per-token API billing. Real
spend is $0; the cost the CLI reports is its own notional
API-equivalent figure and is passed through only so the usage numbers
above this layer keep working.

Ported from `stocktracker-signals/app/llm_cli.py`, which has run this way
in production long enough to have found the sharp edges. The techniques
that matter are carried over rather than reinvented, and each is
commented where it is not obvious.

## Trade-offs against the API path

* **No schema-constrained decoding.** Anthropic's forced tool-use
  guarantees a well-formed tool call; the CLI has no equivalent. The tool
  schema is injected into the system prompt instead, the reply is parsed
  as JSON, and a malformed reply is retried once with a stricter nudge.
  A second failure degrades to "no tool call happened", which every call
  site in claude.py already handles.
* **~14k tokens of agent-harness overhead per cold call**, cached for
  about an hour afterwards. That is quota, not dollars.
* **Higher latency** — each call spawns a Node agent process.
* **Prompt caching directives are dropped.** There is nothing to map
  `cache_control` onto; the CLI does its own caching.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: The binary and a hard wall-clock cap, both overridable from the
#: container env so a slow model does not need a code change.
_CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
_TIMEOUT_S = float(os.environ.get("CLAUDE_CLI_TIMEOUT", "180"))

#: Cap concurrent `claude` processes. Unlike the pooled-HTTP API path,
#: each call is a heavyweight Node agent process. Without this, a screen
#: that fires several AI cards at once would spawn them all together —
#: memory pressure plus a burst the subscription rate-limiter rejects,
#: failing most of them.
_CONCURRENCY = max(1, int(os.environ.get("CLAUDE_CLI_CONCURRENCY", "2")))
_SEM = asyncio.Semaphore(_CONCURRENCY)

#: Env vars that make the CLI authenticate as an API KEY — per-token
#: billing — in preference to the machine's subscription OAuth. This
#: provider's entire premise is $0 subscription use, so they are stripped
#: from the child environment.
#:
#: This is not belt-and-braces. With a key set, headless `claude` returns
#: 401 on a bad key rather than falling back to valid OAuth, so a stale
#: key in the environment would break every call while looking like an
#: auth problem. Stripping forces OAuth and fails loudly if it is absent.
_AUTH_ENV_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

#: Built-in tools denied so the single-turn agent can only ANSWER. This
#: is a text completion, never an action. `Read` is deliberately absent
#: from the deny list and instead granted per-call, scoped to exactly the
#: image file being analysed — see `_argv`.
_DENY_TOOLS = (
    "Bash,Edit,Write,Glob,Grep,WebFetch,WebSearch,Task,TodoWrite,NotebookEdit"
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class CliError(RuntimeError):
    """A headless claude call failed: spawn, timeout, non-zero exit, an
    error envelope, or output that could not be read."""


# ---------------------------------------------------------------- shape
#
# Mirrors openai_compat: the call sites read `resp.content` as blocks
# with a `type` of "text" or "tool_use", plus `resp.model` and
# `resp.usage`. Presenting that shape is what keeps claude.py unchanged.


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _Response:
    content: list[Any] = field(default_factory=list)
    model: str = ""
    usage: _Usage = field(default_factory=_Usage)


def _child_env(oauth_token: str | None) -> dict[str, str]:
    """Child environment: OAuth only, never an inherited API key."""
    env = {k: v for k, v in os.environ.items() if k not in _AUTH_ENV_STRIP}
    tok = (oauth_token or "").strip() or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    else:
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    # Headless turns extended thinking on by default, which balloons a
    # short structured answer into thousands of output tokens for no
    # quality gain on the card-shaped work this app does.
    env["MAX_THINKING_TOKENS"] = "0"
    return env


def _flatten_system(system: Any) -> str:
    """Anthropic's system blocks (with cache_control) down to plain text."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for b in system:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n\n".join(p for p in parts if p)
    return str(system)


def _split_message(messages: list[dict[str, Any]]) -> tuple[str, list[tuple[str, str]]]:
    """Return (prompt text, [(media_type, base64), ...]) from the messages.

    Only the user turn matters: this provider is single-turn by
    construction (`--max-turns 1`), which every call site already is.
    """
    text_parts: list[str] = []
    images: list[tuple[str, str]] = []
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, str):
            text_parts.append(content)
            continue
        for b in content or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                text_parts.append(b.get("text", ""))
            elif b.get("type") == "image":
                src = b.get("source") or {}
                if src.get("type") == "base64":
                    images.append(
                        (src.get("media_type", "image/png"), src.get("data", "")),
                    )
    return "\n\n".join(p for p in text_parts if p), images


def _schema_instruction(tools: list[dict[str, Any]] | None, forced: str | None) -> str:
    """Turn a tool definition into an in-prompt output contract.

    The CLI cannot be forced into a well-formed tool call the way the
    Messages API can, so the schema goes in the prompt and the reply is
    validated afterwards. This is the single biggest behavioural
    difference from the API path.

    The countermand at the top is load-bearing, and cost a debugging
    session to find. Every system prompt in claude.py ends with some form
    of "Answer only via the `give_x` tool" — correct for the Messages API,
    and actively harmful here: the agent obeys it, tries to call a tool
    that does not exist in this harness, exhausts its turn budget and
    exits 1 with `stop_reason: "tool_use"` and an EMPTY stderr. The only
    visible symptom is a 500. So the instruction has to be explicitly
    revoked rather than merely followed by a different one.
    """
    if not tools:
        return ""
    tool = next(
        (t for t in tools if not forced or t.get("name") == forced), tools[0],
    )
    schema = json.dumps(tool.get("input_schema") or {})
    return (
        "\n\n---\n"
        "IMPORTANT — THIS OVERRIDES ANY EARLIER INSTRUCTION ABOUT TOOLS.\n"
        "You have NO tools available in this session. Any instruction above "
        "telling you to answer 'via the tool' or to call a named function is "
        "obsolete: ignore it. Do not attempt any tool or function call.\n\n"
        "OUTPUT FORMAT (STRICT): Respond with ONLY a single JSON object that "
        "validates against the JSON Schema below — the same object you would "
        "have passed as that tool's input. No prose, no explanation, no "
        "markdown fences.\nJSON Schema:\n" + schema
    )


def _strip_to_json(text: str) -> str:
    """Carve a JSON object out of a reply that may be fenced or padded."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = _FENCE_RE.sub("", t).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            t = t[i:j + 1]
    return t


#: Failures worth distinguishing. A fatal one (auth, missing binary) will
#: fail identically on retry; a transient one (rate, capacity) may not.
_FATAL_HINTS = (
    "not logged in", "/login", "claude cli not found", "invalid api key",
    "authentication_error", "unauthorized", "401",
)
_RATE_HINTS = (
    "rate limit", "rate-limit", "429", "overloaded", "usage limit",
    "capacity", "quota", "too many requests",
)


def _is_fatal(err: Exception) -> bool:
    return any(h in str(err).lower() for h in _FATAL_HINTS)


def friendly_error(err: Exception) -> str:
    """A raw CLI failure, in words worth showing a person."""
    if any(h in str(err).lower() for h in _RATE_HINTS):
        return (
            "the AI is temporarily rate-limited on the Claude subscription — "
            "try again in a minute"
        )
    return str(err)


def _argv(model: str, system: str, image_paths: list[Path]) -> list[str]:
    """The command line.

    `Read` is granted ONLY for the exact image files being analysed. That
    scoping is verified behaviour, not hope: with
    `--allowedTools "Read(/path/to/one.png)"` the CLI reads that file and
    refuses any other, so a prompt-injected "read /etc/shadow" cannot
    succeed even though the agent nominally has a Read tool.
    """
    argv = [
        _CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--max-turns", "2" if image_paths else "1",
        "--strict-mcp-config",
        "--exclude-dynamic-system-prompt-sections",
        "--disallowedTools", _DENY_TOOLS,
    ]
    if image_paths:
        # Bare filenames: the process runs IN the directory holding them,
        # so this grants Read on those files and nothing else.
        argv += [
            "--allowedTools",
            ",".join(f"Read({p.name})" for p in image_paths),
        ]
    return argv


async def _invoke(
    model: str,
    system: str,
    prompt: str,
    image_paths: list[Path],
    oauth_token: str | None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """One headless call. Returns the parsed envelope, or raises CliError.

    `cwd` is the temp directory holding the image, when there is one. The
    CLI scopes file access to its working directory, so granting
    `Read(/tmp/elsewhere/x.png)` alone is not enough — the first attempt
    at this came back "I need permission to read the image". Running IN
    the temp directory also means the agent's entire filesystem view is a
    directory containing nothing but the image it was asked to look at.
    """
    argv = _argv(model, system, image_paths)
    async with _SEM:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_child_env(oauth_token),
                cwd=cwd,
            )
        except FileNotFoundError as e:
            raise CliError(
                f"claude CLI not found ({_CLAUDE_BIN!r}) — is it installed "
                "and on PATH inside the backend container?"
            ) from e

        try:
            # The prompt goes on STDIN, never argv: no shell is involved
            # and there is no argv-length or quoting exposure however
            # large the payload gets.
            out, err = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()), timeout=_TIMEOUT_S,
            )
        except asyncio.TimeoutError as e:
            proc.kill()
            try:
                await proc.wait()   # reap, so a timeout does not leak a zombie
            except Exception:  # noqa: BLE001
                pass
            raise CliError(f"claude CLI timed out after {_TIMEOUT_S:.0f}s") from e

    if proc.returncode != 0:
        detail = err.decode(errors="replace")[:300].strip()
        # The useful message ("Not logged in", model/auth problems) is
        # usually in the JSON envelope on stdout rather than stderr, which
        # carries only the non-fatal tool-deny warnings.
        try:
            msg = (json.loads(out.decode()).get("result") or "").strip()
            if msg:
                detail = f"{msg}{(' | ' + detail) if detail else ''}"
        except Exception:  # noqa: BLE001
            pass
        raise CliError(f"claude CLI exited {proc.returncode}: {detail[:300]}")

    try:
        env = json.loads(out.decode())
    except Exception as e:  # noqa: BLE001
        raise CliError(
            f"claude CLI returned non-JSON: {out.decode(errors='replace')[:200]}"
        ) from e
    if env.get("is_error"):
        raise CliError(
            f"claude CLI error envelope (api_error_status={env.get('api_error_status')})"
        )
    if env.get("stop_reason") == "max_tokens":
        raise CliError("claude CLI output was truncated at the model's max output")
    if env.get("stop_reason") == "tool_use":
        # The model tried to call a tool this harness does not provide —
        # almost always a system prompt still telling it to answer "via
        # the tool". The envelope carries no message, so without this the
        # failure surfaces as a bare "exited 1:" with nothing after it.
        raise CliError(
            "the model attempted a tool call, which this provider does not "
            "support — the system prompt still instructs it to answer via a "
            "tool. See _schema_instruction's countermand."
        )
    if "result" not in env:
        raise CliError("claude CLI envelope missing 'result'")
    return env


class ClaudeCliProvider:
    """Anthropic-shaped facade over the headless CLI."""

    def __init__(self, oauth_token: str | None = None) -> None:
        self._oauth_token = oauth_token
        self.messages = self  # so call sites can do provider.messages.create

    async def create(
        self,
        *,
        model: str,
        max_tokens: int = 1024,
        system: Any = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        **_ignored: Any,
    ) -> _Response:
        forced = None
        if isinstance(tool_choice, dict):
            forced = tool_choice.get("name")

        sys_text = _flatten_system(system) + _schema_instruction(tools, forced)
        prompt, images = _split_message(messages or [])

        # Images are written to a private temp directory and the CLI is
        # granted Read on exactly those paths. The directory is removed in
        # the finally, so a photo never outlives the call — which is the
        # same promise the API path makes by never writing one at all.
        tmpdir: tempfile.TemporaryDirectory | None = None
        image_paths: list[Path] = []
        try:
            if images:
                tmpdir = tempfile.TemporaryDirectory(prefix="mv-vision-")
                for i, (media_type, b64) in enumerate(images):
                    ext = {
                        "image/jpeg": "jpg", "image/png": "png",
                        "image/gif": "gif", "image/webp": "webp",
                    }.get(media_type, "png")
                    p = Path(tmpdir.name) / f"image-{i}.{ext}"
                    p.write_bytes(base64.b64decode(b64))
                    image_paths.append(p)
                listed = "\n".join(p.name for p in image_paths)
                prompt = (
                    f"Read the image file(s) below, then answer.\n{listed}\n\n"
                    f"{prompt}"
                )

            env = await self._resilient(
                model, sys_text, prompt, image_paths, tools, forced,
                cwd=tmpdir.name if tmpdir is not None else None,
            )
        finally:
            if tmpdir is not None:
                tmpdir.cleanup()

        return env

    async def _resilient(
        self,
        model: str,
        system: str,
        prompt: str,
        image_paths: list[Path],
        tools: list[dict[str, Any]] | None,
        forced: str | None,
        cwd: str | None = None,
    ) -> _Response:
        """Invoke, then coerce the reply into blocks — retrying once when
        a tool was expected and the reply would not parse."""
        attempts = 2 if tools else 1
        last_raw = ""
        for attempt in range(1, attempts + 1):
            try:
                env = await _invoke(
                    model, system, prompt, image_paths, self._oauth_token, cwd,
                )
            except CliError as e:
                if _is_fatal(e) or attempt == attempts:
                    raise CliError(friendly_error(e)) from e
                log.warning("claude CLI transient failure, retrying: %s", str(e)[:150])
                await asyncio.sleep(3.0)
                continue

            usage = env.get("usage") or {}
            resp = _Response(
                model=env.get("modelUsage") and model or model,
                usage=_Usage(
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                ),
            )
            raw_text = env.get("result", "") or ""

            if not tools:
                resp.content = [_TextBlock(text=raw_text)]
                return resp

            last_raw = raw_text
            parsed = _strip_to_json(raw_text)
            try:
                obj = json.loads(parsed)
                if not isinstance(obj, dict):
                    raise ValueError("not an object")
            except Exception:  # noqa: BLE001
                if attempt < attempts:
                    log.warning("claude CLI reply did not parse as JSON; retrying")
                    prompt = (
                        prompt
                        + "\n\nYour previous reply was not valid JSON. Reply with "
                        "ONLY the JSON object, starting with { and ending with }."
                    )
                    continue
                # Degrade to "no tool call happened", which every call site
                # in claude.py already handles with a documented fallback.
                log.warning(
                    "claude CLI produced no usable JSON after %d attempts", attempts,
                )
                resp.content = [_TextBlock(text=last_raw)]
                return resp

            name = forced or (tools[0].get("name") if tools else "tool")
            resp.content = [_ToolUseBlock(name=name, input=obj)]
            return resp

        raise CliError("claude CLI produced no response")
