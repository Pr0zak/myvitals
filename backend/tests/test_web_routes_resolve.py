"""Every internal link the web builds by hand must match a route — WEB-ROUTE-1.

Reported from live use: tapping a strength session in Train's "Recent · last 7
days" list left the page entirely and landed on /rings.

`Train.vue` built `/workout/day/${w.date}`. The route is
`/workout/strength/day/:date`, so the URL matched nothing, fell through to the
catch-all in `main.ts` — `{ path: "/:pathMatch(.*)*", redirect: "/" }` — and
was redirected to "/", which `router.beforeEach` then turns into `/rings` on
the neon shell. One missing path segment, and the failure mode was navigating
to a different section of the app rather than an error.

That is what makes this class of bug worth a test rather than a fix. The
catch-all exists for a good reason — it stops a bad URL rendering a blank page
— but it also means a typo in a hand-built link is completely silent. There is
no console error, no 404 screen, and the destination is a real page, so it
reads as a deliberate navigation.

Vue's `<RouterLink :to="{ name: ... }">` form cannot fail this way, because an
unknown name warns at runtime. The links at risk are exactly the ones built as
strings, which is what this collects.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
MAIN = SRC / "main.ts"

#: How a hand-built internal path reaches the router. Each pattern captures a
#: string starting with "/" that is used as a destination — not an API call,
#: not a CSS url(), not an external href.
_LINK_PATTERNS = (
    re.compile(r"""href:\s*[`'"](/[^`'"$\s]*(?:\$\{[^}]*\}[^`'"$\s]*)*)[`'"]"""),
    re.compile(r""":to="`(/[^`]*)`"""),
    re.compile(r""":to="'(/[^']*)'"""),
    re.compile(r"""router\.push\(\s*[`'"](/[^`'"]*)[`'"]"""),
    re.compile(r"""\bgo\(\s*[`'"](/[^`'"]*)[`'"]"""),
)


def _routes() -> list[re.Pattern[str]]:
    """The registered paths, as regexes that a concrete URL must match."""
    out: list[re.Pattern[str]] = []
    for raw in re.findall(r"""\{\s*path:\s*["'](/[^"']*)["']""", MAIN.read_text()):
        if "pathMatch" in raw:
            continue  # the catch-all is what this test exists to bypass
        # :date  → one segment;  :date?  → an optional segment
        pat = re.sub(r":([A-Za-z_]\w*)\?", r"(?:/[^/]+)?", raw.replace("/:", "/:"))
        pat = pat.replace("/(?:/[^/]+)?", "(?:/[^/]+)?")
        pat = re.sub(r":([A-Za-z_]\w*)", r"[^/]+", pat)
        out.append(re.compile(rf"^{pat}/?$"))
    return out


def _candidates() -> list[tuple[pathlib.Path, str]]:
    found: list[tuple[pathlib.Path, str]] = []
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in (".vue", ".ts") or path.name == "main.ts":
            continue
        text = path.read_text()
        for pat in _LINK_PATTERNS:
            for m in pat.findall(text):
                found.append((path, m))
    return found


def _concrete(link: str) -> str:
    """Substitute a plausible value for every interpolated segment, and drop
    the query and hash — the router matches on path alone, so
    `/settings?tab=display` is a perfectly good link to `/settings`."""
    return re.sub(r"\$\{[^}]*\}", "x", link).split("?")[0].split("#")[0]


class TestEveryHandBuiltLinkResolves:
    def test_the_route_table_was_actually_parsed(self):
        """A parser that silently found nothing would pass every assertion
        below while checking absolutely nothing."""
        routes = _routes()
        assert len(routes) > 30, len(routes)

    def test_links_were_actually_collected(self):
        assert len(_candidates()) > 10

    def test_the_workout_day_link_is_covered(self):
        """The reported bug, pinned by name so a future refactor that stops
        collecting `href:` literals fails here rather than going quiet."""
        links = {_concrete(l) for _p, l in _candidates()}
        assert "/workout/strength/day/x" in links

    def test_every_link_matches_a_registered_route(self):
        routes = _routes()
        bad = [
            f"{p.relative_to(REPO)}: {link}"
            for p, link in _candidates()
            if not any(r.match(_concrete(link)) for r in routes)
        ]
        assert not bad, (
            "these are redirected to / by the catch-all, which on the neon "
            "shell becomes /rings — a silent navigation to another section:\n"
            + "\n".join(bad)
        )
