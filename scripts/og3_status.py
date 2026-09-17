#!/usr/bin/env python3
"""Read and update the status chips in `docs/opengym-third-pass.html`.

The teardown report is a durable backlog, not a one-off write-up: it is
published as an Artifact the user holds a link to, and it has to keep saying
something true as items ship. Editing twenty-one chips and a progress bar by
hand is exactly the job that drifts, so it is a script.

Same shape as `teardown_status.py` does for the SparkyFitness report — this
one is separate rather than generalised because the two documents have
different chip markup, and a shared abstraction over two callers would be
harder to read than two small scripts.

    scripts/og3_status.py --list
    scripts/og3_status.py --set OG3-A1=shipped:v0.39.0
    scripts/og3_status.py --set OG3-M8=declined

After updating, republish to the SAME artifact URL so the link the user holds
keeps working:

    Artifact({file_path: "docs/opengym-third-pass.html",
              url: "https://claude.ai/code/artifact/b9820117-3615-426e-9f56-d111f9a87803"})
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "opengym-third-pass.html"

#: chip class → the word rendered in it. `shipped` carries a version, so its
#: label is built at write time rather than looked up here.
CLASSES = {
    "todo": ("c-todo", "not started"),
    "wip": ("c-wip", "in progress"),
    "shipped": ("c-ship", "shipped"),
    "declined": ("c-cut", "declined"),
}

#: Anchored on the id chip, so a status chip elsewhere in the row (value,
#: effort, surface) can never be mistaken for this one.
ROW = re.compile(
    r'(<span class="chip c-id">(OG3-[A-Z]\d+)</span>)'
    r'(.*?)'
    r'(<span class="chip (c-todo|c-wip|c-ship|c-cut)">([^<]*)</span>)',
    re.S,
)


def read(html: str) -> list[tuple[str, str, str]]:
    """(id, state, label) for every tracked row, in document order."""
    out = []
    for m in ROW.finditer(html):
        cls = m.group(5)
        state = next(k for k, (c, _) in CLASSES.items() if c == cls)
        out.append((m.group(2), state, m.group(6)))
    return out


def write_one(html: str, ident: str, state: str, version: str | None) -> str:
    if state not in CLASSES:
        sys.exit(f"unknown state {state!r}; expected one of {', '.join(CLASSES)}")
    cls, word = CLASSES[state]
    label = f"{word} {version}" if state == "shipped" and version else word

    def sub(m: re.Match[str]) -> str:
        if m.group(2) != ident:
            return m.group(0)
        chip = f'<span class="chip {cls}">{label}</span>'
        return m.group(1) + m.group(3) + chip

    new = ROW.sub(sub, html)
    if new == html:
        sys.exit(f"{ident} not found in {DOC.name} (or already in that state)")
    return new


def repaint_progress(html: str) -> str:
    """Recompute the bar and legend from the chips themselves.

    Derived rather than stored, so the summary cannot disagree with the rows
    it summarises — the failure mode the whole script exists to avoid.
    """
    rows = read(html)
    total = len(rows)
    shipped = sum(1 for _, s, _ in rows if s == "shipped")
    wip = sum(1 for _, s, _ in rows if s == "wip")
    declined = sum(1 for _, s, _ in rows if s == "declined")
    todo = total - shipped - wip - declined
    pct_s = round(shipped / total * 100) if total else 0
    pct_w = round(wip / total * 100) if total else 0

    html = re.sub(
        r"<h4>Progress · [^<]*</h4>",
        f"<h4>Progress · {shipped} of {total} shipped</h4>",
        html, count=1,
    )
    html = re.sub(
        r'<div class="bar">.*?</div>',
        f'<div class="bar"><i class="b-ship" style="width:{pct_s}%"></i>'
        f'<i class="b-wip" style="width:{pct_w}%"></i></div>',
        html, count=1, flags=re.S,
    )
    legend = (
        f'<span><b style="background:var(--done)"></b> shipped {shipped}</span>\n'
        f'    <span><b style="background:var(--warn)"></b> in progress {wip}</span>\n'
        f'    <span><b style="background:var(--surface-2);'
        f'border:1px solid var(--rule)"></b> not started {todo}</span>'
    )
    if declined:
        legend += (
            f'\n    <span><b style="border:1px dashed var(--rule)"></b> '
            f'declined {declined}</span>'
        )
    return re.sub(
        r'<div class="legend">.*?</div>',
        f'<div class="legend">\n    {legend}\n  </div>',
        html, count=1, flags=re.S,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print every item and its state")
    ap.add_argument(
        "--set", action="append", default=[], metavar="ID=STATE[:VERSION]",
        help="e.g. OG3-A1=shipped:v0.39.0, OG3-C2=wip, OG3-M8=declined",
    )
    args = ap.parse_args()

    html = DOC.read_text()

    for spec in args.set:
        if "=" not in spec:
            sys.exit(f"bad --set {spec!r}; expected ID=STATE[:VERSION]")
        ident, _, rest = spec.partition("=")
        state, _, version = rest.partition(":")
        html = write_one(html, ident.strip(), state.strip(), version.strip() or None)

    if args.set:
        html = repaint_progress(html)
        DOC.write_text(html)

    if args.list or not args.set:
        for ident, state, label in read(html):
            print(f"{ident:<9} {label}")
        rows = read(html)
        print(f"\n{sum(1 for _, s, _ in rows if s == 'shipped')} of {len(rows)} shipped")


if __name__ == "__main__":
    main()
