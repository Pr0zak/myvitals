"""Provider seam for the AI layer.

Everything in ``integrations/claude.py`` constructed ``AsyncAnthropic`` at
each of its nineteen call sites, so Anthropic was not a choice the app made
once — it was baked into every surface. This package is the seam, and it is
genuinely a seam rather than a rewrite: the three things that make the AI
layer safe all sit *above* it and are untouched.

* ``hash_payload`` / ``ai_summaries`` caching, so the same data still never
  re-bills.
* ``_check_and_bump_quota``, so ``daily_call_limit`` still means what it says.
* The bounded payload builders, so no more data leaves the box than before.

Swapping the provider changes who answers, not what is asked or how often.

**Why bother.** The rest of this app is self-hosted by design; the AI layer is
the one part that requires an external account and a credit card. An
OpenAI-compatible endpoint pointed at Ollama on the LAN takes the running
cost to zero and keeps every byte inside the house. That is already on the
roadmap as COACH-BATCH3.

**Three risks, priced honestly.**

1. Small local models produce far worse structured output than Haiku against
   schemas as tight as ``give_deload_check``. The salvage layer in
   ``coerce_tool_input`` is load-bearing, not optional, and a malformed
   emission still renders an empty card.
2. Prompt caching is Anthropic-only. Switching providers silently changes the
   latency and cost model, so the Settings copy says so.
3. A user-supplied ``base_url`` on a container that can reach the whole
   Proxmox cluster is an SSRF surface. ``validate_base_url`` rejects the
   shapes that are never legitimate; it deliberately does not block private
   addresses, because pointing at Ollama on the LAN is the entire point.
"""

from .base import LlmError, LlmProvider, get_provider, validate_base_url

__all__ = ["LlmError", "LlmProvider", "get_provider", "validate_base_url"]
