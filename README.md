<p align="center">
  <img src="docs/images/wordmark.svg" alt="myvitals — self-hosted, personal, health" width="540"/>
</p>

<p align="center">
  Self-hosted personal health tracking &amp; analytics. <em>Single user.</em>
</p>

<p align="center">
  <a href="https://github.com/Pr0zak/myvitals/releases/latest"><img src="https://img.shields.io/github/v/release/Pr0zak/myvitals?include_prereleases&color=ef4444&label=release" alt="release"/></a>
  <a href="https://github.com/Pr0zak/myvitals/actions/workflows/android-release.yml"><img src="https://img.shields.io/github/actions/workflow/status/Pr0zak/myvitals/android-release.yml?branch=main&label=APK%20build" alt="APK build"/></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="python"/>
  <img src="https://img.shields.io/badge/vue-3-42b883?logo=vue.js&logoColor=white" alt="vue 3"/>
  <img src="https://img.shields.io/badge/kotlin-android-7f52ff?logo=kotlin&logoColor=white" alt="kotlin"/>
</p>

---

<p align="center">
  <img src="docs/images/feature-strip.svg" alt="features" width="100%"/>
</p>

## What it does

Pulls your **Pixel Watch / Wear OS** data out of **Health Connect** on the phone, ships it to a **FastAPI + TimescaleDB** backend you run yourself, and renders a **Vue 3 + ECharts** dashboard on top. No cloud, no third-party SaaS — your health data lives on hardware you own.

- **Today** — readiness ring, KPI grid (HR, BP, sleep, recovery, steps, watch wear-time, sober counter), 24h heart-rate ribbon with sync-gap visualisation
- **Trends** — long-term overlays (RHR / HRV / Recovery / Sleep) with sober-reset markers
- **Insights** — story-first feed of auto-discovered correlations (`More alcohol → less HRV`) with plain-English effect sentences and an explorer for ad-hoc questions
- **Sleep / Weight / Blood pressure / Skin Δ** — dedicated views per metric
- **Sober time** — live `d/h/m/s` counter on the phone home screen with a 1.5s hold-to-confirm reset, full history with editable streaks, distribution + timeline charts on the web
- **Activities** — Strava sync + Garmin/Fitbit imports, GPS map view, side-by-side compare
- **Log** — caffeine / alcohol / mood / food / meds, all editable inline (date/time included)
- **Calendar** — year heatmap, any metric

Companion **Android app** does the heavy lifting: Health Connect reads on a 15-min `WorkManager`, retries via local Room buffer, posts a structured **sync heartbeat** to the backend so the dashboard can tell the difference between "phone is offline", "HC perms revoked", and "watch isn't pushing data".

## Architecture

```
Pixel Watch 3
     │
     ▼  Health Connect
  Phone (Kotlin / Compose — Health Connect → WorkManager → Retrofit)
     │
     ▼  HTTP(S) bearer token              ↩ /ingest/heartbeat
  FastAPI ingest  ──►  TimescaleDB  ◄──── HA REST poller (env_readings)
     │                                         (optional)
     ▼
  Vue 3 + ECharts dashboard
   ├ Today / Trends / Insights / Sleep / Activities
   ├ Calendar / Compare / Sober / Log / Logs
   └ Settings (token, units, theme, profile, imports, Strava)
```

Full diagram in [`docs/architecture.md`](docs/architecture.md).

## Stack

| Layer    | Tech |
|----------|------|
| Backend  | FastAPI, SQLAlchemy 2.x, asyncpg, Alembic, APScheduler |
| DB       | PostgreSQL 16 + TimescaleDB |
| Frontend | Vue 3, Vite, ECharts, Lucide, Geist |
| Android  | Kotlin, Compose Material 3, Health Connect, WorkManager, Retrofit, Room, Timber |
| Deploy   | Docker Compose in a Proxmox LXC (unprivileged, runc 1.1.x) |
| CI       | GitHub Actions → GHCR images + signed APK on tag |
| Tooling  | uv (Python), pnpm (frontend) |

## Quickstart (local dev)

```bash
cp .env.example .env                         # set INGEST_TOKEN, QUERY_TOKEN, POSTGRES_PASSWORD
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head && uv run fastapi dev src/myvitals/main.py
# new terminal:
cd frontend && cp .env.example .env && pnpm install && pnpm dev
```

Open `http://localhost:5173`, paste your `QUERY_TOKEN` in Settings, and the dashboard wires up.

## Deploy

Production runs in an unprivileged Proxmox LXC with Docker Compose:

```bash
# Bootstrap a fresh CT (pulls runc 1.1.x to dodge the unprivileged-LXC sysctl bug)
deploy/ct-bootstrap.sh
```

See [`docs/operations.md`](docs/operations.md) for day-to-day commands and [`docs/releasing.md`](docs/releasing.md) for the keystore + GHCR + APK release flow.

## Repo layout

```
backend/                  FastAPI ingest + analytics + alembic migrations
frontend/                 Vue 3 dashboard
android/                  Kotlin / Compose companion app
deploy/                   ct-bootstrap.sh + upgrade.sh
.github/workflows/        images.yml (GHCR) + android-release.yml (signed APK)
docs/                     architecture / operations / releasing + images
```

