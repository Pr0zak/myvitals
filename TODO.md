# myvitals — Pending Work

Snapshot updated **2026-09-22** after shipping **v0.43.0**. The #SA
thirteen-lens internal audit ran this session: 51 items, 46 shipped, 1 declined
on measurement, 4 open. Released across v0.40.0 → v0.43.0, including exercise
routes (SA-P3) and the activity dedupe they broke. Prior snapshot **2026-08-23**
after **v0.26.9**; before that **2026-08-01** after **v0.7.347**.

**#SA status is generated, not hand-kept** — it lives in `docs/sa-findings.json`
and `python3 scripts/sa_report.py SA-L1 shipped` rewrites both the tables below
and the report's chips. Do not hand-edit either.

Numeric task IDs are session-scoped. Use **mnemonics** (e.g. `FITBIT-2`)
as the durable identifier. At the start of a new session, ask Claude to
"rehydrate the task tracker from TODO.md + memory" and it'll re-verify
each item against the code and re-instantiate via TaskCreate.

**Carried items below were not re-verified on 2026-08-23.** They are
reproduced as written on 2026-08-01; check each against the code before
acting on it.

---

## Active — actionable now

## #UI — UI refresh, all screens (2026-09-23)

Design page: `https://claude.ai/artifact/VwA1kyr1UcLAdHmuxxVBn2` (current vs option
mockups for every screen). Themes: one look everywhere, every screen gets a
hero, pictures over sentences. Shared kit landed first — phone `ui/neon/NeonKit.kt`
(NeonHeroCard, NeonRing, NeonEyebrow, NeonStatTile) + `NeonScreen(onBack=)`,
web `components/neon/` (NeonPage, NeonHero, NeonRing, NeonEyebrow, NeonStat).
Use these; do not re-draw rings per screen.

| ID | Task | Surface | Status |
|---|---|---|---|
| UI-0 | Shared kit + `--main-pt/--main-px` inset vars (fixes UX-W1 on 18 views) + Coach "bad" tone amber | both | done |
| UI-1 | Train tab: session hero, weekly volume chart (server field), muscle range bars, tile grid, failure state | both | done — unreleased |
| UI-2 | Active workout: "Now" hero with steppers + rest ring, segmented progress, chips for banners, collapsed done | both | done |
| UI-3 | You + Body: habits hero, goal rings by state_tone, recovery hero, two-tier metrics | both | done — unreleased |
| UI-4 | Detail screens (Steps/HR/Sleep/Weight): neon scaffold, hero chart, server stats block, token colours | both | done — unreleased |
| UI-5 | Activities + Activity detail + Trails: map-first, zone bands, status hero, rose→amber, units | both | done |
| UI-6 | Meals Today + Prep, Fasting, Sober: energy ring + per-meal fat, stage ring, calm reset, milestones server-side | both | done — unreleased |

