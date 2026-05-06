# Architecture

## Components

```
┌─────────────────┐
│ Pixel Watch 3   │
└────────┬────────┘
         │ Health Connect (continuous)
         ▼
┌──────────────────────────────────────┐
│ Android phone — companion app        │
│   • HealthConnectGateway: read perms │
│   • SyncWorker (15 min):             │
│       reads HC since checkpoint,     │
│       POSTs /ingest/batch.           │
│       On failure → Room buffer.      │
│   • UpdateCheckWorker (24 h):        │
│       polls GitHub Releases API,     │
│       inline install button in UI.   │
│   • Timber → RoomLogTree → "logs".   │
│   • LogUploadWorker (15 min):        │
│       POST /debug/logs.              │
└──────┬───────────────────────────────┘
       │ HTTP(S) bearer token (Ingest)
       ▼
┌────────────────────────────────────────────────────────┐
│ Proxmox LXC — Docker Compose                           │
│                                                         │
│  ┌──────────────────┐    ┌────────────────────────┐    │
│  │ FastAPI          │◄──►│ TimescaleDB            │    │
│  │ /ingest          │    │ vitals_* hypertables,  │    │
│  │ /query, /summary │    │ daily_summary,         │    │
│  │ /log, /debug/    │    │ annotations, alerts,   │    │
│  │ /sober           │    │ workouts, sober_streaks│    │
│  │ /ai (Claude)     │    │ ai_config, ai_summaries│    │
│  │ APScheduler:     │    │ ai_alerts, ai_goals,   │    │
│  │  - daily summary │    │ sync_heartbeat, ...    │    │
│  │  - HA pull (5m)  │    └────────────────────────┘    │
│  │  - anomaly (6h)  │                ▲                  │
│  │  - weekly digest │                │ Anthropic SDK    │
│  └────────┬─────────┘                ▼                  │
│           │                  ┌─────────────────┐        │
│           │ /api/*           │ Claude API      │        │
│           ▼                  │ (opt-in, key in │        │
│  ┌──────────────────┐         │  ai_config DB) │        │
│  │ Caddy + Vue 3 SPA│         └─────────────────┘        │
│  │  ECharts panels  │                                    │
│  └──────────────────┘                                    │
└────────────────────────────────────────────────────────┘
       ▲                              ▲
       │ /api/states/* (every 5 min)  │ optional weather
       │                              │
   Home Assistant                 OpenWeather (cron)
   (env_readings rows)            (env_readings rows)
```

## Why TimescaleDB instead of InfluxDB

- Single store for time-series + relational (annotations, derived summaries).
- SQL — easier to write analytics jobs in SQLAlchemy/pandas than InfluxQL/Flux.
- Keeps health data isolated from any existing infra-metrics store.

## Tables (current Alembic head = 0020)

**Hypertables** (TimescaleDB, 7-day chunks)
- `vitals_heartrate(time, bpm, source)`
- `vitals_hrv(time, rmssd_ms)`
- `vitals_spo2(time, percent)`
- `vitals_skin_temp(time, celsius_delta)`
- `vitals_steps(time, count)`
- `sleep_stages(time, stage, duration_s)` — composite PK
- `workouts(time, type, duration_s, kcal, avg_hr, max_hr, source, title)`
- `env_readings(time, source, metric, value)` — composite PK

