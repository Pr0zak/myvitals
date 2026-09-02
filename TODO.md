# myvitals — Pending Work

Snapshot updated **2026-08-23** after shipping **v0.26.9**; prior snapshot
**2026-08-01** after **v0.7.347**. The gap between those two is large: the
version line jumped from `0.7.x` to `0.15.0` for the meals feature and ran
to `0.26.9`, covering MEAL-1 through MEAL-9, the AI-CLI provider, and two
rounds of food-search ranking fixes. All deployed and verified live on
CT 104.

Numeric task IDs are session-scoped. Use **mnemonics** (e.g. `FITBIT-2`)
as the durable identifier. At the start of a new session, ask Claude to
"rehydrate the task tracker from TODO.md + memory" and it'll re-verify
each item against the code and re-instantiate via TaskCreate.

**Carried items below were not re-verified on 2026-08-23.** They are
reproduced as written on 2026-08-01; check each against the code before
acting on it.

---

## Active — actionable now

## #OG2 — openGym second-pass teardown (2026-08-29)

A second teardown of `gitlab.com/DuarteSantos8/opengym`, run because the
first one (`#ENHANCE`, researched 2026-07-25, shipped v0.7.322→342) saw
openGym only up to ~v1.2.5. Everything since — v1.2.6 through v1.2.11 plus
the unreleased drop-set/rest-pause work in its `PROJECT_CONTEXT.md` — was
unexamined. 110 elements studied, 86 survived an adversarial refutation
pass, 24 confirmed already shipped.

The licensing rule from the first pass still binds: **openGym is AGPL-3.0
and myvitals is not. Reimplement behaviour from the described design; never
copy source.** Where a constant is recorded below it is recorded so the
decision can be judged, and in every case the recommendation is to
re-derive it against this user's own data rather than adopt it.

Ten of these are defects rather than missing features — the app is
currently telling the user something untrue — so Phase A runs first
regardless of how appealing anything below it looks.

Report artifact: `https://claude.ai/code/artifact/bb1f86ee-8e76-4c9c-a776-beeb1a6968c8`

### Phase A — correctness (the app is currently wrong)

| ID | Task | Size | Surface |
|---|---|---|---|
| OG2-A1 | `last_target_weight_for_exercise` averages warm-up and drop sets into the next prescription | S | backend |
| OG2-A2 | A session logged without ratings falls through to `starting_weight_lb`, discarding real history | S | backend |
| OG2-A3 | `/stats` + `/volume-trend` drop every null-weight set, so a bodyweight day counts as zero | M | backend |
| OG2-A4 | `/upcoming` carries its own weekday table that disagrees with the generator at `days_per_week=2` | S | backend |
| OG2-A5 | Weight deltas hard-code down-is-green, on `/weight` and again on Today | S | web |
| OG2-A6 | An equipment change neither regenerates today's plan nor warns that it prescribes kit you no longer own | M | backend + both |
| OG2-A7 | Rest timer drifts on web, and both surfaces count down after the final set of the session | M | both |
| OG2-A8 | Wake lock absent on web; on phone it is keyed to the composable, not to the workout | S | both |
| OG2-A9 | A logged set cannot be corrected or removed from either client | M | both |
| OG2-A10 | Health Connect never deduped against itself, so one ride promoted twice | S | backend |

### GH-EXPIRY — Google Health dies every 7 days (tabled 2026-08-31)

The server-side Google Health OAuth poll has been failing since 2026-08-28
with `invalid_grant` / "Token has been expired or revoked". Not a myvitals
bug, and the timestamps settle it to the second:

```
connected_at  2026-08-21 16:39:44.099
expires_at    2026-08-28 16:39:43.200      -> 6d 23:59:59.1
```

The hourly refreshes stayed phase-locked to the connect instant and drifted
under a second across the week; the one due at exactly the 7-day mark was
refused. That is the signature of an OAuth client left in **Testing**
publishing status, whose refresh tokens Google expires after 7 days no
matter how recently they were used.

Ruled out: token rotation. `valid_access_token`
(`integrations/google_health.py:434`) does persist a rotated refresh token
when Google returns one, so the usual "forgot to save the new token" bug is
not what happened.

**Recovery** is entirely on Google's side and needs no code. Publish the
OAuth client to *In production* on the consent screen — unverified is fine
for a single user, showing an interstitial and capping at 100 users — then
Settings -> Google -> **Reconnect**, approve, let the `localhost` page fail
to load, and paste that whole URL into *2. Finish connecting*. Reconnecting
without publishing restores service for exactly seven more days.