Follow-ups the slices left, deliberately:
- **UI-F1** Web features removed with UI-4 because they were browser-computed with no server equivalent yet: HR delta vs previous window + avg HR by activity type (HeartRate.vue), weight distribution histogram + "days at min" (Weight.vue), steps 24h trace (Steps.vue, duplicated the hourly bars). Bring back only with a server field.
- **UI-F2** Web Activities lost its period stats banner, PR card and sort/grid/group-by-month (UI-5; the YTD hero replaces the banner, the phone never had the rest).
- **UI-F3** Train still computes YTD client-side (`computeYtdComparison`); switch it to `GET /activities/ytd` so Train and Activities cannot disagree.
- ~~**UI-F4**~~ done — `load_ladder_lb` on each workout slot (a window onto the micro-loader rounder's loads); phone + web weight steppers walk it, 2.5 lb only as the old-server fallback.
- **UI-F5** Fasting ring on You has no stage ticks yet; UI-6 now serves `stages` on fasting sessions, so wire them in.


## #UX — user-experience scan (2026-09-22)

Four read-only lenses over the code as it stands after v0.43.0: web
dashboard, Android app, backend, and web↔phone flows. Anything already in
`docs/sa-findings.json` or the #SA/#OG2/#OG3 sections was excluded. The three
highest-severity backend claims (UX-D1, UX-D2, UX-D5) were re-read in source
before this was written. Everything else is as the lens reported it — re-read
the cited line before building.

The recurring shape: **failure rendered as absence.** Almost every client
catches an error and falls through to its empty state, so "the request failed"
reads as "you have no goals" / "rest day" / "nothing is flashing red". That is
the same null-is-not-zero rule the backend already enforces, missing one layer
up.

### Batch 1 — wrong numbers and wrong days (done in the working tree 2026-09-22, not yet released)

UX-D8 measured before changing: over 30 days one source had ~800 minutes
holding more than one row, ~21k steps between SUM and per-minute MAX. The
rows are distinct readings seconds apart and `(time, source)` is the primary key, so SUM is right and MAX was dropping
real steps. Stored days in a two-week window ending early September read low; the SA-L1
staleness check will re-flag and rebuild them, `MAX_LAZY_RECOMPUTES` at a
time, on the next `/summary/range` loads.

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| UX-D1 | `_check_goals_for_completion` assumes weight goals go DOWN (`latest <= target`) — a weight-GAIN goal auto-closes as "reached" on the next `/ai/alerts` call, which runs every page load | S | backend | done — unreleased |
| UX-D2 | Fasting streak counts back from the UTC day over UTC `ended_at`, within a 90-day window — reads 0 until today's fast ends, evening fasts land on tomorrow, long streaks truncate | S | backend | done — unreleased |
| UX-D3 | `_current_values_for_goals` + the completion check resolve "today" in UTC — steps goal reads no-data 19:00-24:00 CDT; `ai.py` not in `DAY_FACING_MODULES` | S | backend | done — unreleased |
| UX-D4 | `/profile` steps schedule `effective_today` resolved in UTC — shows tomorrow's weekday target after 19:00 | S | backend | done — unreleased |
| UX-D5 | Web `meals/Today.vue` freezes `today` at mount — a tab left open overnight logs to yesterday | S | web | done — unreleased |
| UX-D6 | Weight "to go" has opposite signs: web `latest - goal`, phone `goal - latest` | S | both | done — unreleased |
| UX-D7 | `Trends.vue` keeps its own localStorage weight goal, a default 178 cm height, and a client-side ETA that never refuses — contradicts the server projection | S | web | done — unreleased |
| UX-D8 | `live_steps_today` is plain SUM; `canonical_steps_total` + `/query/steps` are per-minute MAX then SUM — home and Steps can disagree. Measure duplicate-minute rows first | S | backend | done — unreleased |
| UX-D9 | `/summary/today` `last_sync` lacks `real_install_heartbeat_filter()` — the SA-O2 debug-build heartbeat bug on a second path | S | backend | done — unreleased |
| UX-D10 | Steps detail (web + phone) uses flat `steps_goal`, ignores the per-weekday schedule; "days ≥ goal" denominators differ between clients | S | both | done — unreleased |
| UX-D11 | One shared `local_today()` helper (11 copies exist) and flip the day guard to cover all of `api/` + `analytics/` with named exemptions | M | backend | partial — `localtime.py` + guard widened to 8 modules and the two-line shape; the 11 private copies not yet folded in |
| UX-E1 | AI provider errors (`CliError`, `LlmError`, Anthropic) reach clients as bare 500; `friendly_error()` text exists and is never shown. Map to 503/429 with `detail`; web reads `detail` not `e.message` | S | both | done — unreleased |

### Batch 2 — failure is not absence

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| UX-F1 | Phone Train tab renders "Rest Day" on any fetch failure; no error, no refresh, no cache | M | phone | todo |
| UX-F2 | Web You/Train/CoachHub/Rings/Body never render `loading`, and `.catch(() => null)` turns errors into empty states ("No active goals yet", "Nothing is flashing red") | M | web | todo |
| UX-F3 | Phone Home (`RingsScreen`) and You have no JsonCache SWR — "Loading…" every tab switch; You says "No active goals yet" offline | M | phone | todo |
| UX-F4 | `today_snapshot` `safe()` nulls a failed section silently — add `failed: [...]` and render it | S | both | todo |
| UX-F5 | 110 raw `e.message` renders on phone — one error→copy mapper | S-M | phone | todo |
| UX-F6 | CoachHub: fallback tone "balanced"/"Nothing is flashing red" on no data; synthetic sparklines; disabled Ask input though ASK-1 works; hero mislinks to /heart-rate | S | web | todo |

### Batch 3 — phone behaviour

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| UX-P1 | `onNewIntent` only calls `setIntent` — notification/widget/shortcut taps do nothing when the app is already running | S | phone | todo |
| UX-P2 | Rest-done alert is driven from composition — likely silent with the screen off (inferred; verify on device). Schedule via AlarmManager or a chronometer notification | M | phone | todo |
| UX-P3 | Zero `rememberSaveable` in the app — rotation/dark-mode switch wipes rest timer, half-filled food-log dialog, range pickers | M | phone | todo |
| UX-P4 | Food log: double-tap Save duplicates; errors cleared by the following `fetch()`; dialog closes before the request resolves; "repeat yesterday" reports every failure as "nothing logged" | S | phone | todo |
| UX-P5 | Hard-coded unit labels beside converted values (`WeightDetailScreen:228` "lb", `ActivityYtd:143` "mi", `PrepTab:342` "kg a week"); weekly-volume card summed on device | S | phone | todo |
| UX-P6 | Steps widget falls back to `0` not "—"; widgets `runBlocking` up to 4 s in `onUpdate` | S | phone | todo |
| UX-P7 | Six 15-min periodic workers; TrailAlert/AiAlert redundant with SyncWorker's post-sync trigger; widget refresh scheduled with no widgets placed | M | phone | todo |
| UX-P8 | "Sync now" is not unique work — can overlap the periodic sync on the checkpoint write | S | phone | todo |
| UX-P9 | HC permissions-lost banner is Settings-only on phone; web shows it on every page | S | phone | todo |
| UX-P10 | Catalog favourite/avoid/disable icons: no contentDescription, no toggle state, 36 dp | S | phone | todo |
| UX-P11 | Widgets all route to Body tab; in-app `open()` lacks `launchSingleTop` | S | phone | todo |

### Batch 4 — web layout and reachability

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| UX-W1 | Neon views use `margin: -1.25rem -1.5rem` against 0.9rem mobile padding — ~10 px horizontal scroll on 11 views | S | web | todo |
| UX-W2 | `StrengthToday.vue` set table ~600 px wide on a 360 px phone, no mobile rule | M | web | done (UI-2: SET/LB/REPS/✓ CSS grid, fits 360 px, no horizontal scroll) |
| UX-W3 | Neon shell cannot reach /meals/nutrition, /meals/foods, /meals/log, /day, /watch, /logs; hiding a Body tile orphans its detail view | S | web | todo |
| UX-W4 | One-tap permanent delete with no undo (recipes, shopping, pantry, foods, log) on ~20 px icons; `.icon-btn` redefined in 6 files | M | web | todo |
| UX-W5 | Train Strength/Cardio toggle is inert; YTD distance hard-coded mi; upcoming cells all open today | S | web | todo |
| UX-W6 | Modals: no Escape, no role=dialog, no focus trap, background scrolls — one shared `Modal.vue` | M | web | todo |
| UX-W7 | NeonNav `activeIndex` falls back to Today; no back affordance in `PageHeader` | S | web | todo |
| UX-W8 | Unsaved equipment/profile edits dropped silently on navigation | S | web | todo |
| UX-W9 | Settings mounts every pane — 11 loads + 3 s `/jobs` poll when deep-linked to profile | S | web | todo |
| UX-W10 | Meals Today: unlabeled "+" button, bare kcal numbers, manual inputs coerce "1,5" / "300kcal" to null silently | S | web | todo |

### Batch 5 — performance and features

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| UX-X1 | Web has no cache between route changes; Train pulls 2,000 activities per visit; readinessDetail fetched twice on home | M | web | todo |
| UX-X2 | Activity list/stats endpoints load full `polyline` + `raw`; serve `polyline_simple` in lists, aggregate stats in SQL | S | backend | partial — lists: `?polyline=full / simple / none`, `raw` deferred (UI-5); stats-in-SQL still todo |
| UX-X3 | `/ai/alerts` cooldown keys on newest alert — a scan that writes nothing re-scans every page load, and `phrase_anomaly` runs un-quota'd inside a GET | S-M | backend | todo |
| UX-X4 | Strength review bumps quota BEFORE the cache lookup (and possibly twice); no `/latest` read | S | both | todo |
| UX-X5 | `discoveries` runs 19 per-metric queries though `all_daily_summary_metrics` exists; `tiles.py` ~12 over the same 14 rows | S | backend | todo |
| UX-X6 | Food log entries cannot be edited on either surface — add `PATCH /meals/log/{id}` | S-M | both | todo |
| UX-X7 | Food log + shopping ticks have no offline path on phone (strength flow does) | M | phone | todo |
| UX-X8 | Label/barcode scan cannot log directly; prep → shopping list is a dead end | M | both | todo |
| UX-X9 | Phone cannot create/edit/delete goals or show goal ETA | M | phone | todo |
| UX-X10 | Detail-screen stats (HR/HRV/BP/skin-temp averages, weekday patterns) computed per client and disagree — one `/query/<metric>/stats` each | M | both | todo |
| UX-X11 | Web-only actions with no phone path: alert dismiss, manual BP entry, compare, activity notes — decide which are intentional and list them in `parity_check.py` | M | phone | todo |

---


## #SA — thirteen-lens internal audit (2026-09-18)

The first pass that is **not** a teardown of someone else's project. Thirteen
independent lenses were pointed at this codebase and at the live production
database: dormant surfaces, unsurfaced data, truth, parity, reliability,
performance, the AI layer, security, the test gates, the Android app,
operations, statistical headroom, and a scan of comparable projects that are
not openGym. Each lens measured before it claimed; each finding was then handed
to a refuter told to kill it. **52 findings, 42 survived, 10 refuted.** The
refuter also corrected 39 of the survivors — a scale overstated, an impact
claimed on a screen that does not exist, a proposal that would have broken one
of this project's own invariants. Those corrections are in the report and
several of them change what the fix should be, so read the item before building
it.

**The headline.** The judgement in this codebase is sound and it is applied
where a human remembered to apply it. 1,936 tests pass in 34 seconds, including
every hand-written AST guard, and **nothing runs them** — no CI job, no release
step. The tag that publishes `:latest` is pulled into production within fifteen
minutes by a cron that health-probes the container and rolls back if it fails
to boot, and is blind by construction to a red test or a lint error. Five of
the six live untruths below would have been caught by something this project
already owns. That is why `SA-G1` is not a chore item: it is the reason the
rest of this list exists.

Report artifact: `https://claude.ai/code/artifact/826f3170-a4b4-4f27-bad6-1c50e38c515e`
Repo copy: `docs/self-audit-2026-09.html`, generated — not hand-written. Prior
passes asked you to keep the chips in step with the table by hand, and the
parity map in `SA-G2` is what that habit produces, so this one is wired instead:
the tables below and the report's chips are both emitted from
`docs/sa-findings.json`. Republish by passing the existing URL so the link the
user holds keeps working.

<!-- SA-TABLES:BEGIN -->

### Live — the app states something false right now

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-L1 | `daily_summary.steps_total` freezes at a partial count; nothing recomputes it. 32 of the last 100 days wrong, stored history 23% short. Every surface but the Steps detail screen reads the frozen column | M | backend | shipped ✅ |
| SA-L2 | `You.vue` re-maps `/ai/goals` and drops every GOAL-STATE field, so **every** goal card renders "No reading yet" — the v0.32.0 bug re-created one layer up | S | web | shipped ✅ |
| SA-L3 | `daily_training_stress` early-returns on a day with no Strava activity, so a lifting day carries zero load. CTL/ATL/TSB pinned at 0.0; Compare reports "Fitness −100%, worse" | S | backend | shipped ✅ |
| SA-L4 | All five phone Coach POSTs declare `@Body Map<String, Any>` → Java wildcard → Retrofit rejects the method. Three of six Coach cards have never once run | S | phone | shipped ✅ |
| SA-L5 | Two F821 NameErrors in shipped code. `add_exercise` raises *after* commit, so each retry writes another phantom slot | S | backend | shipped ✅ |
| SA-L6 | `last_sync` on `/summary/today` is `max(heartrate.time)`, not a sync. Amber-and-false 22% of wall-clock time, pointing at the wrong fault | S | both | shipped ✅ |

### Exposure — the token model has a door cut around it

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-S1 | Postgres `ports:` published on every interface, no consumer, no firewall — the LAN and the tailnet reach the health DB and eight plaintext third-party credentials, bypassing the token model | S | ops | shipped ✅ |
| SA-S2 | `_check_and_bump_quota` still gates on `anthropic_api_key`; 21 AI endpoints break if the unused key is cleared | S | backend | shipped ✅ |
| SA-S3 | More call sites still use the guard `_credentials_missing(cfg)` was written to replace | S | backend | shipped ✅ |
| SA-S4 | Neither image builds from a lockfile, and the CT force-recreates from `:latest` every 15 min | S | ops | shipped ✅ |

### The gates — what is meant to catch this class, and does not run

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-G1 | **No CI runs the tests, ruff, or the Android test.** 1,936 tests pass in 34 s; nothing executes them. `images.yml` should `needs: [tests]` — that is what closes the loop with the auto-update cron | S | ops | shipped ✅ |
| SA-G2 | The parity pair map stopped being updated — six live web↔phone counterparts unregistered | S | ops | shipped ✅ |
| SA-G3 | `parity_check.py` passes a pair when both files moved in the range — so a fix applied to one surface and not the other reads green. HeartRate.vue ↔ HrDetailScreen.kt matched clean on a commit where the phone chart still lacked the fix | M | ops | shipped ✅ |

### The numbers behind the numbers

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-N1 | The nightly RHR/HRV window is 22:00–09:00 **UTC** = 17:00–04:00 local. Adds variance, misses the last two hours of sleep. The AST day-boundary guard cannot see a clock-hour window | M | backend | shipped ✅ |
| SA-N2 | `/summary/range` re-derives the same ~77 days on every call and never converges (~1.6–2.0 s for 30 days). No wrong number — pure wasted latency | S | backend | shipped ✅ |
| SA-N3 | "Sleep quality" is the duration score wearing a quality label; the architecture term is pinned at 100 | M | both | shipped ✅ |
| SA-N4 | The recovery verdict is one night of HRV against a 7-day mean, and reverses itself on 57% of consecutive days | S | both | shipped ✅ |
| SA-N5 | The projection's refuse-when-noisy gate is measured on the smoothed series, so it cannot fire | S | backend | shipped ✅ |
| SA-N6 | The skin-temp carry-forward does not declare itself; the side nav shows a 5-day-old value as current | S | backend | shipped ✅ |
| SA-N7 | `backfill_analytics` computes `today = datetime.now(timezone.utc).date()` — the local-day bug class, in a module `DAY_FACING_MODULES` does not cover | S | backend | shipped ✅ |
| SA-N8 | `readiness` weights hrv 0.40 / rhr 0.30 / sleep_score 0.15 / sleep_duration 0.15 — but `sleep_score` is itself ~60% duration, so sleep enters twice and the two terms correlate at r=0.573 (measured) | M | backend | declined ✖ |

### Reachability — built, shipped, and with no door

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-R1 | Two Key-metrics cards navigate somewhere other than themselves; its Edit link opens the wrong Settings pane | S | web | shipped ✅ |
| SA-R2 | Web Today omits the weekly training-load card the phone Today shows, and fetches four endpoints it does not render | S | web | shipped ✅ |
| SA-R3 | Nine registered parity pairs have a web half with no route into it on the default (neon) shell | S | web | shipped ✅ |
| SA-R4 | Meals is 3-of-11 reachable on the default web shell; the pill's own subtitle promises two views you cannot open | S | web | shipped ✅ |

### Operations — what happens when nobody is watching

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-O1 | Settings' "Preview payload" can render 1 of 15 builders — and 14 of 24 real AI results came from the ones it cannot show | M | web | shipped ✅ |
| SA-O2 | A second install poisons `sync_heartbeat`, the only sync-health signal the web reads (222 ghost rows) | S | both | shipped ✅ |
| SA-O3 | The pre-migration restore point survives a median of 10 h; the bugs it exists for take days to notice | S | ops | shipped ✅ |
| SA-O4 | Nothing outside the app watches the app; `/health` is a literal constant | S | ops | shipped ✅ |
| SA-O5 | The weekly docker prune has never run once — not executable; cron has been mailing the error | S | ops | shipped ✅ |
| SA-O6 | Nothing the backend logs reaches a surface — 265k `app_logs` rows, zero from the server | S | backend | shipped ✅ |

### Phone telemetry — permissioned, counted as granted, never read

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-P1 | `DistanceRecord` is in the manifest and in `HealthConnectGateway`'s permission list but is never read; `WorkoutSample` has no distance field on either side of the wire, so all 18 Health Connect activities have `distance_m` NULL | S | both | shipped ✅ |
| SA-P2 | `READ_EXERCISE_ROUTE` is absent from the manifest and `ExerciseRoute` appears nowhere in the app, so `activities.polyline` is NULL for every Health Connect activity and the Route card is hidden | M | both | shipped ✅ |
| SA-P3 | Health Connect holds a route for the walk and withholds it pending `READ_EXERCISE_ROUTE`; declare the permission, request it through the route consent flow, and carry a polyline on the wire so phone-ingested activities can draw a map | M | both | shipped ✅ |
| SA-P4 | `sync_heartbeat` recorded 30 consecutive failures across nine hours while reporting 13/13 permissions granted, and nothing on either client said so — the dashboard's only ingest signal is the permission banner | M | both | todo |
| SA-P5 | The self-duplicate path retires a promoted row without a winner to carry to, so `CARRYABLE_COLUMNS` never runs — only the older two-column user-owned veto protects it | S | backend | todo |
| SA-P6 | `track_is_materially_better` short-circuits `if not incumbent: return True`, so a corrupt or truncated polyline is carried onto the survivor unvalidated | S | backend | todo |

### Dead weight — things to delete rather than build

| ID | Task | Size | Surface | Status |
|---|---|---|---|---|
| SA-C1 | Release APK 62.4 MB with R8 disabled; one dependency shipped whole for 104 icons is most of it | M | phone | shipped ✅ |
| SA-C2 | 996 MB of Chromium in every backend image, for a Strava login this account cannot use | S | ops | shipped ✅ |
| SA-C3 | The phone log table's prune query has zero callers — ~68 MB of text | S | phone | shipped ✅ |
| SA-C4 | 463k trail snapshots feed an endpoint no view calls and a client method with no callers | M | both | shipped ✅ |
| SA-C5 | `trail_status_snapshots` is 99.62% exact duplicates — 76 MB storing 1,746 facts | S | data | shipped ✅ |
| SA-C6 | ~4,600 statistical alerts, incl. 14 stage-2 BP alerts, written where no client reads them | S | backend | todo |
| SA-C7 | Three of the four AI rows on the workout page are dead, on a page used daily | S | both | shipped ✅ |
| SA-C8 | The body-circumference screen has no door on either surface | S | both | shipped ✅ |
| SA-C9 | The Fasting ring holds half the Habits row and has rendered an em-dash since it shipped | S | both | shipped ✅ |
| SA-C10 | The AI model picker states the wrong cost, and switching model cannot change a cached card | S | web | shipped ✅ |
| SA-C11 | The unbounded `MAX()` pattern costs 530 ms of planning against 17 ms of execution | S | backend | shipped ✅ |
| SA-C12 | No `frontend/.dockerignore` — a developer's local `node_modules` (227 MB when measured) is sent to the daemon and copied over the image's own installed tree by `COPY . .` | S | ops | shipped ✅ |
| SA-C13 | SA-O6's allowlist was audited line by line for physiological values; the `uvicorn.error` catch-all beside it was not, and an exception *message* (Pydantic `ValidationError`, SQLAlchemy `IntegrityError`) can quote a health value into `app_logs` | S | backend | shipped ✅ |
| SA-C14 | `loadUpdateStatus`, `checkUpdate` and the new `aiPreview` all call `axios.get("/api/...", { baseURL: apiBase.value || undefined })` — with a custom API base set, the wire URL becomes `<base>/api/...` and 404s, because hitting the backend directly bypasses the Caddy prefix strip | S | web | shipped ✅ |

<!-- SA-TABLES:END -->

**Status lives in `docs/sa-findings.json`.** The tables above and the chips in
`docs/self-audit-2026-09.html` are both generated from it by
`python3 scripts/sa_report.py SA-L1 shipped` — do not hand-edit either, and
republish the report to the URL above so the reader's link keeps working.

### Refused on measurement — do not re-open from intuition

Ten findings did not survive the refuter, and three of them are worth knowing
about specifically because they read well until the query was re-run.

- **"The watch feed has been dead 58 h."** It had self-healed before the
  refuter reached it. The gap was 43.3 h, not 58, it is the 120-day maximum,
  and `device_status` shows heart rate resuming in the same minute the watch
  went back on the wrist. There are zero worn-but-silent hours. A proposed 24 h
  staleness alarm would have fired three times in four months on a healthy
  watch — HEALTH-1's failure exactly.
- **"10,955 SpO2 readings have no read endpoint."** The arithmetic is right and
  it is already TODO's `SPO2` item, which asks for exactly the read endpoint
  proposed. But ingest **stopped on 2026-09-07**: SpO2's only writer is the
  Google Health poll, which is the dead `invalid_grant` grant of `OG3-L1`. A
  chart built now plots a closed 40-day window. Fix the grant first.
- **"The HA environment poll is registered in a paused state."** The job is not
  registered at all — `settings.ha_url` / `ha_token` / `ha_entity_list` are
  empty on the deployed CT, and the backend logs six scheduled jobs at boot
  with no HA line among them. `env_readings` being empty is a configuration
  choice, not a fault.

The other seven: the deterministic alert tier (structurally true, every number
attached to it wrong, and `ts` is write-time not event-time so the "readable
volume" claim inverts); three unread `google_health_daily` columns (nothing in
the app claims to collect them, so there is no untrue statement to correct, and
the VO2 half already shipped); the Coach page being unreachable (`Analytics.vue`
is a four-tab shell that mounts it, linked unconditionally from seven detail
views); phone `records_pulled` (nobody reads it, and the fault it would diagnose
did not exist); the CT's stale `docker-compose.yml` (byte-diff is two env vars
whose compose defaults are identical to the code defaults — a provable no-op);
the steps trend badge weekday artefact (no client renders a trend badge at all);
and zone-time outside logged activities (the zones endpoint has never been wired
to a screen on either surface).


