# myvitals — TODO

Tracking deferred work. Move items to commit messages as they ship.

## AI integration — batch 3 (deferred)

### Phone-side alert notifications

Backend already produces structured alerts (`/ai/alerts`) via the
6-hour anomaly cron. The companion app needs to surface them.

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

- [ ] **Fitbod / strength importer** — get per-set workout data into
      `strength_sets` (or fold into activities with type=strength).
      See chat history for API-scrape vs CSV-export options.
- [ ] **iOS app** — currently Android-only. Same Health Connect
      analogue would be HealthKit on iOS.
- [ ] **Multi-user** — single-user assumed throughout; no user_id
      column on most tables. Big refactor if ever wanted.
- [ ] **Watch-side complication** — Wear OS face complication
      showing sober days / readiness / verdict.