Three things this exposed that ARE ours, none yet done:

- The setup copy we ship tells the user to add themselves as a test user
  (`frontend/src/views/Settings.vue:2745`, and the module docstring at
  `integrations/google_health.py:13-17`). That reasoning checked the
  verification gate — the 100-user cap — and missed the separate
  testing-mode gate, so the weekly expiry was baked in at design time.
  Nothing in the repo mentions it. The setup text should.
- The failure handler records `last_error` and re-raises without clearing
  the token, disabling the poll, or backing off, so a dead grant is retried
  every 15 minutes indefinitely. An auth failure will never recover on its
  own and is a different class from a transient network failure; the poll
  does not distinguish them.
- Nothing surfaced it. `data_health.py` reports the integration as `status:
  "error"` with the message, and it went unnoticed for two days until
  someone ran a manual check. Strava got a reconnect banner in v0.7.319
  after the identical silent-failure shape; Google Health has no
  equivalent. Note the HEALTH-1 restraint applies to *stale streams*, and a
  revoked grant is not one — it is a fault that needs a human.

### Phase B — structure

| ID | Task | Size | Surface |
|---|---|---|---|
| OG2-B1 | One shared session reducer (`ok`/`enough`/`low`/`count`/`stalls`) for the thirteen readers of `strength_sets` | L | backend |
| OG2-B2 | One `next_prescription()` entry point; generate/swap/ad-hoc currently disagree | M | backend |
| OG2-B3 | Every target carries its own reason as structured data, not prose behind a tap | M | both |

### B1 follow-ons (deferred with reasons, 2026-09-01)

`stall_count` was specified for B1 and deliberately not shipped. An
adversarial review measured the streak across all 143 exercises with history:
the maximum consecutive shortfall is **1**, and zero exercises reach 2 or 3,
so the function could only ever return 0 or 1 — and nothing consumed it.
Shipping a pure function with no caller and a promise attached is the
liability the rest of this backlog argues against.

Its consumer, when there is one, is the coach payload.
`build_deload_payload` sends four coarse 14-day numbers, and its
`missed_or_skipped_sets` counts rows with `actual_reps IS NULL` — of which
production has **zero**, because an unlogged set has no row at all. So a
partial session is invisible to the deload check today, which is the same
blind spot B1 closed in the prescription, in a third place. Wiring `enough`
per exercise into that payload is the small, well-defined change that would
make a stall count worth having.

Note it must still not be ACTED on. Three deloads already compound — the
rating policy's 7.5% cut, the recovery factor (0.85 x 0.90, then
generate_plan's own 0.90 on an easy day, so 0.6885 is reachable), and PROG-1's
fail streak.

Also found by that review and not yet done:

- `recent_ratings_by_exercise` has no workout-status filter at all despite a
  docstring claiming "completed workouts", and no set_type filter — so a
  warm-up rated Easy is evidence about a lift, and it gates SELECTION at
  `AUTO_AVOID_THRESHOLD`, meaning it can rotate an exercise out of the plan.
- `explain_workout` narrates the prescription but reads a *different* set: the
  heaviest set of any prior session, filtered only on `actual_weight_lb IS NOT
  NULL`. It can cite a session the reducer never looked at. That is OG2-B3's
  job — the explanation and the number must come from one read.
- `_advance_program_on_complete` (PROG-1) shares the set_type constant but
  drops the `¬skipped` predicate and advances a linear program off a single
  logged set. Latent while PROG-1 is off in production.

### Phase C — the feature

| ID | Task | Size | Surface |
|---|---|---|---|
| OG2-C1 | Per-muscle fatigue, crossed with the systemic recovery signal openGym does not have | L | backend + both |
| OG2-C2 | The muscle silhouette shown at planning time, not only in review | M | both |
| OG2-C3 | The progression chart picks its metric, unit and caption from what was logged | M | both |
| OG2-C4 | Every rated average shows its denominator; e1RM names its source set | M | both |

### Phase D — follow-ons