---

## #OG3 — openGym third-pass teardown (2026-09-16)

Third reading of `DuarteSantos8/openGym`, run because #ENHANCE saw it to
~v1.2.5 and #OG2 to ~v1.2.11; HEAD is the v1.3.x line. Four lenses, each
verifying its own findings against this source and the production database,
then one adversarial refuter. 49 findings, 31 survived the check, roughly a
third of those survived the refuter. The refusals are recorded in the report
and are measured against this user's own data — do not re-open them from
intuition.

The AGPL rule from both prior passes still binds: **openGym is AGPL-3.0 and
myvitals is not. Reimplement behaviour from the described design; never copy
source.**

Report artifact: `https://claude.ai/code/artifact/b9820117-3615-426e-9f56-d111f9a87803`
Repo copy: `docs/opengym-third-pass.html` — **keep its status chips in step
with this table.** Republish by passing the existing URL so the link the user
holds keeps working.

### Live — the app is wrong right now

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-L1 | Google Health grant dead since 2026-09-08 (`invalid_grant`), retried every 15 min, surfaced nowhere. **Recovery is on Google's side**: publish the OAuth client to *In production*, then Settings → Google → Reconnect | — | user action |
| OG3-L2 | `main.py:191` gates the weekly AI digest on `not cfg.anthropic_api_key` — a guard `_credentials_missing(cfg)` replaced, so the digest silently no-ops under `provider="claude_cli"` | S | backend |