**Relational**
- `annotations(id, ts, type, payload JSON, note)` — manual log entries
- `daily_summary(date PK, resting_hr, hrv_avg, recovery_score, sleep_duration_s, sleep_score, steps_total, readiness_score, training_stress_score, ctl, atl, tsb, sleep_consistency_score, sleep_debt_h, ...)`
- `activities(source, source_id, type, name, start_at, duration_s, distance_m, elevation_gain_m, avg_hr, max_hr, avg_power_w, max_power_w, kcal, suffer_score, polyline, hr_recovery_60s, hr_recovery_120s, raw, notes, tags)` — Strava + Garmin imports
- `alerts(id, ts, kind, payload, acknowledged)` — legacy stat alerts
- `app_logs(id, ts, source phone|server, level, tag, message, stack, received_at)`
- `body_metrics(time, weight_kg, body_fat_pct, bmi, lean_mass_kg, source)`
- `blood_pressure(time, systolic, diastolic, pulse_bpm, source, notes)`
- `sleep_sessions(start_at, end_at, source, title)` — canonical session boundaries
- `import_jobs(id, kind, filename, status, started_at, finished_at, counts, error)`
- `user_profile(id=1, birth_date, sex, height_cm, weight_goal_kg, resting_hr_baseline, activity_level, extra)`
- `strava_credentials`, `strava_app_config` — OAuth state
- `sober_streaks(id, addiction, start_at, end_at, notes)` — sobriety history
- `sync_heartbeat(attempt_at, success, permissions_lost, ...)` — phone diagnostics
- **AI tables:**
  - `ai_config(id=1, enabled, anthropic_api_key, model, daily_call_limit, calls_today, calls_today_date, weekly_digest_enabled, tone)`
  - `ai_summaries(id, generated_at, range_kind, payload_hash, model, input_tokens, output_tokens, content)` — cached LLM responses
  - `ai_alerts(id, created_at, kind, severity, title, body, metric, z_score, dedup_key, acked_at, phone_notified_at)` — anomaly notifications
  - `ai_goals(id, kind, title, target_value, target_unit, target_date, started_at, ended_at, notes)`

## Auth model

