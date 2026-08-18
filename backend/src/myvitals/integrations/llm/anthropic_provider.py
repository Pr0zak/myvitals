"""Anthropic — the path this app has always taken, unchanged.

Deliberately the thinnest possible wrapper. The SDK's response already has
the shape claude.py reads, and prompt caching, forced tool choice and the
`cache_control` breakpoint all work exactly as before. Nothing about the
default path is refactored in the name of making a second path possible.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic


class AnthropicProvider:
    def __init__(self, api_key: str | None) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    @property
    def messages(self) -> Any:
        return self._client.messages