### Batch A — the session surfaces stop lying (one tag, pure render)

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-A1 | Today's session card reads `split_focus` only; `status` is in the same payload and neither client reads it, so 45 completed + 86 skipped workouts all present as outstanding | S | both |
| OG3-A2 | Web rest day is a dead end; the phone already names the next session from `/upcoming` | S | web |
| OG3-A3 | `LastSetOut` carries no date and no rating, though both are already in the join — and 106 of 159 re-training gaps exceed 14 days | S | both |
| OG3-A4 | `tiles.py` never passes `target` for weight, so `MetricCard.vue`'s dashed goal line is always null | S | both |
| OG3-A5 | `Train.vue` invents `heroMinutes` as `exercises × 7` and renders an unbound `RPE —`; the phone prints "6 exercises" for the same session | S | web |

### Batch B — backend only, no parity cost

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-B1 | Two MCP tools: `preview_today_workout` and `get_exercise_records`. All eight existing tools are retrospective | S | backend |
| OG3-B2 | Count exercises this equipment can actually reach per muscle — 5 of 14 audited muscles have a pool smaller than their own MEV | S | both |
| OG3-B3 | Say "per side" on unilateral lifts. **Phase 1 only** — flag the rows, do NOT double `target_sets` | S | both |

### Batch C — the model is untrusted input

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-C1 | `strength_nudge` renders and caches unvalidated `block.input`; filter against `selectable_ids` and attach real names | M | both |
| OG3-C2 | Declines never reach the server, so "Get fresh suggestions" is guaranteed to return the swaps just dismissed | M | both |