`OG2-D1` bodyweight rep ladder (reps → sets → refuse) ·
`OG2-D2` session notes in three lifetimes, one pinned ·
`OG2-D3` tap-to-read markers on the phone's charts ·
`OG2-D4` goal line on the phone weight chart ·
`OG2-D5` effort encoded on the progression dot ·
`OG2-D6` year strip shaded by time, opening on today, tappable ·
`OG2-D7` one muscle vocabulary and one reused intensity ramp ·
`OG2-D8` warm-up ramp derived after the prescription ·
`OG2-D9` pair / unpair / reorder mid-session ·
`OG2-D10` sparse date → day-type override ·
`OG2-D11` program state replayed from the log (closes PROG-STATE-1) ·
`OG2-D12` snapshot muscle attribution at log time ·
`OG2-D13` retained strength, named honestly ·
`OG2-D14` curated import alias table ·
`OG2-D15` the "Log weight" button actually logs weight ·
`OG2-D16` light theme on the phone

### Considered and rejected

"Expected current 1RM" (openGym's own weakest number — a decay constant
with no evidence basis, a floor that reports half your best forever, and a
reset from one light set; fights `projection.py`'s refuse-rather-than-guess
rule). openGym's fatigue reference EWMA ported as-is (dragged down by a
light week, so post-deload training reads as more fatiguing than the same
work before it — myvitals labels deloads explicitly and can exclude them).
Drop-set / rest-pause as nested set shapes (`StrengthSet` is flat, `log_set`
is idempotent on `(workout_exercise_id, set_number)`, and the phone's
offline replay depends on that). Freestyle sessions, plan-file sharing,
passkeys, multi-profile, UI i18n, PWA demo and guest mode (all solve
openGym's problem of being software other people install). Multi-gym
equipment profiles. Hand-rolled SVG charts and a replacement icon set
(downstream of a dependency-light constraint myvitals does not share).
Sheet-stack back handling (not applicable — native Compose already owns it).

---

### SEARCH-MULTIAXIS — "pork chop" needs a pin the current tier cannot express
Source: v0.26.9 catalog audit. The right row requires cut AND trim AND raw
simultaneously (center loin ∧ lean-and-fat ∧ raw), and `_PREFERRED_VARIETY`
is an any-of substring tier, so every single qualifier tested lands on a
wrong axis — "center loin" resolves to the lean-only row (the exact silent
fat-trim the audit was hunting), "lean and fat" to a cooked blade chop.
Deliberately not fixed: the incumbent's error is modest (11.1 vs 9.0 g fat,
cooked vs raw) and an all-of pin would need a near-full-name phrase that
rots on the next catalog rebuild. Revisit only if the tier gains AND
semantics. Same shape may exist for other multi-axis cuts.

### MEAL-BARCODE — barcode scanning via Open Food Facts
Phase 7 of `docs/MEALS_PLAN.md`, offered and not built. The label scanner
(MEAL-8) covers the same intent by photo and is arguably better, since it
works for products with no barcode entry. Worth doing only if typing
friction is measurable after real food-log use.

### MEAL-OBSERVED-TARGETS — derive energy targets from logged intake
Phase 8 of `docs/MEALS_PLAN.md`. `analytics/targets.py` always reports
`basis: "estimate"` (Mifflin-St Jeor is an equation applied to a profile,
not a measurement) and `prep_plans.target_basis` is already stored per
plan so the two can be told apart in hindsight. Open question is how many
complete food-log days is enough for an observed figure to BEAT the
equation rather than just be noisier. Blocked on there being enough
complete days.

### PROG-STATE-1 — program progression state can be reverted by a stale equipment PUT
Source: v0.7.342 adversarial review (see memory `myvitals-prog1-known-issue`).
`_advance_program_on_complete` writes progression state (current_weight_lb,
consecutive_fails, last_advanced_on) into `user_equipment.payload`, which the
config UIs round-trip and `put_equipment` overwrites wholesale. A prefs save
from a payload loaded before a workout completion silently reverts the
advance. Low severity (narrow window, single user, SWR reload). Fix needs a
**product decision**: make progression bookkeeping server-authoritative in
`put_equipment` (running-lift weight then becomes non-editable from the config
screen — reset = remove+re-add, or add a "reset weight" action), OR move the
state to a separate server-owned store. Deferred pending that call.

### WEB-WORKOUT-PARITY — port the phone v0.7.312 active-workout redesign to web
Source: neon memory. Phone got the compact one-tap set-table + Canvas
countdown-ring rest timer + NOW highlight + session progress bar in
v0.7.312; web `StrengthToday.vue` is still the old `<input>` table
(L1214-1276) + text rest timer (L1061-1075). `parity_check.py` still
flags the pair. Port it, keeping the existing `logSet` path (offline
buffer / progression / bilateral) untouched. The v0.7.318 timed-hold
countdown already shipped to web and is unrelated — leave it.

