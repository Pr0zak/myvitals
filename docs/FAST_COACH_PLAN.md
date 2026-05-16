# #FAST-COACH — Fasting Recommendations, Goals, and Workout Coupling

Plan dated 2026-05-15. Defaults from the open-decision matrix have been
locked in; this doc is the durable reference. Track via the `FAST-16`
through `FAST-19` mnemonics in `TODO.md`.

---

## Motivation

The fasting feature shipped (FAST-1..15) with a complete data + UI loop:
sessions, logs, widgets, religious presets, scheduled mode, fasting in
the AI verdict and deload payloads. What it doesn't yet do:

1. **Recommend** whether today is a good day to fast.
2. **Live inside the goals system** — no `fast_streak` or `fast_target`
   `kind`, no profile↔goal bidirectional sync, no AiAlert when a target
   hits.
3. **Modulate the workout generator** — strength prescription doesn't
   know the user is 18 hours fasted and shouldn't be doing 3-rep
   compounds. Coach payloads don't see fasting status as a separate
   signal from training load, so "HRV down" reads as overtraining when
   it's actually compressed by a fasting streak.

This plan closes those three gaps.

---

## Family overview

| Mnemonic | Subject | Effort | Blocked by |
|---|---|---|---|
| FAST-19 | Plumb `fasting_today` + `fasting_7d` into workout / recovery / verdict coach payloads | ~half day | — |
| FAST-17 | `fast_streak` Goal kind (sync with `user_profile.fasting_target_hours_per_week`, progress bar, auto-complete + AiAlert) | ~half day | — |
| FAST-16 | `POST /ai/coach/fasting` — structured "should I fast today?" card | ~1 day | FAST-19 |
| FAST-18 | Fasting-aware strength generation: volume / rep-range modulation + UI banner | ~1 day | FAST-19 |

**Ship order:** FAST-19 → FAST-17 → FAST-16 → FAST-18. FAST-19 first
so downstream surfaces (coach card + generator) start with richer
context from the first release tag.

---

## Locked decisions (defaults from planning session)

- **Auto-break-fast:** **NO**. The "Should I fast" card may include
  `recommendation: break_now`, but the system never acts on its own —
  the user taps to break. This is health software, not an alarm.
- **Strength volume modulation magnitude:**
  - `< 18h fasted` → no change
  - `18-24h fasted` → drop 1 set per exercise, +15s rest (~−20% volume)
  - `≥ 24h fasted` → drop 2 sets per exercise on isolation, swap one
    compound to a Z2 cardio block; +30s rest (~−30% volume)
- **Hard rule against heavy strength on long fast:** **YES**. At
  ≥ 18h fasted, refuse to prescribe `main_compound` 3-5 rep ranges
  (strength-focus goal). Route to hypertrophy 8-12 instead. Injury
  risk reduction; matches the "fasted lifters bend technique under
  near-max load" pattern in the literature.
- **Goal kinds to ship first:** `fast_streak` only. Shape-matches the
  existing sober streak code path closely, smallest behaviour change.
  `fast_target` and `fast_hours` can follow if the user wants them.
- **Fasting coach sees weight goal progress:** **YES**. Lets the card
  say "down 1.2 kg over 4 weeks at 14:10 — no need to push to 18:6"
  vs "weight plateau at 14:10 → suggest 16:8 three days this week".
- **Religious-fast windows (Ramadan / Lent / Yom Kippur):** existing
  presets stay; the coach card MUST NOT recommend breaking a religious
  fast. Detect via `fasting_sessions.protocol` containing `ramadan`,
  `lent`, or `yom_kippur` and refuse `break_now` outputs.

---

## FAST-19 — Coach payload plumbing

Pure infrastructure. No new endpoints, no client changes.

**Backend:** `integrations/claude.py`

- New helper `_fasting_status_summary(db) -> dict`:
  - `active`: bool
  - `current_hours`: float | null
  - `current_protocol`: str | null
  - `current_stage`: str | null  (e.g. "ketosis", "autophagy", "fed")
  - `last_7d_hours_fasted_total`: float
  - `last_7d_fast_count`: int
  - `last_7d_longest_h`: float
  - `is_religious`: bool — true if any 7d row's protocol is religious.