### Batch D — integrations that fail loudly

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-D1 | Classify integration failures (`transient`/`auth`/`config`/`upstream`); stop retrying `auth`, surface it as a reconnect action | M | backend |

### Batch E — the prescription says what it means

| ID | Task | Size | Surface |
|---|---|---|---|
| OG3-E1 | Deload on the weight × reps grid. With `wrist_weights_lb = []` the light/moderate deload is a structural no-op at every rung 5-50 lb | M | backend |

### Menu — survived, below the line

`OG3-M1` reserve the floating bar height once at the shell (S) ·
`OG3-M2` `backdrop-filter` fallback, zero `@supports` in the frontend (S) ·
`OG3-M3` seeded invariant probe for `round_weight`/`deload_round` (S) ·
`OG3-M4` emoji doing icon work in `Train.vue`, duplicating `ActivityIcon` (M) ·
`OG3-M5` `ConfirmDialog.vue` for the four highest-stakes confirms (M) ·
`OG3-M6` neon type scale — 31 of 42 web weights at 700+ (L) ·
`OG3-M7` BodyMap tap-through to the filtered catalog (L) ·
`OG3-M8` unilateral phase 2 — a volume-semantics decision, deferred ·
`OG3-M9` reminder hour ceiling + APK size floor (S)


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
| ~~OG2-C1~~ | ~~Per-muscle fatigue~~ — **REFUSED on measurement, 2026-09-02.** See below | — | — |
| OG2-C2 | The muscle silhouette shown at planning time, not only in review | M | both |
| OG2-C3 | The progression chart picks its metric, unit and caption from what was logged | M | both |
| OG2-C4 | Every rated average shows its denominator; e1RM names its source set | M | both |

