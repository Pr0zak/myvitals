# myvitals — TODO

Tracking deferred work. Move items to commit messages as they ship.

## AI integration — batch 3 (deferred)

### Phone-side alert notifications

Backend already produces structured alerts (`/ai/alerts`); since
v0.7.128 these are generated lazily on read (when the most recent
alert is >6h old) instead of by a fixed-cadence cron. The companion
app needs to surface them.

- [ ] Add `aiAlerts()` + `markAlertsNotified()` to `BackendClient.kt`
- [ ] Inside `SyncWorker.doWork()`, after a successful sync, fetch
      `GET /ai/alerts?unacked_only=true`. For any row whose
      `phone_notified_at` is null, post a `Notifier.postAiAlert(...)`
      and `POST /ai/alerts/mark-notified` with the IDs to suppress
      duplicates.
- [ ] Extend `Notifier` with a second channel `alerts` (severity-based
      icons, distinct from the `updates` channel).
- [ ] Tapping the notification deep-links into the dashboard via
      `https://<backend>/?alert=<id>` — frontend route handler scrolls
      to the relevant card.
- [ ] Optional: a small "AI alerts" toggle in phone Settings →
      Diagnostics so users can mute the channel without touching
      Health Connect grants.

### Other AI deferrals (lower priority)

- [ ] **Diff view** on Today — "this week vs last week" side-by-side
      structured cards. Backend `POST /ai/explain/diff?ranges=…`
      returns two structured outputs and a delta narrative.
- [ ] **Source citations** — make claims in AI cards clickable to
      jump to the underlying data point ("HRV 11ms on May 6" → opens
      `/trends#hrv` zoomed to that day). Needs a structured response
      schema with `(text, link)` tuples.