- Inject as `fasting_status` into:
  - `build_workout_coach_payload`
  - `build_recovery_coach_payload`
  - `build_verdict_payload`
  - `build_summary_payload`

- System prompts (one paragraph each, both recovery + workout):
  > "long fasts compress HRV and lower RHR without indicating
  > overtraining — check fasting_status.last_7d_hours_fasted_total
  > before recommending a deload. If the user has been fasting ≥ 18h
  > on multiple nights, the autonomic signature is fasting-driven."

**Acceptance:** `curl POST /ai/coach/workout` returns a card whose
evidence cites `fasting_status` when relevant. Cache key bumps via
payload-hash so existing cached cards regenerate once.

---

## FAST-17 — `fast_streak` Goal kind

**DB:** no migration needed. `AiGoal.kind` is a `String(32)`; just adds
a new accepted value.

**Profile:** add `fasting_target_hours_per_week: int | null` to
`UserProfile`. Migration: alembic-generated, default null.

**Backend:**

- `_profile_target_for_kind(kind="fast_streak", prof)` returns
  `prof.fasting_target_hours_per_week`.
- `_check_goals_for_completion` adds a `fast_streak` branch:
  - `current_value` = consecutive days since last day where total
    fasted hours fell below the target / 7 (a "missed" day).
  - Crossing target → AiAlert kind `fast_streak_reached`,
    severity `good`, dedup_key per-goal.

**Web:** `Goals.vue` already renders any `kind` generically — confirm.
The Goals table needs a new pill colour for `fast` (cyan).

**Phone:** `GoalsScreen.kt` parity — add kind → label mapping.

**Acceptance:** profile sets target = 80h/wk → goal created with
`target_value=80` automatically. Hitting the streak fires an alert
that the phone notification channel picks up (via ALERTS-4).

---

## FAST-16 — "Should I fast today?" coach card

**Backend:** `integrations/claude.py`

- `FASTING_COACH_TOOL` schema:
  - `recommendation`: `fast` | `eat_normally` | `light_fast` | `break_now`
  - `tone`: `good` | `warn` | `bad` | `neutral`
  - `protocol_suggestion`: `"16:8"` | `"18:6"` | `"20:4"` | `"24h"` | `null`
  - `best_window`: free-form ("18:00 today → 12:00 tomorrow") | null
  - `goal_alignment`: ≤ 30 words — how this fits the active weight /
    fasting goal
  - `evidence`: 2-4 bullets
  - `caveats`: array — religious-fast safeguard goes here, drug timing,
    pregnancy/lactation if profile flagged, etc.

- `build_fasting_coach_payload`:
  - 28d daily rows (HRV/RHR/recovery/readiness/sleep/sleep_debt_h)
  - 14d fasting history (per-fast: started_at, duration_h, protocol)
  - Last 14d fasting_logs (FAST-13: hunger, mood, hydration, notes)
  - Today's planned strength split + recovery_score
  - Active weight goal current_value / target_value / progress_pct
  - Active fasting goal target_value if any
  - `is_religious_active`: bool — refuses `break_now` if true
  - `recent_alerts`, `top_correlations`, `wow_deltas`

- System prompt: explicit RULES list ending with
  > "If `is_religious_active` is true, `recommendation` MUST NOT be
  > `break_now`. The user is observing a religious fast; coaching is
  > limited to hydration + reframing benefits."

- `POST /coach/fasting` + `GET /coach/fasting/latest` mirror the
  established coach pattern.

**Web:** `Coach.vue` — 5th card (after Workout, Sleep, Recovery,
Cardio). Hourglass icon. Top-of-body shows `recommendation` chip
in tone colour, `protocol_suggestion` below it. "Start fast" button
deep-links to `/fasting?protocol=...` and pre-fills the start dialog.

**Phone:** `CoachScreen.kt` — 5th card with `Outlined.Hourglass` icon.
"Start fast" button navigates to FastingScreen with the protocol
preselected.

**Fasting page hero:** new top-of-page card mirroring Coach card.
Web + phone parity.