### SPO2 — wire SpO2 end-to-end (semi-blocked)
Source: TODO.md. Declared as an HC read perm
(`HealthConnectGateway.kt:32`, counts in "12/12 granted") but never
read or transmitted: `SyncWorker` doesn't read `OxygenSaturationRecord`,
`DataMapper.toBatch` has no spo2 param, `IngestBatch`/backend `Batch`
have no spo2 field. The `vitals_spo2` table already exists (alembic
0001) with zero writers — **no migration needed**. Wire the chain
(SyncWorker → DataMapper → IngestBatch → backend Batch → `_bulk_upsert`
→ `models.Spo2`) + read endpoint + web/phone display. **Semi-blocked:**
the PW3/PW4 firmware bug (see CLAUDE.md) zeroes SpO2 until Google ships
the sensor-permission fix, so this yields no live data yet — but do the
wiring so it's ready. Lower urgency for that reason.

### HOMELAB-DOC — CT 104 dynamic-host docs + deploy skill (outside this repo)
Source: TODO.md + memory. The homelab root `CLAUDE.md` still pins CT
104 to a single node; ProxBalance migrates it. Switch to the
pitstop/homedepot "(currently pveX, dynamic)" convention. The
`myvitals-deploy` skill hard-codes the node and breaks after a
migration — make it discover the host dynamically (like the
pitstop-*/homedepot-* skills). **New (2026-07-22):** it must ALSO stop
building locally-only — the CT auto-update cron reverts any untagged
local `docker build` within 15 min; see memory
`myvitals-deploy-requires-tag`. Touches files **outside** the myvitals repo.

---

## Blocked / needs input

### FITBIT-2 — verify `parse_fitbit_zip` against a Google Health Takeout export
**Blocked on** a Takeout ZIP from takeout.google.com — no code change
can close it. Parser is intact (`integrations/imports.py:84`, wired at
`api/imports.py:202`); no test covers it. When the ZIP lands: POST
`/imports`, confirm the post-rebrand filenames still match all 7
`files_seen` categories, watch for the legacy wrist-temp log line,
update regexes if detection drifted, and ideally add a redacted
fixture + regression test.

### NEON-PROMOTE — decide whether Neon Refined becomes the default theme
**Needs user.** Neon Refined (A1) shipped opt-in on both surfaces
across v0.7.316-318; Classic is still the default. Promote to default
or keep opt-in? If promoted, audit remaining classic-only surfaces.

### BODY-NUMBER-FONT — Neon Refined Body-card number font mismatch
**Needs user pointer.** User says the Body-card metric numbers "don't
match the rest of the theme," but no code-level diff was found (cards
use NeonNumber / Space Grotesk like elsewhere). Ask which surface and
which reference element before touching fonts.

---

## Backlog (not scoped)

- **STRAVA-OAUTH** — re-enable the OAuth sync path (only truly
  hands-off, no-password, no-cookie-expiry option). User signs in via
  Google/email-code, so cookie paste is the current path (chosen
  2026-07-22). OAuth authorize is password-agnostic and our code
  (`integrations/strava.py`) already handles rotating refresh tokens —
  BUT Strava now gates API "Standard Tier" (= any personal app) behind
  a paid Strava subscription from 2026-06-30 (existing devs get a
  ~3-month free transition). Re-enable IF the user gets a Strava sub, or
  during the free window. Would also need re-adding the scheduled poller
  (disabled v0.7.275) + a fresh authorize (token expired 2026-06-05).
  See memory `myvitals-strava-cookie-sync`.
- **STRAVA-OTC-AUTOLOGIN** — free + hands-off cookie refresh: headless
  browser submits email → Strava emails a one-time code → backend reads
  it from a dedicated IMAP inbox → captures a fresh cookie on a
  schedule. User declined 2026-07-22 (fragile + needs IMAP setup), but
  it's the only free way to make cookie mode self-heal. Not started.
- **COACH-BATCH3** — future Coach sub-cards: week-vs-week diff view,
  clickable source citations, smart cache invalidation, ~~local-LLM
  (Ollama) provider~~ (shipped as TD-8: `integrations/llm/` provider seam,
  Anthropic default plus any OpenAI-compatible endpoint), voice Q&A.
  Each follows the "Adding a new card"
  pattern in CLAUDE.md.