### OG2-C1 — per-muscle fatigue, refused on measurement (2026-09-02)

Set out to build openGym's model: intensity-weighted tonnage accumulated with
a 36-hour half-life, saturating readout, crossed with myvitals' systemic
recovery. **Not built.** Every constant it needs was measured against this
user's own data and none could be sourced. The refusal is the result, not an
omission, and these numbers are the record so the question does not get
re-opened from intuition.

- **The decay constant cannot be derived.** Across 286 muscle-to-muscle
  re-training intervals, ZERO arrive above 50% residual at a 36-hour
  half-life; the maximum reachable is 0.397 because the shortest gap on any
  muscle is 2 days. Every muscle would read "ready" at essentially every
  decision point. That is HEALTH-1's failure with the sign flipped — a signal
  that never fires is ignored exactly as fast as one that always does.
- **Nor fitted from performance.** Of 88 exercises with any weighted set, 49
  have been performed in exactly ONE session and only 5 in four or more.
  There is no repeated-measures data to fit a curve to.
- **The thing the model carries is not there.** Session size barely varies —
  set-count CV 0.05 back, 0.16 chest, 0.19 quadriceps — because the generator
  writes a fixed slot template. And 162 of 165 weighted slots carry a single
  distinct weight, so the `(load/1RM)^1.5` intensity term collapses to a
  constant.
