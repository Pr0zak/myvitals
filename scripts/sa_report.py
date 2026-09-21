#!/usr/bin/env python3
"""Regenerate docs/self-audit-2026-09.html from docs/sa-findings.json.

The JSON is the single source of truth for the #SA audit: the finding text, the
refuter's correction, and — the part that goes stale by hand — each item's
status. Edit the status there (or with the CLI below) and re-run. The page and
the TODO.md batch tables are both overwritten from it, so the chips and the
tracker cannot disagree; never edit either by hand.

    python3 scripts/sa_report.py                 # regenerate page + TODO.md tables
    python3 scripts/sa_report.py SA-L1 shipped   # set a status, then regenerate both

Statuses: todo | wip | shipped | declined.

After regenerating, republish to the SAME artifact URL recorded in the JSON so
the link already handed to the reader keeps working.
"""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "sa-findings.json"
OUT = ROOT / "docs" / "self-audit-2026-09.html"
STATUSES = ("todo", "wip", "shipped", "declined")

# Nothing identifying the homelab may reach a public doc. The data file is
# already scrubbed; this is a second net for anything edited in by hand later.
_SCRUB = [
    (r"\bpve[0-9]\b", "$PVE_HOST"),
    (r"\bCT[\s ]?104\b", "$CT_ID"),
    (r"\bCT[\s ]?[0-9]{3,5}\b", "a sibling CT"),
    (r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:/[0-9]{1,2})?", "<lan-addr>"),
    (r"\bPBS9000\b", "the backup server"),
    (r"\b(?:Lil|Silver)NAS\b", "a NAS"),
    (r"\b[0-9a-fA-F]{32,}\b", "<redacted>"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<redacted-email>"),
]


def scrub(s):
    for pat, rep in _SCRUB:
        s = re.sub(pat, rep, s)
    return s


def esc(s):
    return html.escape(scrub(html.unescape(s or "")), quote=False)


def rich(s):
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))