- **MULTI-USER** — single-user assumed throughout; no `user_id` on
  most tables. Big schema+auth+client refactor. No demand yet.

Intentional divergences (by design, **not** tasks): phone
`SettingsScreen` left classic (config surface — Strava cookie config is
web-only, confirmed 2026-07-22 and in `parity_check` WEB_ONLY_OK); web
`Coach.vue`/`Journal.vue` auto-adapt via global tokens (parity_check
flags them phone-only); Coach tab intentionally phone-removed (v0.7.309).

---

## #ENHANCE — strength/workout backlog ✅ ALL SHIPPED (v0.7.322→342)

The full 13-task #ENHANCE backlog (researched 2026-07-25 from openGym +
exercises-dataset) is **shipped, deployed to CT 104, and verified** on both
surfaces. Durable design notes: memory `myvitals-strength-enhance-backlog`.

| Mnemonic | Task | Shipped |
|---|---|---|
| e1RM-1 | e1RM engine + per-exercise progress curve | ✅ |
| PR-1 | Strength PR detection: set-log badge + Records card | ✅ |
| LOAD-1 | "How to load it" micro-loader combo | ✅ |
| LOG-1 | Previous-performance ghost prefill | ✅ |
| MMAP-1 | Anatomical muscle-map shaded by volume | ✅ |
| IMPORT-1 | Strong/Hevy/FitNotes/AppleHealth importers | ✅ |
| ANIM-1 | Pseudo-animated demo (start/end JPG crossfade) | ✅ |
| SETTYPE-1 | Set-type tags + volume exclusion | ✅ |
| VOLT-1 | Weekly-volume-over-time (mesocycle) chart | ✅ |
| CAT-1 | Metadata-only catalog merge (MIT dataset) | ✅ |
| BODY-1 | Body circumference measurements + trends | ✅ v0.7.339 |
| PROG-1 | Opt-in program mode (Greyskull/linear/double) | ✅ v0.7.340 |
| PDF-1 | Print/PDF export of today's workout | ✅ v0.7.341 |

Licensing rules that shaped the work (still binding for follow-ons):
openGym is **AGPL** → algorithms reimplemented from scratch, never copied;
exercises-dataset GIFs are "with permission" only → **never committable**
(ANIM-1 used bundled public-domain JPGs); MMAP-1's body SVG is permissive.

Post-ship fixes (v0.7.342) from the full adversarial review, plus the one
**deferred** item `PROG-STATE-1` (see Active above).

**Deferred follow-ons** (not part of the 13; still open backlog): muscle
*recovery/freshness* body map (reuse MMAP-1 SVG + recovery_score); post-workout
session-summary card (needs PR-1 + e1RM-1); relative-strength e1RM/bodyweight
trend (needs e1RM-1 + BODY-1); consistency-streak / weekly-target ring;
tap-a-muscle drill-down (needs MMAP-1); user-created custom exercises (generator
blast-radius); phone Live-Activity persistent workout notification.

**Confirmed already present (dropped):** weight-goal dashed line (Weight.vue:237),
rest/hold + missed-workout notifications, workout calendar-heatmap (both surfaces),
supersets, timed-hold countdown, double-progression plateau logic, per-set 1-5
rating (RPE-ish). Not proposed: openGym plan-file *sharing*, passkey/multi-profile/
i18n-UI (single-user self-host, irrelevant).

---

## Resolved — meals line, v0.15.0 → v0.26.9 (2026-08-23)

Ten shipped items. Design record is in CLAUDE.md and
`docs/MEALS_PLAN.md`; only the parts that constrain future work are
repeated here.

- **MEAL-1..MEAL-8** — foods, recipes, pantry, per-meal fat, weekly plan,
  shopping list, AI suggestions, food log, ingredient concepts, one-tap
  staples, pantry-from-a-photo, nutrition-label scanning. Both surfaces.
- **AI-CLI (v0.23.0)** — every AI surface can route through headless
  `claude -p` on the machine's subscription instead of API credits. The
  $0 premise is one line: `ANTHROPIC_API_KEY` must be stripped from the
  child environment, or the CLI bills per token.
- **MEAL-9 (v0.26.0)** — weekend component prep planner. The AI proposes
  what to cook; every gram, calorie and macro is computed server-side.
  `PREP_PLAN_TOOL` has no nutrition field at all, and a test asserts it.
