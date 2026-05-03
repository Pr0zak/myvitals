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
│ Proxmox LXC (CT 104, pve5) — Docker Compose            │
│                                                         │
│  ┌──────────────────┐    ┌────────────────────────┐    │
│  │ FastAPI          │◄──►│ TimescaleDB            │    │
│  │ /ingest, /query, │    │ vitals_* hypertables,  │    │
│  │ /summary, /log,  │    │ daily_summary, alerts, │    │
│  │ /debug/logs      │    │ annotations, app_logs  │    │
│  │ APScheduler:     │    │ env_readings           │    │
│  │  – daily summary │    └────────────────────────┘    │
│  │  – HA pull (5m)  │                                  │
│  └────────┬─────────┘                                  │
│           │                                             │
│           │ /api/* (Caddy reverse proxy)               │
│           ▼                                             │
│  ┌──────────────────┐                                  │
│  │ Caddy + Vue 3 SPA│ Today, Trends, Sleep, Log,      │
│  │  ECharts panels  │ Logs, Settings                  │
│  └──────────────────┘                                  │
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

## Tables (Alembic 0001 + 0002)

**Hypertables** (TimescaleDB, 7-day chunks)
- `vitals_heartrate(time, bpm, source)`
- `vitals_hrv(time, rmssd_ms)`
- `vitals_spo2(time, percent)`
- `vitals_skin_temp(time, celsius_delta)`
- `vitals_steps(time, count)`
- `sleep_stages(time, stage, duration_s)` — composite PK
- `workouts(time, type, duration_s, kcal, avg_hr, max_hr)`
- `env_readings(time, source, metric, value)` — composite PK

**Relational**
- `annotations(id, ts, type, payload JSON, note)` — manual log entries
- `daily_summary(date PK, resting_hr, hrv_avg, recovery_score, sleep_duration_s, sleep_score, steps_total, notes)`
- `alerts(id, ts, kind, payload, acknowledged)`
- `app_logs(id, ts, source phone|server, level, tag, message, stack, received_at)`

## Auth model

- `INGEST_TOKEN` — phone uses this to POST `/ingest/*` and `/debug/logs`. High write blast radius.
- `QUERY_TOKEN` — frontend uses this to GET `/query/*`, `/summary/*`, `/log`, `/debug/logs`.
- No users table. If a second user is ever needed, add a `users` table and per-user tokens.

The frontend reads `QUERY_TOKEN` from `localStorage` at runtime (set in `/settings`), so deployments don't need to be rebuilt to rotate it.

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
|   ↳ `sleep_score` | — | duration + deep/REM proportion, 0–100 |
|   ↳ RHR drift alert | — | if RHR ≥ baseline + 5 bpm |
| `pull_states` (HA) | 5 min | `env_readings` rows for configured `HA_ENTITIES` |

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
