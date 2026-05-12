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
- [ ] **iOS app** — currently Android-only. Same Health Connect
      analogue would be HealthKit on iOS.
- [ ] **Multi-user** — single-user assumed throughout; no user_id
      column on most tables. Big refactor if ever wanted.
- [ ] **Watch-side complication** — Wear OS face complication
      showing sober days / readiness / verdict.
