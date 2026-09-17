"""What KIND of failure an integration just had — OG3-D1.

Every integration here already records *that* something failed. None of them
recorded *what sort of thing* failed, and the distinction is the whole
difference between a poll worth retrying and one that cannot possibly
recover:

  * A network timeout will very likely work in fifteen minutes.
  * A revoked OAuth grant will not work in fifteen minutes, or in fifteen
    thousand. It needs a person.

Retrying both at the same cadence means the second is indistinguishable from
the first while it is happening, and the failure mode is not hypothetical.
The Google Health grant on this install expired on 2026-09-08 and was
re-tried every fifteen minutes for eight days while the dashboard reported
only that the stream was stale — which is exactly what a quiet week looks
like. TODO.md predicted this in prose under GH-EXPIRY; the database recorded
it happening, twice.

openGym's job runner reduces every failure to a named class before anything
acts on it, and lets the class drive behaviour — an answer that was paid for
and failed validation is never retried, a call that never reached the model
is. This module is the same idea at the size this app actually needs.

## Four kinds, and why not more

``transient``  A network error, a timeout, a 5xx. Retry on the normal
               schedule; it will probably fix itself.
``auth``       A credential is expired, revoked or rejected. Retrying cannot
               help and only buries the real message under identical log
               lines. Needs a human to reconnect.
``config``     Something is missing or malformed in the user's own setup — no
               client id, no token, a bad URL. Also needs a human, but a
               different sentence: nothing to reconnect, something to fill in.
``upstream``   The far end answered, and said no in a way that is neither our
               credentials nor our configuration — a 4xx we cannot fix, a
               deprecated endpoint, a rate limit. Worth surfacing, not worth
               hammering.

Four values across four integrations is deliberately the whole design. A
richer taxonomy would have categories with one member and no distinct
behaviour, which is a pipeline pretending to be a decision.

## What this does NOT do

It does not feed `status` in `analytics/data_health.py` from the age of the
last item. HEALTH-1's restraint holds: most streams are SUPPOSED to be stale,
and a card that fires on healthy data is one you stop reading by the week it
matters. A revoked grant is not a stale stream — it is a fault with a
specific action attached — which is precisely why it gets its own kind rather
than a longer staleness message.
"""

from __future__ import annotations

from typing import Literal

#: The four kinds. A plain Literal rather than an Enum so the value that
#: reaches the database, the API and both clients is the same short string
#: all the way through, with no serialisation step to get wrong.
ErrorKind = Literal["transient", "auth", "config", "upstream"]

#: Kinds a scheduled poll should stop retrying until a human intervenes.
#: `upstream` is deliberately NOT here: a rate limit or a bad gateway is
#: worth surfacing and does often clear on its own.
BLOCKING_KINDS: frozenset[str] = frozenset({"auth", "config"})

#: What a client should offer the user for each kind. The words live
#: server-side for the same reason `analytics/compare.py` owns `better`:
#: a client deciding that a 400 means "reconnect" is a client making a
#: judgement it has no information for.
KIND_ACTION: dict[str, str] = {
    "transient": "Retrying automatically.",
    "auth": "Reconnect this integration to restore it.",
    "config": "Check this integration's settings.",
    "upstream": "The service rejected the request. Retrying later.",
}


class IntegrationError(Exception):
    """An integration failure that knows what kind of failure it is.

    Existing per-integration exception types keep working — `GoogleHealthError`
    and `CookieExpired` both subclass this now, so every `except` clause
    already written still catches what it caught before. That mattered more
    than a clean hierarchy: this is being retrofitted onto four live polls,
    and a refactor that changes what an `except` catches is how a poll stops
    reporting anything at all.
    """

    #: Default for subclasses that do not say. `transient` is the safe
    #: default: treating an unknown failure as retryable preserves today's
    #: behaviour, where treating it as blocking would silently disable a
    #: poll on the first unrecognised error.
    kind: ErrorKind = "transient"

    def __init__(self, message: str, kind: ErrorKind | None = None) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind

    @property
    def action(self) -> str:
        return KIND_ACTION.get(self.kind, KIND_ACTION["transient"])

    @property
    def blocking(self) -> bool:
        """Whether a scheduled poll should stop until someone intervenes."""
        return self.kind in BLOCKING_KINDS


def classify_oauth_response(status_code: int, body: str) -> ErrorKind:
    """Kind of an OAuth token-endpoint failure.

    `invalid_grant` is the one that matters and the one that has actually
    happened here: Google returns it for a refresh token that has been
    revoked or expired, which on an OAuth client still in *Testing*
    publishing status happens after exactly seven days regardless of use.
    No amount of retrying recovers it; publishing the client does.

    A 5xx from an auth server is a transient failure that happens to be
    about auth, which is not the same thing — hence the status check first.
    """
    if status_code >= 500:
        return "transient"
    lowered = (body or "").lower()
    if "invalid_grant" in lowered or "invalid_client" in lowered:
        return "auth"
    if "unauthorized_client" in lowered or "invalid_scope" in lowered:
        return "config"
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        return "upstream"
    return "upstream" if status_code >= 400 else "transient"