def clip(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


BATCHES = [
    ("live", "Live — the app states something false right now",
     "Six surfaces assert a number, a status or a state that the database contradicts. Every one "
     "reproduced under an independent refuter who re-ran the SQL. They come first regardless of how "
     "appealing anything below them looks, which is this project's own stated order."),
    ("sec", "Exposure — the token model has a door cut around it",
     "The bearer-token layer itself audited clean: constant-time compare, correct 401s, no blanket "
     "dependency overrides across 269 routes. The problems are beside it, not in it."),
    ("gate", "The gates — what is meant to catch this class, and does not run",
     "1,936 tests pass in 34 seconds and nothing executes them. Both NameErrors in SA-L5 are F821s "
     "that the repo's own configured linter reports today."),
    ("num", "The numbers behind the numbers",
     "Not wrong on screen so much as wrong underneath — a window, a baseline, a gate, a label. Each "
     "changes a figure the user reads, but none of them announces itself."),
    ("reach", "Reachability — built, shipped, and with no door",
     "The neon shell is the default web shell. Several surfaces reachable in the classic shell, or on "
     "the phone, have no route into them from the one actually in use."),
    ("ops", "Operations — what happens when nobody is watching",
     "The deploy chain is better than it looks: auto-update takes a pre-update dump, health-probes the "
     "new image and rolls back on failure. What it cannot see is a logic regression, which is the whole "
     "of SA-G1."),
    ("gap", "Phone telemetry — permissioned, counted as granted, never read",
     "Health Connect grants the app reads it does not use. Each one inflates the \"12/12 granted\" "
     "count that the permission banner and the sync diagnostics report, while contributing nothing, "
     "so the app looks fully wired for data it has never once requested."),
    ("cut", "Dead weight — things to delete rather than build",
     "Eleven items where the right change removes code, rows or megabytes. Listed last not because they "
     "matter least but because none of them is urgent; several are the cheapest wins on the page."),
]
TONE = {5: "c-v5", 4: "c-v4", 3: "c-v3", 2: "c-eff", 1: "c-eff", 0: "c-eff"}
ST_CHIP = {"todo": ("c-todo", "not started"), "wip": ("c-wip", "in progress"),
           "shipped": ("c-ship", "shipped"), "declined": ("c-cut", "declined")}
CSS = (Path(__file__).resolve().parent / "sa_report.css").read_text()



TODO_MD = ROOT / "TODO.md"
BEGIN, END = "<!-- SA-TABLES:BEGIN -->", "<!-- SA-TABLES:END -->"
ST_MARK = {"todo": "", "wip": " ⏳", "shipped": " ✅", "declined": " ✖"}


def todo_tables(d):
    """The TODO.md batch tables, regenerated from the same statuses the page uses."""
    out = []
    for key, title, _ in BATCHES:
        grp = [i for i in d["items"] if i["batch"] == key]
        if not grp:
            continue
        out += ["### %s" % title, "",
                "| ID | Task | Size | Surface | Status |", "|---|---|---|---|---|"]
        for i in grp:
            out.append("| %s | %s | %s | %s | %s%s |" % (
                i["id"], i["task"], i["size"], i["surface"],
                i["status"], ST_MARK[i["status"]]))
        out.append("")
    return "\n".join(out)


def write_todo(d):
    if not TODO_MD.exists():
        return
    s = TODO_MD.read_text()
    if BEGIN not in s or END not in s:
        print("TODO.md: markers missing, left untouched")
        return
    head, rest = s.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    TODO_MD.write_text(head + BEGIN + "\n\n" + todo_tables(d) + "\n" + END + tail)
    print("updated TODO.md tables")


def card(it):
    st_cls, st_txt = ST_CHIP[it["status"]]
    o = ['<div class="rk">',
         '<div class="top"><div class="t">%s</div><div class="m">' % rich(it["title"]),
         '<span class="chip c-id">%s</span>' % esc(it["id"]),
         '<span class="chip %s">%s</span>' % (st_cls, st_txt),
         '<span class="chip %s">value %d</span>' % (TONE[it["value"]], it["value"]),
         '<span class="chip c-eff">%s</span>' % esc(it["size"]),
         '<span class="chip c-eff">%s</span>' % esc(it["surface"]),
         '<span class="chip c-lens">%s</span>' % esc(it["lens"]),
         '</div></div>',
         '<p>%s</p>' % rich(clip(it["problem"], 900)),
         '<p><span class="lab">Today</span>%s</p>' % rich(clip(it["impact"], 900)),
         '<p><span class="lab">Change</span>%s</p>' % rich(clip(it["proposal"], 900))]
    if it.get("correction"):
        o.append('<p class="corr"><span class="lab">Refuter</span>%s</p>'
                 % rich(clip(it["correction"], 1100)))
    if it.get("also_found_by"):
        o.append('<p class="corr" style="border-left-color:var(--mv)">'
                 '<span class="lab">Also found by</span>%s</p>'
                 % " · ".join(rich(m) for m in it["also_found_by"]))
    o.append('<details><summary>Evidence</summary><pre>%s</pre></details></div>'
             % esc(clip(it["evidence"], 2600)))
    return "\n".join(o)


def build(d):
    m, items = d["meta"], d["items"]
    n = len(items)
    cnt = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    pct = lambda k: round(100 * cnt[k] / n) if n else 0

    H = ['<title>Thirteen Lenses on myvitals</title>',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Mono:wght@400;500&display=swap">',
         '<style>%s</style>' % CSS, '<div class="wrap">']

    H.append('''
<header class="mast">
  <div class="eyebrow"><span>Internal audit · first pass</span><span>·</span>
    <i>myvitals %s</i><span>·</span><span>18 Sept 2026</span></div>
  <h1>Thirteen Lenses on myvitals</h1>
  <p class="dek">Not a teardown of another project. Thirteen independent lenses were pointed at
  <strong>this</strong> codebase and at the live production database — dormant surfaces, unsurfaced
  data, truth, parity, reliability, performance, the AI layer, security, the test gates, the Android
  app, operations, statistical headroom, and a scan of comparable projects that are not openGym. Each
  lens measured before it claimed; each finding was then handed to a refuter told to kill it.
  <strong>%d findings, %d survived, %d were refuted</strong> — and the refusals are printed in full,
  because a measured refusal is what stops an idea coming back next quarter.</p>
</header>''' % (esc(m["against"].split()[0]), m["found"], m["survived"], m["refuted"]))

    H.append('''
<div class="box alarm">
  <h4>Fix first</h4>
  <p><strong>Every step count the app has stored since 20 July is wrong, and the row can never
  repair itself.</strong> The lazy <code>daily_summary</code> recompute asks two questions — is sleep
  missing, is HRV missing — and steps are not one of them. Once a day has sleep and HRV the row is
  frozen at whatever partial count existed when it was written. Recomputed against the raw samples over
  100 local days: <strong>32 days disagree, 24 of them by more than 1,000 steps, and the stored history
  is 142,028 steps — 23% — short</strong>. 6 September reads 122 against a real 17,855. Trends, the home
  ring, the Compare card, the CSV export, the MCP tools and every AI coach payload read the frozen
  column, while the Steps detail screen computes live and shows the right number. Two screens, two
  answers, same day.</p>
  <p>Two live NameErrors sit beside it. <code>ruff</code> — already configured in this repo, already
  declared as a dev dependency — reports both as F821 today, and nothing runs it.</p>
</div>''')

    H.append('''
<div class="box head">
  <h4>The headline</h4>
  <p><strong>This codebase is unusually disciplined about not lying to its user, and the discipline is
  applied where a human remembered to apply it.</strong> The guard tests are real and they work: 1,936
  of them pass in 34 seconds, AST-walking for a UTC day boundary, a nulled model attribute, a streak on
  the food log, an RDA threshold, a mutation in the MCP surface. What is missing is not judgement — it
  is <em>execution</em>. No CI job runs any of them. No release step runs any of them. The tag that
  publishes <code>:latest</code> is pulled into production within fifteen minutes by a cron that
  health-probes the container and rolls back if it fails to boot, and is blind by construction to a red
  test or a lint error.</p>
  <p>That gap explains the shape of this whole report. Of the six live untruths, <strong>five would have
  been caught by something the project already owns</strong> — two by <code>ruff --select F</code>, one by
  the goal-state guard the project wrote after the identical bug in v0.32.0, one by the parity map that
  stopped being updated, one by a single request-level test of an endpoint that has none. The thinking
  was done. Nothing makes it run.</p>
</div>''')

    H.append('<div class="prog">')
    H.append('<h4>Progress · %d of %d shipped</h4>' % (cnt["shipped"], n))
    H.append('<div class="bar"><i class="b-ship" style="width:%d%%"></i>'
             '<i class="b-wip" style="width:%d%%"></i></div>' % (pct("shipped"), pct("wip")))
    H.append('<div class="legend">'
             '<span><b style="background:var(--done)"></b> shipped %d</span>'
             '<span><b style="background:var(--warn)"></b> in progress %d</span>'
             '<span><b style="background:var(--surface-2);border:1px solid var(--rule)"></b> '
             'not started %d</span>'
             '<span><b style="border:1px dashed var(--rule)"></b> declined %d</span></div>'
             % (cnt["shipped"], cnt["wip"], cnt["todo"], cnt["declined"]))
    H.append('<p style="margin:14px 0 0;font-size:14px;color:var(--ink-2)">Tracked as '
             '<code>SA-*</code> in the repo\'s <code>TODO.md</code>. Status lives in '
             '<code>docs/sa-findings.json</code> and this page is regenerated from it by '
             '<code>scripts/sa_report.py</code> — the chips cannot drift from the tracker because '
             'they are the same file.</p>')
    H.append('</div>')

    H.append('<h2>Method</h2>')
    H.append('''<p>Thirteen lenses ran in parallel, each with read access to the repository at
<code>%s</code> (byte-identical to the deployed build), to the production database, and to the live
API. Each was capped at four findings and required to attach either a <code>file:line</code> with the
quoted line or the SQL and its result — and to report, separately, what it had checked and found
<em>clean</em>. Findings were then paired off to refuters instructed to default to refuted where they
could not independently reproduce the claim.</p>
<p>Ten died there, several of them findings that read extremely well until someone re-ran the query.
The refuters also corrected <em>surviving</em> findings in 39 cases — a scale overstated, an impact
claimed on a screen that does not exist, a proposal that would have broken one of the project's own
invariants. Those corrections are printed with each item, under
<span class="lab">Refuter</span>.</p>''' % esc(m["against"].split("(")[-1].rstrip(")")))

    H.append('<div class="scroll"><table><thead><tr><th>Group</th><th>Items</th><th>Shipped</th>'
             '<th></th></tr></thead><tbody>')
    for key, title, _ in BATCHES:
        grp = [i for i in items if i["batch"] == key]
        H.append('<tr><td>%s</td><td><strong>%d</strong></td><td>%d</td><td>%s</td></tr>'
                 % (esc(title.split(" — ")[0]), len(grp),
                    sum(1 for i in grp if i["status"] == "shipped"),
                    esc(title.split(" — ")[-1] if " — " in title else "")))
    H.append('<tr><td>Refuted</td><td><strong>%d</strong></td><td>—</td>'
             '<td>printed in full, with the measurement that killed them</td></tr>'
             % len(d["refused"]))
    H.append('</tbody></table></div>')

    for key, title, blurb in BATCHES:
        grp = [i for i in items if i["batch"] == key]
        if not grp:
            continue
        H.append('<h2>%s</h2>' % esc(title))
        H.append('<p>%s</p>' % rich(blurb))
        H.append('<div class="rank">')
        H.extend(card(i) for i in grp)
        H.append('</div>')

    H.append('<h2>Refuted — and why</h2>')
    H.append('''<p>Ten findings did not survive. They are recorded because each one is a claim a future
session would otherwise re-derive from the same intuition, and because three of them were wrong in a
way worth knowing about: the thing they described had already self-healed, or the screen they claimed
to correct does not exist.</p>''')
    H.append('<dl class="dec">')
    for f in d["refused"]:
        H.append('<dt>%s <span class="chip c-kill">refuted</span> '
                 '<span class="chip c-lens">%s</span></dt>' % (rich(f["title"]), esc(f["lens"])))
        H.append('<dd>%s</dd>' % rich(clip(f["reason"], 1250)))
    H.append('</dl>')

    H.append('<h2>What the lenses cleared</h2>')
    H.append('''<p>Each lens was required to report what it had checked and found sound. This is the
half of an audit that usually goes unrecorded, and it is the half that stops the same ground being
re-walked.</p>''')
    H.append('<div class="scroll"><table><thead><tr><th>Lens</th><th>Cleared</th></tr></thead><tbody>')
    for c in d["cleared"]:
        lis = "".join("<li>%s</li>" % rich(clip(i, 340)) for i in c["items"][:6])
        H.append('<tr><td>%s</td><td><ul style="margin:0;padding-left:17px">%s</ul></td></tr>'
                 % (esc(c["lens"]), lis))
    H.append('</tbody></table></div>')

    H.append('''
<div class="foot">
  myvitals · internal audit, first pass · %s · against %s<br>
  13 lenses · %d findings · %d survived adversarial refutation · %d ranked here, 3 merged into a sibling<br>
  Generated by <code>scripts/sa_report.py</code> from <code>docs/sa-findings.json</code>. Do not edit
  this file by hand.
</div></div>''' % (esc(m["audited_on"]), esc(m["against"]), m["found"], m["survived"], n))
    return "\n".join(H)


def main(argv):
    d = json.loads(DATA.read_text())
    if len(argv) >= 2:
        sid, st = argv[0].upper(), argv[1].lower()
        if st not in STATUSES:
            sys.exit("status must be one of: %s" % ", ".join(STATUSES))
        hit = next((i for i in d["items"] if i["id"] == sid), None)
        if hit is None:
            sys.exit("no such id: %s" % sid)
        hit["status"] = st
        DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False))
        print("%s -> %s" % (sid, st))
    OUT.write_text(build(d))
    write_todo(d)
    cnt = {s: sum(1 for i in d["items"] if i["status"] == s) for s in STATUSES}
    print("wrote %s (%d items: %s)" % (OUT.relative_to(ROOT), len(d["items"]),
          ", ".join("%d %s" % (cnt[s], s) for s in STATUSES if cnt[s])))
    print("republish to", d["meta"]["artifact_url"])


if __name__ == "__main__":
    main(sys.argv[1:])