- [ ] **Smart cache invalidation** — currently any tiny payload-hash
      delta re-bills. Could whitelist only material fields (changing
      `notes` shouldn't bust the sleep cache).
- [ ] **Local LLM option** — Ollama / Llama backend; same `/ai/*`
      endpoints, different SDK behind a config flag. Pure privacy
      play.
- [ ] **Voice Q&A** on the phone — TTS the answer; tap-to-speak
      input via Android speech recognizer.
- [ ] **HA env enrichment** — `env_readings` (bedroom temp/humidity)
      already in DB but not in Claude's payload. Adding it lets the
      model correlate sleep with environmental factors.

## Home Assistant device-status sync (planned, 7 tasks · scope trimmed v0.7.181)

Add HA WebSocket as a liveness signal for the Pixel Watch 3 —
watch on/off, charging, activity state, battery. HC stays the
authoritative source for **everything else** (HR, HRV, SpO2,
sleep, skin temp, steps).

**Scope trimmed after probing the actual data:** the Wear OS
Companion App's `sensor.pixel_watch_3_heart_rate` writes only ~17
HC rows over 48 hours (vs HC's ~1400 samples/hour). HA can't
deliver realtime HR with this setup, so HR + steps are dropped
from the HA pipeline — they'd produce strictly worse data than
HC. HA's job here is the "watch on / off / charging" tile that HC
literally cannot produce.

- [ ] **#HA-1** Alembic — `device_status` hypertable + ORM model.
- [ ] **#HA-2** Backend — `integrations/ha_realtime.py` WebSocket
      consumer + dispatch. Subscribe ONLY to device_status-class
      entities (`on_body`, `activity_state`, `battery_level`,
      `battery_state`, `charger_type`). Originally planned to also
      carry HR + daily_steps; dropped per the probe above.
- [ ] **#HA-3** Backend — lifespan wiring in `main.py` so the
      consumer starts/stops with the app. Blocked by #HA-2.
- [ ] **#HA-4** Backend — `GET /api/device-status/latest`
      returning the most recent watch status row. Blocked by #HA-1.
- [ ] **#HA-5** Frontend — `Settings.vue` HA section (URL / token /
      connected indicator). Include a blurb explaining HA is
      liveness-only; HR/HRV/SpO2/sleep stay on HC. Blocked by
      #HA-3, #HA-4.
- [ ] **#HA-6** Frontend — `Home.vue` Watch status tile rendering
      `/api/device-status/latest`. Blocked by #HA-4.
- [ ] **#HA-7** Manual — generate a long-lived HA token; paste
      into Settings. Blocked by #HA-5.
- [ ] **#HA-8** Smoke + freshness verification — device_status
      updates land within seconds, disconnect writes online=false,
      reconnect recovers. Blocked by #HA-7.

*(`#HA-9` source-priority dedupe dropped — no HC/HA overlap to
dedupe now that HA isn't carrying HR or steps.)*

## Fasting feature (planned, 15 tasks)

Intermittent-fasting tracker with protocol catalog, scheduled +
active modes, configurable notification cadence, home-screen widget
+ app-shortcut tile, religious calendar pre-sets, and AI / Insights
correlation surfaces. Full scope confirmed; nothing built yet.

Ship order driven by dependencies:

1. **Backend foundation**
   - [ ] **#FAST-1** `fasting_sessions` table + Alembic migration.
         Hypertable on `started_at`. Single-active-session unique
         index `WHERE ended_at IS NULL`.
   - [ ] **#FAST-2** `/fasting/*` endpoints — start, end, current,
         history, stats. Stage thresholds computed server-side
         (gut_rest / glycogen / ketosis / autophagy / deep_autophagy
         / 36h / 48h / 72h+) so phone + web render identical text.
   - [ ] **#FAST-8** Daily-summary integration — add `fasting_hours`
         to the nightly rollup so Today + AI surfaces can consume
         fasting context with one query.

2. **UI parity (parallel)**
   - [ ] **#FAST-3** Vue Fasting view — active ring + stage label +
         Start/End + protocol picker + history card + streak pill.
   - [ ] **#FAST-4** Phone FastingScreen composable — same shape.
         New tab in BottomBar; encrypted-prefs offline cache.

3. **Settings + notifications**
   - [ ] **#FAST-7** Settings — full protocol catalog picker, Active
         vs Scheduled mode toggle, eating-window times, per-stage
         notification cadence checklist (4h / 12h / 16h / 18h / 24h /
         36h / 48h / 72h / target reached / window-opens-in-30 /
         window-closing-in-30), religious-calendar opt-in.
   - [ ] **#FAST-5** Phone milestone notifications — new
         `FASTING_CHANNEL_ID`, WorkManager one-shots scheduled at
         each enabled stage threshold; cancelled if fast ends early.

4. **Widgets**
   - [ ] **#FAST-6** 1×1 app-shortcut tile (long-press app icon →
         Fasting). Mirrors the Workout / Trails shortcuts added in
         v0.7.164. New `ic_shortcut_fasting.xml` vector.
   - [ ] **#FAST-9** 2×1 live home-screen widget — elapsed time +
         stage label + progress ring. AppWidgetProvider +
         RemoteViews + WorkManager 15-min refresh during active
         fasts.

5. **Scheduled + extended**
   - [ ] **#FAST-12** Scheduled-mode auto start/end — WorkManager
         one-shots at the user's eating-window boundaries POST
         `/fasting/start` and `/fasting/end`. Rescheduled on every
         fasting_prefs change; manual End wins.
   - [ ] **#FAST-13** `fasting_logs` table — hunger / mood /
         hydration / notes during a fast. Surfaced as an in-fast
         card during sessions >12h.
   - [ ] **#FAST-10** Extended-fast protocols (24h+) + symptoms /
         hydration card. 5:2, Eat-Stop-Eat, ADF, Extended 36/48/72h.
         Electrolyte reminder card at 24h / 48h (informational).

6. **Religious calendar**
   - [ ] **#FAST-14** Ramadan / Lent / Yom Kippur pre-sets. 5-year
         static date table; #FAST-12 worker auto-starts/ends on
         those dates. Solar-aware Ramadan windows need lat/long
         (Settings can ask, fallback to local 5:00 / 19:30).

7. **AI + Insights correlations**
   - [ ] **#FAST-11** Plumb `current_fast` + `recent_fast_hours_7d`
         into deload-check + today's verdict payloads so AI tones
         recommendations during a fast.
   - [ ] **#FAST-15** Add `fasting_hours` to the correlation engine
         (`_DAILY_SUMMARY_METRICS`) so Insights auto-surfaces
         fasting↔HRV/weight/sleep relationships.

## Fitbit → Google Health migration (May 19, 2026)

Google is rebranding the Fitbit app to Google Health with auto-
updates rolling May 19–26, 2026. Most of myvitals' Fitbit usage is
file-based imports + Health Connect, so impact is limited but
needs verification post-cutover. All tasks are gated until after
the user's phone has auto-updated to Google Health.

- [ ] **#FITBIT-1** Post-May 19 sync smoke test — verify
      Pixel Watch 3 → Google Health → Health Connect → SyncWorker
      flow still works; check `/query/last-sync` has no
      `permissions_lost` flag; compare record-counts 24h before
      vs after the transition.
- [ ] **#FITBIT-2** Test `parse_fitbit_zip` against a Google Health
      export. Catalog any filename / directory-layout deltas vs
      the legacy Fitbit ZIP; update the parser to handle both
      shapes so archived exports still import.
- [ ] **#FITBIT-3** Update Settings.vue + README copy for the
      Google Health rebrand — change "Fitbit" labels to "Fitbit
      / Google Health" and replace the export-URL link with the
      post-cutover URL once known. Blocked by #FITBIT-2.
- [ ] **#FITBIT-4** Mark `_parse_fitbit_wrist_temp` as legacy —
      Google is removing skin temperature minute-by-minute data;
      keep the parser for historical ZIPs but emit a "deprecated"
      notice in import-job results when a Google Health export
      yields zero wrist-temp rows. Blocked by #FITBIT-2.
- [ ] **#FITBIT-5** HC background-read permission parity check —
      verify `READ_HEALTH_DATA_IN_BACKGROUND` still works after
      Google Health takes over as the HC writer. If Android
      re-prompts for grants, route the user through the existing
      v0.7.133 re-grant banner.

Not affected (per Google's published guidance):
- Health Connect API contract — explicitly maintained
- Strava + Withings — independent OAuth, no Fitbit linkage in
  myvitals
- Garmin imports — separate ecosystem
- Fasting / sober / workouts / trails / AI surfaces — no Fitbit
  dependency

## Other deferred features

- [x] **Fitbod / strength importer** — done in v0.6.0 as a generator,
      not an importer. `strength_workouts` + `strength_sets` populated
      via the on-device logging UI; no third-party dependency.
- [ ] **Strength v2 — catalog supplement** — add ~25 named exercises
      Fitbod has that free-exercise-db doesn't (Incline Row, Kroc Row,
      Bird Dog Row, Renegade Row, Tate Press, Single-Arm Floor Press,
      B-Stance RDL, DB Hip Thrust, Cuban Rotation, Zottman Preacher,
      Cross-Body Hammer, Plank Pull-Through, Pike / Archer / Hindu
      push-ups, etc.) as a supplementary JSON merged at catalog load.
- [x] **Strength v2 — training preferences UI** — done.
      `StrengthEquipment.vue` has a training section editing
      `level / days_per_week / split_preference / workout_minutes /
      include_mobility / yoga_on_rest_days / cardio_days_per_week /
      goal` (`strength` | `hypertrophy` | `general`, added v0.7.147).
      `put_equipment` auto-regens today's plan when any of these
      change and today's workout is planned + has zero logged sets.
- [x] **Strength v2 — exercise swap** — done. Per-exercise "Swap
      exercise" button on the active workout screen filtered by
      `/workout/strength/workout-exercises/{wex_id}/swap` plus the
      AI Variety nudge (`POST /ai/strength/nudge/{workout_id}`)
      returning 0-2 surgical AI suggestions with reasoning.
- [x] **Strength v2 — AI coach surfaces** — done. Consolidated Coach
      card (`CoachCard.vue` / `CoachCard` composable) with four rows:
      multi-signal deload trigger (`/ai/strength/deload-check`),
      per-workout focus cue (`/ai/strength/focus-cue/{id}`), variety
      nudge, and Why-this-workout rationale. State hoisted to the
      parent screen (`CoachCardState` class) so it survives LazyColumn
      re-creation.
- [x] **Strength v2 — goal-aware prescription** — done. `prescribe_slot`
      reads training.goal + profile.age + latest bodyweight; rotation
      pressure (`recent_frequency_by_exercise`) down-ranks recently-used
      exercises. Weekly muscle-group volume audit endpoint exposes
      sets/MEV/MAV per primary_muscle.
- [x] **Trail-status integration** — done in v0.7.0 (web only). Backend
      polls RainoutLine `/dnis_refresh` every 15 min, persists snapshots
      as a hypertable, and exposes /trails endpoints. Frontend Trails
      view with subscribe-star. Phone-side TrailsScreen + push deferred
      to v0.7.1.
- [x] **Trail-status — phone surface** — done in v0.7.2.
      `ui/trails/TrailsScreen.kt`, BackendClient extended,
      `Notifier.TRAIL_CHANNEL_ID` separate channel, TrailAlertWorker
      polls every 30 min and posts a notification per unnotified
      flip. Added as 4th bottom-nav tab (Sober / Workout / Trails /
      Settings).
- [ ] **#PHONE-EQUIP-1 Equipment + training prefs on phone** —
      currently web-only (`StrengthEquipment.vue` PUTs to
      `/workout/strength/equipment`). Phone reads equipment for
      display but can't edit. Add an `EquipmentScreen.kt` (under
      Settings or the Workout group) that covers dumbbells / bench /
      pull_up_bar / cardio gear / training.* fields. Match web's
      auto-regen behavior — when days_per_week or split_preference
      change and today's workout is planned + zero logged sets,
      backend already regenerates; phone just needs to refetch.
- [ ] **iOS app** — currently Android-only. Same Health Connect
      analogue would be HealthKit on iOS.
- [ ] **Multi-user** — single-user assumed throughout; no user_id
      column on most tables. Big refactor if ever wanted.
- [ ] **Watch-side complication** — Wear OS face complication
      showing sober days / readiness / verdict.
