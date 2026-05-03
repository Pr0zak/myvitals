# Architecture

## Components

```
┌─────────────────┐
│ Pixel Watch 3   │
└────────┬────────┘
         │ Health Connect sync
         ▼
┌─────────────────┐
│ Phone           │
│ ┌────────────┐  │
│ │ companion  │  │  reads Health Connect, batches every 15 min
│ │ app (Kt)   │  │  offline buffer (Room) for failed posts
│ └─────┬──────┘  │
└───────┼─────────┘
        │ HTTPS POST /ingest/batch  (bearer)
        ▼
┌────────────────────────────────────────────┐
│ Proxmox LXC                                 │
│ ┌──────────────┐    ┌────────────────────┐ │
│ │ FastAPI      │◄──►│ TimescaleDB        │ │
│ │ (uvicorn)    │    │ (PG 16 + ext)      │ │
│ └──────┬───────┘    └────────────────────┘ │
│        │                                    │
│        │  reads aggregates                  │
│        ▼                                    │
│ ┌──────────────┐                            │
│ │ Caddy + Vue  │  /api/* → backend          │
│ │ SPA          │  /     → static SPA        │
│ └──────────────┘                            │
└────────────────────────────────────────────┘
        ▲
        │ HA REST (pull bedroom temp, presence)
        │ Weather API (cron)
        │
   external sources
```

## Why TimescaleDB instead of InfluxDB

- Single store for time-series + relational (annotations, derived summaries).
- SQL — easier to write the analytics jobs in pandas/SQL than InfluxQL/Flux.
- Keeps health data isolated from any existing infra-metrics store.

## Auth model

- `INGEST_TOKEN` — phone uses this to POST. High write blast radius, treat as secret.
- `QUERY_TOKEN` — frontend uses this to GET. Lower blast radius; rotate independently.
- No users table. If a second user is ever needed, add a `users` table and per-user tokens.

## Data freshness

- Watch → phone: continuous (Health Connect handles it).
- Phone → backend: 15 min default, configurable, manual "sync now" button in app.
- Backend → frontend: live query (no aggressive caching at v0).

## Analytics jobs

Run as APScheduler tasks inside the FastAPI process:

| Job | Cadence | Output |
|-----|---------|--------|
| Daily summary | 03:00 local | `daily_summary` row for previous day |
| RHR baseline + drift | 03:05 local | alert if drift > 5 bpm vs 28-day baseline |
| Recovery score | After morning sync | written to `daily_summary` |
| HA pull | every 5 min | `env_readings` rows |
| Weather pull | every 30 min | `env_readings` rows |

## What's NOT in scope

- Multi-user / account system
- Mobile-friendly responsive UI is nice-to-have, not v0 (frontend works on phone but not optimised)
- iOS / Apple Watch (Health Connect is Android only)
- Medical-grade interpretation — this is for personal trend awareness, not diagnosis