- **Two of fourteen muscles have no measurable load at all**: abdominals is
  97% unweighted (2 weighted sets across 23 sessions), lower back 100%.
- **The systemic cross has no signal.** Session size against next-day change
  in `recovery_score`: r = -0.082 for set count, +0.015 for tonnage (n=20),
  against a day-to-day median absolute change of 15.9 points.

WHAT WOULD HAVE TO CHANGE for this to be worth revisiting: training frequency
high enough that per-muscle gaps fall to 2-3 days, enough repeat sessions per
exercise to fit a decay curve, and genuine variation in session size. None of
those are true today and none can be manufactured.

**OPEN QUESTION found on the way.** `strength_workouts.deload_factor` is below
1.0 on ZERO of 40 completed workouts, including four whose
`recovery_score_used` was 24.3 / 30.0 / 35.3 / 38.3 — all of which
`RecoveryInputs.deload_factor()` maps to 0.85. Recovery-aware planning IS
enabled (`user_profile.strength_recovery_aware = true`). Two explanations fit
and I could not separate them from stored state: the user routinely taps
"use full weight" (which correctly stores 1.0), or the factor is not being
persisted on completed workouts. Worth an hour with the generation path.

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

#### Phase D outcome — shipped in v0.37.0

The sixteen were re-verified against the code before any of them was built,
because phases A-C had shipped since the list was written and several items
described code that had changed underneath them. Five survived. Four of the
five close a divergence rather than adding a capability, and two of the five
were not on the list at all — they were found while measuring the items that
were.

