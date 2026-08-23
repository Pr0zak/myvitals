"""Provider selection, URL validation, and the response contract.

The contract is deliberately Anthropic-shaped. Every call site in claude.py
already reads ``resp.content`` as a list of blocks with a ``type`` of
``text`` or ``tool_use``, plus ``resp.model`` and ``resp.usage.input_tokens``
/ ``output_tokens``. Making the OpenAI-compatible provider present that same
shape means the nineteen call sites change by exactly two lines each -- the
client construction -- and none of the response handling moves.

The alternative, a neutral third shape, would have meant rewriting every
extraction path in a 3000-line module for no behavioural gain, and each of
those rewrites is a chance to introduce a bug into a surface that currently
works.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """A provider call failed in a way worth showing the user."""


class LlmProvider(Protocol):
    """What claude.py needs from a provider.

    Named `messages` with a `create` coroutine because that is the Anthropic
    SDK's own shape, and matching it is what keeps the call sites unchanged.
    """

    @property
    def messages(self) -> Any: ...


def validate_base_url(url: str) -> str:
    """Reject base URLs that are never legitimate. Returns the cleaned URL.

    This runs on a container that can reach the entire Proxmox cluster, so a
    user-supplied URL is an SSRF surface. What is checked:

    * The scheme must be http or https. A ``file://`` or ``gopher://`` target
      has no honest use here.
    * No embedded credentials. ``http://user:pass@host`` both leaks the
      secret into logs and is a classic parser-confusion vector.
    * There must be a host at all.

    What is deliberately *not* checked: whether the host resolves to a
    private address. Pointing at Ollama on the LAN is the entire reason this
    feature exists, so blocking RFC1918 would defeat it. The honest mitigation
    is that this value can only be set by the single authenticated user of a
    single-user app, and that it is logged when used.
    """
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        raise LlmError("base URL is empty")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise LlmError(
            f"base URL scheme must be http or https, got {parsed.scheme or 'none'!r}"
        )
    if not parsed.hostname:
        raise LlmError("base URL has no host")
    if parsed.username or parsed.password:
        raise LlmError(
            "base URL must not embed credentials — put the key in the API key "
            "field instead, where it is not logged"
        )
    return cleaned


def get_provider(cfg: Any) -> LlmProvider:
    """The provider this config selects.

    Defaults to Anthropic when `provider` is unset, which is every existing
    row: the column is additive and nothing is migrated, so an installation
    that never opens the new setting behaves exactly as it did.
    """
    provider = (getattr(cfg, "provider", None) or "anthropic").strip().lower()

    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=cfg.anthropic_api_key)

    if provider == "claude_cli":
        # Headless Claude Code CLI on the machine's subscription OAuth.
        # No API key is used — see claude_cli._AUTH_ENV_STRIP for why an
        # inherited one is actively harmful rather than merely redundant.
        from .claude_cli import ClaudeCliProvider
        log.info("LLM provider=claude_cli model=%s", getattr(cfg, "model", "?"))
        return ClaudeCliProvider(
            oauth_token=getattr(cfg, "cli_oauth_token", None),
        )

    if provider in ("openai_compatible", "ollama"):
        from .openai_compat import OpenAiCompatProvider
        base_url = validate_base_url(getattr(cfg, "base_url", "") or "")
        log.info("LLM provider=%s base_url=%s model=%s",
                 provider, base_url, getattr(cfg, "model", "?"))
        return OpenAiCompatProvider(
            base_url=base_url,
            # Ollama ignores the key entirely; a hosted OpenAI-compatible
            # endpoint needs it. Sending an empty bearer is harmless.
            api_key=cfg.anthropic_api_key or "",
        )

    raise LlmError(f"unknown AI provider {provider!r}")
