"""OpenAI-compatible chat completions, presented in the Anthropic shape.

Covers Ollama (`http://host:11434/v1`), llama.cpp's server, LM Studio, vLLM,
and any hosted endpoint that speaks the OpenAI chat-completions API.

The translation is small but there are four asymmetries worth naming, because
each one is a place where behaviour differs from the default path rather than
merely differing in syntax:

* **System prompts.** Anthropic takes a `system` parameter carrying content
  blocks with `cache_control`; OpenAI takes a system *message*. The blocks
  are flattened to text and the cache directive is dropped, because there is
  nothing to map it to. This is the concrete form of "prompt caching is
  Anthropic-only": the same conversation costs full input rate every call.
* **Forced tool use.** Anthropic's `tool_choice={"type":"tool","name":X}`
  becomes `{"type":"function","function":{"name":X}}`. Servers vary in how
  well they honour it; a model that answers in prose instead lands in
  claude.py's existing "no tool call happened" fallback rather than crashing.
* **Tool arguments arrive as a JSON *string*** and are parsed here, so the
  call sites keep reading `block.input` as a dict. A model that emits
  malformed JSON yields an empty dict, which is the same signal as no tool
  call at all.
* **Usage keys differ** (`prompt_tokens` / `completion_tokens`) and are
  renamed, so the quota accounting above this layer keeps working.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Local models on modest hardware are slow. This is generous on purpose: a
# 90-second wait is annoying, a spurious timeout that renders an empty card
# looks like a bug in the app.
_TIMEOUT_S = 180.0


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


def _flatten_system(system: Any) -> str:
    """Anthropic's system blocks (with cache_control) → one string."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    parts = []
    for block in system:
        if isinstance(block, dict):
            parts.append(block.get("text", ""))
        else:
            parts.append(str(block))
    return "\n\n".join(p for p in parts if p)


def _map_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object"}),
            },
        })
    return out


def _map_tool_choice(choice: Any) -> Any:
    if not choice:
        return None
    if isinstance(choice, dict) and choice.get("type") == "tool":
        return {"type": "function", "function": {"name": choice.get("name")}}
    return choice


class _Messages:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key

def _map_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic image blocks into the OpenAI shape.

    The two vendors disagree on exactly one thing here. Anthropic sends
    ``{"type": "image", "source": {"type": "base64", "media_type": ...,
    "data": ...}}``; OpenAI sends ``{"type": "image_url", "image_url":
    {"url": "data:<media_type>;base64,<data>"}}``.

    Without this, the call sites that pass a photo would post an
    Anthropic-shaped block to an OpenAI-compatible endpoint, which either
    errors or — worse — silently ignores the image and answers about
    nothing. Text-only messages pass through untouched, so no existing
    call site changes.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            out.append(m)
            continue
        blocks: list[Any] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "image":
                src = b.get("source") or {}
                if src.get("type") == "base64":
                    mt = src.get("media_type", "image/jpeg")
                    blocks.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mt};base64,{src.get('data', '')}",
                        },
                    })
                    continue
            blocks.append(b)
        out.append({**m, "content": blocks})
    return out


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
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [],
        }
        sys_text = _flatten_system(system)
        if sys_text:
            body["messages"].append({"role": "system", "content": sys_text})
        body["messages"].extend(_map_images(messages or []))
        mapped_tools = _map_tools(tools)
        if mapped_tools:
            body["tools"] = mapped_tools
            mapped_choice = _map_tool_choice(tool_choice)
            if mapped_choice:
                body["tool_choice"] = mapped_choice
        if temperature is not None:
            body["temperature"] = temperature

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions", json=body, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        message = (choices[0].get("message") if choices else {}) or {}
        blocks: list[Any] = []

        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                # Same signal the call sites already handle for "no tool call
                # happened": they fall back to a placeholder card rather than
                # raising. Weak models emit malformed JSON often enough that
                # this must not be an exception path.
                log.warning("provider returned unparseable tool arguments for %s",
                            fn.get("name"))
                parsed = {}
            blocks.append(_ToolUseBlock(name=fn.get("name", ""), input=parsed))

        text = message.get("content")
        if text:
            blocks.append(_TextBlock(text=text))

        usage = data.get("usage") or {}
        return _Response(
            content=blocks,
            model=data.get("model", model),
            usage=_Usage(
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            ),
        )


class OpenAiCompatProvider:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._messages = _Messages(base_url, api_key)

    @property
    def messages(self) -> Any:
        return self._messages
