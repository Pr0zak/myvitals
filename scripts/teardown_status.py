#!/usr/bin/env python3
"""Set option statuses in docs/sparkyfitness-teardown.html.

The teardown document is the durable backlog for the SparkyFitness work: a
ranked shortlist of ten items tracked as tasks TD-1..TD-10, plus a full menu
of roughly forty options that may be picked up at any point. Its value comes
entirely from staying accurate, and hand-editing fifty status chips across a
2000-line HTML file is exactly the sort of thing that quietly stops happening.

So: name an option by its heading text and give it a state. The progress bar
and the legend counts are recomputed from the chips themselves, so they can
never disagree with the list they summarise.

    scripts/teardown_status.py --set "Give HR-zone analytics an HTTP route=shipped"
    scripts/teardown_status.py --list

After editing, republish to the SAME artifact URL (see the TD-DOC task) or the
link the user already holds stops receiving updates.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs" / "sparkyfitness-teardown.html"

# state -> (chip css class, chip label)
STATES = {
    "todo": ("c-todo", "not started"),
    "wip": ("c-wip", "in progress"),
    "shipped": ("c-done", "shipped"),
    "declined": ("c-cut", "declined"),
}

BLOCK_RE = re.compile(r'<div class="(?:rk|opt)">.*?(?:</div>\s*</div>|</p></div>)', re.S)
TITLE_RE = re.compile(r'class="(?:t|h)">(.*?)</div>', re.S)
CHIP_RE = re.compile(r'<span class="chip (c-todo|c-wip|c-done|c-cut)">[^<]*</span>')


def _title(block: str) -> str:
    m = TITLE_RE.search(block)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _blocks(html: str) -> list[tuple[str, str]]:
    return [(_title(m.group(0)), m.group(0)) for m in BLOCK_RE.finditer(html)]


def set_status(html: str, title: str, state: str) -> tuple[str, bool]:
    css, label = STATES[state]
    chip = f'<span class="chip {css}">{label}</span>'
    hit = False

    def repl(m: re.Match[str]) -> str:
        nonlocal hit
        block = m.group(0)
        if _title(block).lower() != title.lower():
            return block
        hit = True
        # Every block already carries exactly one status chip, inserted when
        # the document was first generated, so this is a replace and never an
        # append -- an append would silently double the chips.
        return CHIP_RE.sub(chip, block, count=1)

    return BLOCK_RE.sub(repl, html), hit


def refresh_progress(html: str) -> str:
    """Recompute the bar and legend from the chips that actually exist."""
    ranked = [b for t, b in _blocks(html) if b.startswith('<div class="rk">')]
    menu = [b for t, b in _blocks(html) if b.startswith('<div class="opt">')]

    def count(blocks: list[str], css: str) -> int:
        return sum(1 for b in blocks if f'class="chip {css}"' in b)

    done, wip = count(ranked, "c-done"), count(ranked, "c-wip")
    total = len(ranked) or 1
    todo = total - done - wip
    pct_done = round(100 * done / total)
    pct_wip = round(100 * wip / total)

    bar = (f'<i class="b-done" style="width:{pct_done}%"></i>'
           f'<i class="b-wip" style="width:{pct_wip}%"></i>')
    html = re.sub(r'(<div class="bar" role="img" aria-label=")[^"]*("[^>]*>).*?(</div>)',
                  lambda m: f'{m.group(1)}{done} of {total} shortlist items shipped{m.group(2)}{bar}{m.group(3)}',
                  html, count=1, flags=re.S)

    legend = (
        f'<span><b style="background:var(--good)"></b> shipped &nbsp;{done}</span>\n'
        f'    <span><b style="background:var(--sp)"></b> in progress &nbsp;{wip}</span>\n'
        f'    <span><b style="background:var(--rule)"></b> not started &nbsp;{todo}</span>\n'
        f'    <span>·</span>\n'
        f'    <span>full menu: {len(menu)} options, '
        f'{count(menu, "c-done")} shipped, {count(menu, "c-cut")} declined</span>'
    )
    return re.sub(r'(<div class="legend">\n\s*).*?(\n  </div>)',
                  lambda m: f'{m.group(1)}{legend}{m.group(2)}',
                  html, count=1, flags=re.S)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="TITLE=STATE",
                    help=f"state is one of {', '.join(STATES)}")
    ap.add_argument("--list", action="store_true", help="print every option and its state")
    args = ap.parse_args()

    html = DOC.read_text()

    if args.list:
        for title, block in _blocks(html):
            m = CHIP_RE.search(block)
            kind = "ranked" if block.startswith('<div class="rk">') else "menu  "
            print(f"{kind}  {m.group(1)[2:] if m else '?':9}  {title}")
        return 0

    if not args.set:
        ap.print_help()
        return 1

    failed = False
    for pair in args.set:
        title, _, state = pair.rpartition("=")
        if state not in STATES:
            print(f"unknown state {state!r} (expected {', '.join(STATES)})", file=sys.stderr)
            return 2
        html, hit = set_status(html, title, state)
        if not hit:
            print(f"no option titled {title!r} — run --list to see the exact headings",
                  file=sys.stderr)
            failed = True
        else:
            print(f"{title} -> {state}")

    if failed:
        return 3
    DOC.write_text(refresh_progress(html))
    print("progress bar and legend recomputed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