SHIPPED. D3 and D5 (effort on the progression dot, and the first pointer
gesture on any chart in the app). D6 in part — the tappable cells and the
current year stopping at today; its headline is in the refused list below.
D7 in part — the shared palette, which turned out to be a live cross-surface
contradiction rather than the tidy-up the entry described. D1, reshaped: the
ladder runs on the RATING, not on reps, because both loggers prefill the rep
field from the previous session and the number read back is the app's own
suggestion.

Also shipped, not from the list: the three drifted readers found by the B1
review, and the #WP-8 cadence advisory, which was gated off for exactly the
user it describes.

ALREADY DONE: D4 (v0.33.0). MOOT: D15 — the component holding that button was
unmounted on 2026-08-10 and weight has arrived automatically since 2026-08-23
via the Garmin Index path.

NOT BUILT, each against a decision this project had already recorded and that
still holds:
- `D8` warm-up ramp. The deferral comment at `api/workout/strength.py` says
  prescribing warm-ups would change what `sets_total` means and force the
  SKIP-1 counters to learn to exclude them. Since that was written SKIP-1 made
  those counters the single client-rendered definition, so the blast radius
  grew. And the benefit needs loads this user does not lift: the heaviest set
  ever logged is 30 lb, the mean of 547 weighted sets is 15.7, and there are
  zero sets at or above 40. At that ceiling the first working set IS the
  warm-up. Revisit if a barbell appears.
- `D10` sparse date → day-type override. Refuted by measurement: deviation is
  the majority case here, not a sparse exception, so an override sheet would
  ask for four to seven taps a week forever while leaving the setting that
  generates the phantom days untouched. The measurement is what surfaced the
  cadence advisory instead, which addresses the same complaint at its source.
- `D12` snapshot muscle attribution at log time. It would have PREVENTED the
  one catalog change this project has actually made — `_CATALOG_OVERRIDES`
  moves both pullovers from chest to lats, with the stated intent that sets
  already logged must pick up the correction.
- `D13` retained strength. Its consumer was already rejected, and the signal
  never fires: across 242 re-training intervals the median gap is 6 days and
  only 12 of 242 clear a 14-day plateau.
- `D6`'s headline, shading the strip by minutes. Reverts v0.7.361, which
  replaced exactly that ramp with the per-category calendar and recorded why.
  The 2026 mix is 48 ebike rides to 13 walks, so category is load-bearing.
- `D16` light theme on the phone. 1,084 direct `NeonMV.` reads across 52
  files, 474 `MV.` across 27, and 315 raw colour literals, against two
  recorded decisions — including v0.7.393 retiring the Classic/Neon choice on
  the grounds that there is one app theme.

DEFERRED, still real:
- `D11` program state replayed from the log. Blocked on the product decision
  TODO.md already defers under PROG-STATE-1, and PROG-1 is `enabled: false`.
- `D9` mid-session pair/unpair/reorder. Zero demand signal: `added_ad_hoc` is
  false on all 1,450 slots, so the existing mid-session structural edit has
  never been used once.
- `D14` curated import alias table. No imported rows exist, and there is no
  import surface on the phone.
- `D2` session notes. The existing free-text surface holds 3 rows in four
  months with nothing in the note column, against 780 rated sets in the same
  period.

CORRECTION to the v0.37.0 commit message for the bodyweight ladder. It says
the frozen target covered "74 of 292 slots in completed workouts", a figure
carried over from the triage. The real reach is smaller and the difference is
structural, not a counting slip. Of 152 null-weight slots in completed
workouts, 76 are mobility cool-down poses, which already had their own ladder
via `adjust_mobility_target`; 42 are WP-17 finisher slots, which hard-code a
fixed 12-15 light-pump range with no weight on purpose and are deliberately
not laddered; and **34 are main strength slots, which is what the ladder
actually reaches.** The defect and the fix are unchanged — a main bodyweight
slot genuinely could not progress — but the headline number was roughly
double the truth, and the two excluded groups are excluded for good reasons
rather than by oversight.

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
**DONE in UI-2** — web now has the Now hero (steppers, one-tap Log set), the
rest ring inside the hero, NOW-row highlight and one segmented progress bar,
all on the same `logSet` path.
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
