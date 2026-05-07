# claude.ai/design prompt — myvitals Workout section

Paste the prompt block below into <https://claude.ai/design>. It's tuned to
generate a single-route workout screen + the exercise card subcomponent in
the same dark, monospace-leaning aesthetic the rest of the app uses (Vitals
badges, Trails cards, Vico charts). Keep your design tokens consistent with
the existing Vue dashboard so a generated mock can be ported with minimal
re-skinning.

---

## Prompt

> Design a single-route mobile-first dashboard called **Workout** for a
> self-hosted health app called **myvitals**. The user is a single
> person (no multi-tenant chrome) tracking strength training with a
> dumbbell + bench setup. Target both web and Android phone — the
> components should look identical on both.
>
> **Visual language** — pure dark theme:
> - Background: `#0F1620`. Surface containers: `#1B2331` (raised),
>   `#121925` (low). Outline variant: `#243042`.
> - Primary on-surface text: `#E5E7EB`. Secondary: `#94A3B8`.
>   Dim text: `#6B7689`.
> - Brand accent (sparingly, for primary CTAs + "today" highlight):
>   `#EF4444` (Tailwind red-500).
> - Status pips & exercise-status semantics:
>   - Open / Complete: `#22C55E` (green-500)
>   - Delayed / In progress: `#EAB308` (yellow-500)
>   - Closed / Skipped: `#EF4444` (red-500), or muted slate when neutral.
> - Heart-rate zones (used in charts): Z1 `#38BDF8`, Z2 `#22C55E`,
>   Z3 `#EAB308`, Z4 `#F97316`, Z5 `#EF4444`.
> - Typography: system sans-serif body. Use a monospaced family
>   (Geist Mono or JetBrains Mono) for *numbers in cards* — that's an
>   intentional touch the rest of the dashboard uses.
> - Iconography: outlined Material Symbols only. No filled glyphs.
>   No emoji in the rendered UI.
>
> **Page structure (top → bottom):**
>
> 1. **Header** — single line. Left: page title `Workout` in 18px
>    semibold + tiny "TODAY 2026-05-08" (uppercase, 11px, 2px letter
>    spacing). Right: outlined `Refresh` icon button + a 3-dot
>    overflow that opens a menu with `Charts`, `History`, `Catalog`,
>    `Training prefs`.
>
> 2. **Week strip** — 7 day cells, Monday-first. Each cell is a
>    rounded 8px chip showing the abbreviated weekday on top + a
>    coloured 8px circular pip below for status (green completed,
>    amber in-progress, slate skipped, brand-red planned today,
>    transparent for projected workout days that haven't run yet).
>    Today's cell has a 1.5px brand-red border. All cells are
>    tappable; on tap, navigate to the day-view route. The strip is
>    horizontally swipeable but starts centred on today.
>
> 3. **Today header card** — full-width raised surface. Inside:
>    - Big split label: `Push day` (or `Pull`, `Legs`, `Upper`,
>      `Lower`, `Full body`, `Rest`). 18px semibold.
>    - One-line muscle list, dot-separated:
>      `Chest · Shoulders · Triceps`. Secondary text colour, 12px.
>    - Three small chips below: `4/12 sets`, `recovery 78`, `sleep 6.4h`.
>      Pill shape, 1px outline-variant border, surface-low fill,
>      muted text.
>
> 4. **"Why this workout?" expandable** — collapsed by default,
>    surface-low, full-width. Header line shows the title and a
>    chevron (▸ collapsed, ▾ open). Tapping reveals three short
>    paragraphs in the secondary text colour:
>    - *Why this split:* "Today's push focus comes after Monday's
>      pull. You're on a 4-day upper/lower rotation."
>    - *Why these exercises:* "Picked from your favourites and last
>      session's variety bucket — no exercise repeats inside a 7-day
>      window."
>    - *Why these targets:* "DB Bench bumped 27.5 → 30 lb after last
>      set 3 came in at RPE 7. Wrist-weight micro-loaders fill the
>      gap between dumbbell pairs."
>
> 5. **Exercise cards** — vertical list, 12px gap. Each card is a
>    raised surface with this structure:
>
>    - **Top row**:
>      - Order number + exercise name in 16px semibold
>        (e.g., `1. Dumbbell Bench Press`).
>      - Beneath the name, a single line summary: `4 × 8-12 @ 30 lb
>        · 90 s rest`, all monospace numbers, 12px secondary text.
>      - Right-aligned: optional 64×64 rounded thumbnail (the
>        exercise diagram). If no image, render a square outlined
>        placeholder.
>      - Far-right corner: a 3-dot overflow IconButton.
>
>    - **Action row** — two text buttons + flex spacer + the
>      overflow menu:
>      - `YouTube ↗` — opens search for the exercise's form.
>      - `Swap` — paired with an outlined `swap_horiz` icon. Only
>        visible if no sets logged yet.
>      - The overflow menu is left in place so the user can
>        ❤ Favorite / 👎 Avoid / 🚫 Disable / Reset.
>
>    - **Sets list** — one row per planned set:
>      - Logged set: small number (1, 2, 3...) in muted, then the
>        actual weight × reps in primary text, then `RPE 7` chip
>        coloured by rating (1=red → 5=green), trailing green ✓.
>      - Active set (next in line): inline weight input + reps
>        input + 5-button RPE picker (small rounded squares, each
>        coloured per scale: 1 red → 5 green). Two action buttons
>        right-aligned: `Log set` (primary) and `Failed` (outlined,
>        muted red).
>      - Pending future set: shows `set N · waiting` in dim text.
>
>    - **Superset indicator** — when this card is in a superset
>      pair, the card has a 2px left border in a colour stable per
>      superset id (avoid red — pick from a small palette like
>      `#A855F7`, `#06B6D4`, `#84CC16`). Above the title, render a
>      small "⇄ Superset 1 — alternate with *Bent-Over Row*" hint in
>      the same colour, 11px semibold.
>
>    - **Completed state**: when every set is logged, the card uses
>      the surface-low colour (subtler) and order number gets a
>      ✓ badge. Card is still tappable but expanded view is
>      collapsed by default.
>
> 6. **Rest timer bar** — appears between the today header and the
>    exercise list whenever a set was just logged. Sticky to the
>    top of the scrollable region. 2-line component: countdown in
>    big mono digits, total rest below. Two buttons: `+30s` and
>    `Skip`. When the timer hits zero, the card flips to a green
>    tint and the digit area says `Rest done — go!`.
>
> 7. **Empty / rest day**: if the planner returned a rest-day
>    recommendation, the today header card shows a softer green
>    border + a `🌙` glyph (replace with `bedtime` outlined icon)
>    and a short reason line ("HRV 22% below baseline — recover
>    today.") plus a `Push through anyway` outlined button.
>
> **Charts route (separate screen reachable from the header
> overflow):** range chips along top (`7d / 30d / 90d / 1y`).
> Stacked cards:
> - Overview row: 4 stat boxes — workouts, sets, total volume,
>   avg RPE.
> - Daily volume: line chart, surface-1 background, no extras
>   beyond y-axis ticks at min/mid/max + day-of-week x-ticks.
> - Volume by muscle: horizontal bar list, each row coloured by
>   muscle group (use the HR-zone-style palette but mapped per
>   muscle). Bar fill is the muscle colour, rest of the row is
>   surface-low.
> - Weight progression: line chart with a dropdown picker above it
>   to switch exercise. Show dots on each session. Dashed thin
>   trend line in the same colour at lower opacity.
>
> **Day-view (read-only, for past sessions or future preview):**
> Same header chip + title (`Mon, May 5`). Stacked exercise cards
> showing only logged sets (no active row). For future days, the
> top of the page shows a `Preview` chip in muted yellow. Don't
> render swap/log buttons.
>
> **Output format:** generate the parent React component +
> sub-components in TypeScript with Tailwind. Use semantic class
> names so I can rename to my Vue conventions. Mobile-first: the
> grid above 600px width should stay single column for the sets
> list, but the page itself can be max-width 720px on desktop with
> left + right gutter. No animations beyond a 150ms ease-in-out
> on the rest-timer-done flip.

---

## Notes for me / the AI

- The myvitals frontend is **Vue 3 + Vite + ECharts**, not React. After
  Stitch generates the React mock, I'll port the layout to a `Workout.vue`
  view. The colour tokens above already exist on the dashboard
  (`MV.Bg`, `MV.SurfaceContainer`, etc. on phone; `--bg`, `--surface`,
  `--accent` CSS vars on web).
- Charts will land on `/workout/strength/charts` (already routed) using
  the new `GET /workout/strength/stats` endpoint.
- Exercise cards on the *active* workout screen need the per-set inline
  inputs + the rest timer; the design above describes the full state
  machine. The day-view variant is the read-only subset.
- Any iconography should map to Material Symbols Outlined names so I
  can paste them straight into Vue without further translation.