- **v0.26.1** — a weight goal stored in **pounds** was read as kilograms,
  so the planner concluded the user wanted to GAIN 86 kg and returned a
  surplus target next to a weight-loss goal. Three duplicate `/ 2.20462`
  conversions in `api/ai.py` now share `targets.goal_target_kg`.
- **v0.26.2** — `models.FoodLogEntry.eaten_on` (the column is `day`)
  reached production as a bare 500. `tests/test_model_attribute_references.py`
  now AST-walks every source file and asserts each `models.X.attr`
  resolves; SQLAlchemy resolves those at access time, so nothing else
  catches it.
- **v0.26.3 / v0.26.6** — two arithmetic repairs applied AFTER the model
  answers, because the prompt rules were not enough twice over: portion
  reconciliation (it cooked 6 portions and assigned 11.5) and energy
  scaling (plans landed at 40-71% of budget). Sauce is excluded from
  scaling — per-meal fat is a medical constraint here.
- **v0.26.5 / v0.26.9** — food-search ranking. A row that is WRONG rather
  than MISSING is the one failure the meals code's null-handling cannot
  catch, because it returns confident nutrition with no error anywhere.
  "sweet potato" resolved to the leaves, "tuna" to oil-packed, "salmon"
  to wild Atlantic at half the fat of farmed, "steak" to "lean only".
- **v0.26.8** — `MAX_LOOKBACK_DAYS = 14` clamped the Settings backfill
  buttons, so "30 days", "1 year" and "All (10y)" all read a fortnight
  and records older than that were permanently unreachable. Reads are now
  sliced, because `HealthConnectGateway.read()` truncates silently at 100
  pages. Also: `/meals/prep/targets` now reports `weight_age_days` and
  `weight_stale`.

---

## Resolved — v0.7.347 (2026-08-01)

- **JOURNAL-401** — the journal router (`api/annotations.py`) and its
  legacy `/log` shim gated on `require_query`, so the phone's Journal
  quick-log (ingest token only) 401'd while the dashboard worked. Both
  routers now use `require_any`. Backend-only.
- **RECOVERY-STALE-CLEANUP** — the `recovery_stale` flag, dead since the
  banner was removed in v0.7.268, is gone from `WorkoutOut`,
  `_workout_recovery_stale`, its `_hydrate_workout` call site,
  `frontend/src/api/types.ts`, `StrengthToday.vue`, `sync/Models.kt`, and
  `StrengthTodayScreen.kt`. Pure dead-code removal, no behaviour change.

---

## Resolved — Strava sync session (v0.7.319 → v0.7.321, 2026-07-22)

- **STRAVA-SILENT-401** — a dead cookie session was reporting a clean
  0-ride sync (`error:null`, green status) for ~6 weeks. Now raises
  `strava_web.CookieExpired`, persists `last_error`, and
  `StravaCookieStatus.needs_reconnect` drives a reconnect banner on
  web + phone Activities. (v0.7.319)
- **STRAVA-COOKIE-BLOB** — Settings accepts a pasted cookie-export blob
  (Cookie-Editor JSON / header string / Netscape); `parse_cookie_blob`
  extracts the tokens server-side. (v0.7.320 code, shipped in v0.7.321)
- **STRAVA-DECLUTTER** — Settings → Strava redesigned: cookie JSON paste
  box is the primary visible element; email+password auto-login,
  DevTools fields, paywall text, and legacy OAuth demoted to collapsed
  sections. Designed + adversarially verified via workflow. (v0.7.321)
- **Root-cause of "deploys keep reverting"**: CT auto-update cron only
  pulls CI-built GHCR `:latest`, which CI rebuilds solely on a `v*` tag.
  Documented in memory `myvitals-deploy-requires-tag`.

---

## Durable design docs

- FAST-COACH: `docs/FAST_COACH_PLAN.md`
- FITBIT migration: local Claude memory `project_fitbit_google_health_migration.md`
- Neon / Neon Refined redesign: local Claude memory `myvitals-neon-redesign-status.md`
- CT 104 dynamic host: local Claude memory `myvitals-ct104-host-dynamic.md`
- Strava cookie sync (why it breaks + all durable options): local Claude memory `myvitals-strava-cookie-sync`
- Deploy requires a v* tag (auto-update cron gotcha): local Claude memory `myvitals-deploy-requires-tag`
