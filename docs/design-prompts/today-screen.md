# claude.ai/design prompt — myvitals Today screen refactor

Paste the prompt block below into <https://claude.ai/design> to get a
single-route landing dashboard that consolidates today's read in a
clearer information hierarchy than the current `/views/Today.vue`.

The current screen has accreted six layered surfaces that all compete
for the top of the viewport — AI verdict strip, pre-workout chip, AI
insights card, TrendBadges component, KPI strip, and "Today at a
glance" hero — followed by long detail cards (HR with 30d range pills,
steps with daily breakdown, BP with entry form). The result is
information-dense but disorganized; goal of this redesign is to
flatten the hierarchy into **one hero · one live-vitals row · one
day-summary band · contextual modules** that you scroll past, not
through.

Tokens, palette, and visual language must match the rest of the
dashboard exactly — same dark surface stack, same monospace numerals,
same outlined Material icons, no emoji. Nothing should look "designed
for Today" specifically; it should feel like the same product as the
Heart Rate detail and Workout pages.

---

## Prompt

> Design a single-route web dashboard called **Today** for a self-hosted
> health tracking app called **myvitals**. The user is a single person
> tracking heart rate, HRV, sleep, steps, blood pressure, weight,
> recovery, and an optional Claude-narrated AI insights layer. The
> existing Today screen is over-crowded; this is a refactor focused on
> hierarchy and breathing room. Target desktop-first responsive (collapses
> cleanly to a single column at <720px).
>
> **Visual language** — pure dark theme, identical to the rest of the
> dashboard:
> - Background: `#0F1620`. Surface raised: `#1B2331`. Surface low: `#121925`.
>   Outline variant: `#243042`.
> - On-surface text: `#E5E7EB`. Secondary: `#94A3B8`. Dim: `#6B7689`.
> - Brand accent (used sparingly — primary CTAs, "today" highlights,
>   resting HR): `#EF4444` (Tailwind red-500).
> - Status semantics:
>   - Good / improving: `#22C55E` (green-500)
>   - Watch / amber: `#EAB308` (yellow-500)
>   - Bad / declining: `#EF4444`
>   - Neutral: slate `#94A3B8`
> - Heart-rate zones (charts only): Z1 `#38BDF8`, Z2 `#22C55E`,
>   Z3 `#EAB308`, Z4 `#F97316`, Z5 `#EF4444`.
> - Body text: system sans-serif. **All numbers in cards** use a
>   monospaced family (Geist Mono / JetBrains Mono) — that's an
>   intentional, project-wide convention.
> - Iconography: outlined Lucide icons only. No filled glyphs, no emoji
>   in the rendered UI.
> - Charts: ECharts. Smooth lines, 1.5–1.8px stroke, semi-transparent
>   area fill, dashed mean-lines, theme-tinted axis labels.
>
> **Information architecture (top → bottom):**
>
> 1. **Page header strip** — one line. Left: `Today` in 22px semibold +
>    a small uppercase date pip "Fri Mar 8" in 11px / 1.5px letter-spacing.
>    Right: outlined refresh icon and a 3-dot overflow that opens
>    `Trends`, `Calendar`, `Goals`, `Compare`. No range pills here —
>    Today is "now"; the detail screens own range.
>
> 2. **Hero band** — single tall card (≈220px) split into three columns:
>    - **Left (40%)**: a 140px circular **Readiness gauge**. Number in
>      the centre (e.g. "78"), word "Readiness" beneath, gauge fill in
>      the appropriate status colour. Below the gauge: a one-sentence
>      Claude-narrated **verdict** (≤22 words) when AI is enabled,
>      otherwise just `"—"` muted. Tiny refresh icon to regenerate
>      the verdict.
>    - **Middle (30%)**: 4-row mini summary of today's anchor numbers:
>      `Sleep 7h 23m · 84`, `Resting HR 58 bpm`, `HRV 42 ms`,
>      `Steps 6 240 / 10 000`. Each row has the metric name in dim
>      11px caps, the value in 16px monospace, and a tiny
>      change-vs-7d-baseline pip (▲/▼ + delta in green/red).
>    - **Right (30%)**: 96px-square mini cards (2×2) for Recovery /
>      Readiness / Sleep score / TSB. Each shows the score, a tiny
>      sparkline of the last 7 days underneath, and a status pip.
>
>    The hero replaces today's two competing summary surfaces (KPI
>    strip + "Today at a glance"). Anything not in the hero shouldn't
>    surface above the fold.
>
> 3. **Live vitals row** — a single 96-tall card, three equal columns:
>    - **Heart rate** — current/last value in 24px mono, dim age tag
>      ("4h ago"), and a 24-hour HR sparkline that takes the bottom
>      half of the card. Resting HR baseline drawn as a faint dashed
>      horizontal line.
>    - **HRV** — last value, 24h sparkline, 7-day baseline dashed.
>    - **Steps** — current count vs goal as a 6px progress bar plus
>      hourly buckets behind the bar (faded blocks 0–24).
>
>    Tapping any column drills into the matching `/heart-rate`,
>    `/trends#hrv`, or `/trends#steps` detail screen — the row is the
>    "see at a glance, click for depth" pattern. NO 30-day range
>    pills, NO multi-tab overlay toggles. Those belong to the detail
>    pages.
>
> 4. **AI insights** (only when AI is enabled in Settings) — one card
>    with a **single** structured response visible at a time. Topic
>    selector on the left as a vertical pill list (Sleep / Recovery /
>    Sober / Workout / Week / Anomaly). Right side renders the picked
>    topic's structured card: tone-tinted left border, headline in
>    14px semibold, evidence as 1-3 monospace bullets, and an optional
>    `Try: …` suggestion in dim text. Footer: "fresh" / "cached" pill,
>    model name, generated-at timestamp, refresh button. Replace the
>    current "verdict strip + prework chip + insights card" trio with
>    this single card.
>
> 5. **Today's activity** — horizontal card with three equal cells:
>    - Last activity (icon + name + duration + avg HR + miles).
>      Empty state = `"No activity logged today"` muted.
>    - Last strength workout (split focus + sets count + completed pip).
>    - Last rowing erg (distance + 500m split + avg power).
>
>    Rowing only shows when present; otherwise omit the cell.
>    Tapping any cell drills into the matching detail screen.
>
> 6. **Body & log** — two-column row, equal width:
>    - **Body metrics** card. Weight last reading + 30-day sparkline
>      with a goal-weight reference line. Tiny "log weight" outlined
>      button in the header.
>    - **Blood pressure** card. Latest sys/dia + 30-day sparkline (two
>      thin lines, sys red, dia amber). "Log BP" outlined button in
>      the header opens a slide-over (NOT inline) with a 3-field form.
>
> 7. **Annotation log** — last 10 logged annotations (caffeine,
>    alcohol, food, mood, meds, notes) as a compact horizontal scroll
>    of pill-shaped chips, each with a small Lucide icon and the
>    relative time. "+ Log" outlined button at the right of the row.
>
> 8. **Footer / state** — version, last-sync timestamp ("synced 4 min
>    ago" — green pip if <30min), and a "Diagnostics" link. Single
>    line, dim text.
>
> **Card styling rules:**
> - 12px corner radius. 1px outline-variant border. No shadows.
> - Card title 11px caps + 1.5px letter spacing in `OnSurfaceVariant`,
>   16px lower-margin to the content.
> - Card padding: 16px. Multi-column cards have 16px column gap.
> - Sparklines and small charts have 16px top padding inside the card
>   so they never visually crowd the title.
>
> **Number rendering:**
> - Always monospace. `tnum` font feature so digits don't shift on
>   live updates. Units (`bpm`, `ms`, `kg`, `mi`, `lb`) in a half-step
>   smaller, dim text, after a 4px gap.
> - Deltas use `▲ 1.2` (green) or `▼ 3.4` (red); never `+`/`-`.
>
> **Empty / loading states:**
> - Loading = a card-shaped 12px-rounded skeleton block with a
>   subtle 1.5s shimmer. Never a "Loading…" text.
> - Empty value = an `—` em-dash in dim text. Never zeroes when the
>   data is missing — those are different cases.
>
> **Interactions:**
> - Whole hero / live-vitals cells are link surfaces; outline glow on
>   hover (1px brand-red), no scaling, no shadow change.
> - All buttons in the design are outlined. No filled solid buttons
>   anywhere on Today (the only filled button in the whole app is the
>   primary CTA on Workout).
>
> **What NOT to add:**
> - No fitness tracker comparison. No social / streak gamification.
> - No range pills above the hero. Today is *now*; range belongs to
>   detail pages.
> - No mode toggles ("focus mode", "compact view"). One layout.
> - No emoji anywhere in the rendered output.
>
> **Generate:**
> 1. The full Today screen at desktop width (1280×900).
> 2. The same screen at mobile width (390×844, single-column stack).
> 3. The hero band as a stand-alone module (so it can be ported as a
>    component).
> 4. The live-vitals row as a stand-alone module.
> 5. The AI-insights card as a stand-alone module, with three filled
>    states: tone=good, tone=warn, tone=bad.

---

## Notes for whoever ports the result

The current implementation is in `frontend/src/views/Today.vue`
(~1,200 lines). When porting:

- **Reuse `Card.vue`** — the existing component already has the
  `title` / `subtitle` / `flat` props the prompt is built around.
- **Hero gauge** — there's a CSS-only readiness ring already at
  `today-screen` styles `.ring`; pull that out into a component.
- **Live-vitals sparklines** — use the same `baseTimeOption()` /
  `meanMarkLine()` helpers in `components/charts/chartHelpers.ts` so
  the new row matches the rest of the app visually.
- **AI insights single-topic view** — keep the `AI_TOPICS` array and
  `askTopic(id)` logic; just rearrange the markup. Drop the verdict
  strip + pre-workout chip into this card too (verdict = topic 7th
  pill at the top, prework = topic 8th).
- **Drill-down nav** — wrap each hero / live-vitals cell in a
  `<RouterLink>` to `/heart-rate`, `/sleep`, `/trends#steps`,
  `/blood-pressure`, `/weight`, `/activities`, `/workout/strength/today`.
- **Don't move** the existing data-loading or AI integration code.
  The shape of the load (`api.todaySummary`, `api.heartRate`, etc.)
  stays — only markup + styles get reworked.

Once a generated mock is ready, branch off `main` as `today-redesign`
and port piece-by-piece. Keep the old `Today.vue` until the new view
is wired and looks right at both widths — then delete the old.