**Acceptance:** card renders `eat_normally` for a sleep-debt-3h /
HRV-down/training-tomorrow profile. Renders `break_now` for an
in-progress fast with HRV cliff overnight. Renders `fast` aligned
to weight goal when progress is stalling.

---

## FAST-18 — Fasting-aware workout generation

**Backend:** `analytics/strength.py`

- `generate_plan` accepts `fasting_context: dict | None`:
  ```
  {
    "active": bool,
    "current_hours": float,
    "stage": "fed" | "ketosis" | "autophagy" | "deep_autophagy",
  }
  ```
- New helper `_fasting_modulation(ctx) -> ('normal' | 'volume_-20%'
  | 'volume_-30%_cardio_priority', notes_str)`.
- Apply at three points:
  1. `prescribe_slot` — when goal=`strength` AND `active` AND
     `current_hours ≥ 18`, route to `hypertrophy` rep ranges
     (8-12 instead of 3-6). Hard rule.
  2. `select_exercises_for_split` — `volume_-20%` drops `target_sets`
     by 1 across the picked set (min 2). `volume_-30%` drops 1 from
     compounds, 2 from isolation, and converts one compound to a
     prescribed cardio block.
  3. `GeneratedPlan.notes` — append `"Fasted 18h — strength block
     scaled back 20%; expected to finish under 30 min."` so the UI
     surfaces it.

- `WorkoutOut` payload adds `fasting_context: dict | null` field
  (state, hours, modulation, recommend_cardio_swap). Derived at
  serialisation, not stored on the row.

- `/workout/strength/today` reads current fasting status via
  `_fasting_status_summary` and passes through.

**Web:** `StrengthToday.vue` — amber banner under the workout head
when `workout.fasting_context.modulation != 'normal'`:
> "You're 18h fasted. Volume trimmed 20%, rest extended 15s."

**Phone:** `StrengthTodayScreen.kt` — parallel banner Card above the
exercise list, same copy.

**Acceptance:** generate plan with active 19h fast → strength split
returns with `target_sets=2` (was 3), notes contains the scaled-back
explainer, UI banner renders. Generate same split with no fast →
unchanged.

---

## Cross-task plumbing checklist (do once during FAST-19)

- [ ] `_fasting_status_summary` lives in `integrations/claude.py`
      module top (not nested in a single builder) — reused by 5+
      callers.
- [ ] `fasting_sessions.protocol` LIKE matching for religious fast
      detection is case-insensitive (`Ramadan`, `ramadan`, `RAMADAN`).
- [ ] Cache `range_kind` strings: `coach_fasting`, no `_v2` suffix
      (clean slate, no migration of existing rows).
- [ ] Parity check: `Coach.vue` ↔ `CoachScreen.kt` (already paired),
      `StrengthToday.vue` ↔ `StrengthTodayScreen.kt` (already paired),
      `FastingScreen.kt` ↔ `Fasting.vue` (add to pair-map if missing).

---

## Acceptance criteria (whole family)

Demo scenario from a single 30-day window:

1. User has a weight goal `target_value=70 kg`, `current_value=72 kg`,
   stalled for 3 weeks. → Coach.vue shows fasting card recommending
   `fast` with protocol `16:8`. Tap → fasting page hero pre-filled.
2. User starts an 18h fast at 20:00. → Tomorrow's strength workout
   regenerates with `-20%` volume, banner visible.
3. User skips dinner (24h fast cumulative). → Coach card flips to
   `break_now` with caveats; fasting page hero matches.
4. User completes goal-aligned fast streak (5 consecutive days at
   80h+/week). → AiAlert `fast_streak_reached`, phone notification
   fires (ALERTS-4), GoalsScreen shows 100% complete.

All four steps must work without further configuration once FAST-16
through FAST-19 ship.

---

## Out of scope (this round)

- Other goal kinds (`fast_target` / `fast_hours`) — gated by the
  user using `fast_streak` first.
- Strength generator's fasting modulation acting on cardio days —
  cardio plans are short and don't have the same injury risk.
- Voice / TTS read-out of the coach card — separate AI-batch-3 item.
- Auto-break-fast on bad signal — explicitly rejected (see locked
  decisions).