- `INGEST_TOKEN` — phone uses this to POST `/ingest/*` and `/debug/logs`. High write blast radius.
- `QUERY_TOKEN` — frontend uses this to GET `/query/*`, `/summary/*`, `/log`, `/debug/logs`, `/ai/*`, etc.
- `/sober/*` accepts EITHER token (the phone's home counter + reset and the dashboard need the same endpoints).
- No users table. If a second user is ever needed, add a `users` table and per-user tokens.

The frontend reads `QUERY_TOKEN` from `localStorage` at runtime (set in `/settings`), so deployments don't need to be rebuilt to rotate it.

The Anthropic API key is **not** in `.env` — it lives in `ai_config.anthropic_api_key`, set via the dashboard's Settings → AI panel. Empty key = AI feature disabled.

## Data freshness

| Hop | Cadence |
|---|---|
| Watch → phone (Health Connect) | continuous |
| Phone → backend (`SyncWorker`) | 15 min, +manual "Sync now" |
| Phone logs → backend (`LogUploadWorker`) | 15 min, +manual "Sync logs now" |
| Backend → frontend | live (no caching v0) |
| HA → `env_readings` (`pull_states`) | 5 min |
| Daily summary | 03:00 in `TZ` |
| GitHub Releases poll (in-app updater) | 24 h, +manual "Check for updates" |

## Analytics jobs (APScheduler, in-process)

| Job | Cadence | Output |
|-----|---------|--------|
| `compute_daily_summary` | 03:00 in `TZ` | one `daily_summary` row, possibly an `alerts` row |
|   ↳ `nightly_rhr` / `nightly_hrv` | — | mean HR/HRV during 22:00–09:00 window |
|   ↳ `rolling_baseline` | — | 7-day median |
|   ↳ `recovery_score` | — | HRV deviation vs baseline, 0–100 |
|   ↳ `sleep_score` | — | duration + deep/REM proportion (excludes awake), 0–100 |
|   ↳ readiness / TSB / CTL / ATL | — | training-stress balance, fitness/fatigue |
|   ↳ sleep consistency / debt | — | rolling bedtime variance + cumulative debt |
|   ↳ RHR drift alert | — | if RHR ≥ baseline + 5 bpm |
| `pull_states` (HA) | 5 min | `env_readings` rows for configured `HA_ENTITIES` |
| `strava_int.sync_recent` | 6 h | imports new Strava activities (no-op if not configured) |
| `_anomaly_scan` (AI) | 6 h | z-score outlier detection → Claude phrasing → `ai_alerts` row, no-op if AI disabled |
| `_weekly_ai_digest` (AI) | Sun 22:00 in `TZ` | weekly summary in `ai_summaries` if `weekly_digest_enabled=true` |

## AI integration (opt-in, single-user)

All AI features sit behind `ai_config.enabled = true` AND a non-empty `ai_config.anthropic_api_key`. With either condition off, every endpoint returns a structured `400` or no-ops in cron jobs.

**Endpoints under `/ai/*`** (require_query):

| Endpoint | Output | Notes |
|---|---|---|
| `GET /ai/config` | current settings (key masked) | |
| `POST /ai/config` | partial update | enabled, key, model, daily_call_limit, weekly_digest_enabled, tone |
| `GET /ai/preview-payload` | exact JSON that would be sent | audit before opt-in |
| `POST /ai/explain` | markdown narrative | legacy free-form |
| `POST /ai/explain/{topic}` | structured JSON | week / month / sleep / recovery / sober / anomaly |
| `POST /ai/explain-all` | all 5 topics in one call | uses Claude tool-use; ~1 call instead of 5 |
| `POST /ai/explain-discovery` | plain-English correlation read | body: `{x_metric, y_metric}` |
| `POST /ai/verdict` | one-sentence headline | cached by payload hash |
| `POST /ai/pre-workout` | training recommendation | Go hard / Moderate / Easy / Rest |
| `POST /ai/ask` | free-form Q&A answer | body: `{question}` |
| `POST /ai/activity/{src}/{id}/summary` | post-activity 2-line context | |
| `GET/POST/PATCH/DELETE /ai/goals` | goal CRUD | weight / sober / sleep / steps / custom |
| `POST /ai/goals/{id}/check` | coaching read on a goal | |
| `GET /ai/badges` | trend badges, no LLM | always-on chips on Today |
| `GET /ai/alerts` | unacked anomaly alerts | banner source |
| `POST /ai/alerts/{id}/ack` | dismiss one | |
| `POST /ai/alerts/ack-all` | dismiss all | |
| `POST /ai/alerts/mark-notified` | phone calls after pushing | dedup |

**Bounded payload** (what gets sent to Anthropic):
- Daily summaries (last 7 / 30 days), pre-aggregated
- Top 5 correlations from `/analytics/discoveries` (90-day window)
- Profile context (age range, sex, activity level, RHR baseline) — no DOB/name/email
- Activity details (type, duration, HR zones, power, pace, suffer, HR recovery)
- Annotations (caffeine/alcohol/mood/meds — payload only, free-form notes excluded)
- Sober streak shape (current days, total resets, longest, avg) — no history dates
- Trend badges (already aggregated)

**Never sent:** raw HR/HRV samples, GPS tracks, exact sleep timestamps, the user's name/email, sober history dates, free-form annotation notes, bearer tokens.

**Cost:**
- Default model is Haiku 4.5 (`claude-haiku-4-5-20251001`) — ~$0.0005-$0.005 per call
- Anthropic prompt caching (`cache_control: ephemeral`) on system prompts — ~50% off compounded over multiple calls
- Daily call limit enforced server-side (default 30/day)
- Cache layer (`ai_summaries`, keyed by payload hash) — re-asks return existing rows free
- Sonnet 4.6 / Opus 4.7 selectable via Settings if heavier reasoning is wanted

## Android app structure

```
app.myvitals/
├── MyVitalsApp.kt            // schedules SyncWorker, UpdateCheckWorker, LogUploadWorker; plants Timber trees
├── MainActivity.kt           // Compose entry; requests POST_NOTIFICATIONS on Android 13+
├── data/
│   ├── SettingsRepository.kt // EncryptedSharedPreferences for token, plain prefs for URL/last-sync
│   └── AppDatabase.kt        // Room: buffered_batches + logs
├── health/
│   ├── HealthConnectGateway.kt
│   └── DataMapper.kt         // HC records → IngestBatch
├── sync/
│   ├── SyncWorker.kt
│   ├── BackendClient.kt      // Retrofit + Moshi
│   └── Models.kt             // DTOs matching backend schemas
├── update/
│   ├── GitHubApi.kt          // /repos/.../releases/latest
│   ├── UpdateChecker.kt      // semver compare
│   ├── UpdateCheckWorker.kt
│   ├── Notifier.kt           // notification channel
│   └── UpdateInstallerActivity.kt   // DownloadManager → FileProvider → install intent
├── debug/
│   ├── RoomLogTree.kt        // Timber → "logs" table; tag inferred from stack
│   ├── LogViewerActivity.kt  // Compose log viewer with level filter
│   └── LogUploadWorker.kt    // POST unsent rows to /debug/logs
└── ui/
    └── SettingsScreen.kt     // single-screen Compose UI
```

## What's NOT in scope (v0)

- Multi-user / account system
- iOS / Apple Watch (Health Connect is Android-only)
- Medical-grade interpretation — personal trend awareness, not diagnosis
- TLS termination — backend is HTTP on LAN; deploy behind NPM/Caddy if exposing publicly
