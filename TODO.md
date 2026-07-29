# myvitals — Pending Work

Snapshot by session-close on **2026-07-28** after shipping **v0.7.342**
(previous snapshot v0.7.321, 2026-07-22). This session shipped the entire
13-task **#ENHANCE** strength backlog (v0.7.322→342) — all deployed +
verified. One low-severity follow-up (`PROG-STATE-1`) is deferred pending
a product decision; see Active below.

Numeric task IDs are session-scoped. Use **mnemonics** (e.g. `FITBIT-2`)
as the durable identifier. At the start of a new session, ask Claude to
"rehydrate the task tracker from TODO.md + memory" and it'll re-verify
each item against the code and re-instantiate via TaskCreate.

---

## Active — actionable now

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

### JOURNAL-401 — phone Journal quick-log returns HTTP 401 (bug)
Source: neon-QA memory. The journal router gates on `require_query`
(`api/annotations.py:13` + legacy `/log` shim `:20`), but the phone
authenticates with the ingest bearer token — the recurring
`require_any` vs `require_query` gotcha. Fix: switch both routers to
`require_any`, update the import on `:8`. Backend-only. Verify with a
phone quick-log against the deployed CT.

### RECOVERY-STALE-CLEANUP — delete the dead `recovery_stale` flag
Source: TODO.md. The banner was removed in v0.7.268 but the backend
still computes/ships the flag and both clients declare it as inert
deserialize-and-discard fields. Remove from
`api/workout/strength.py` (WorkoutOut field :589, `_workout_recovery_stale`
:672-695, call site :744), `frontend/src/api/types.ts:241` +
`StrengthToday.vue:923-925`, and `android sync/Models.kt:235` +
`StrengthTodayScreen.kt:884-888`. Pure dead-code removal. Quick win.

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
  clickable source citations, smart cache invalidation, local-LLM
  (Ollama) provider, voice Q&A. Each follows the "Adding a new card"
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
