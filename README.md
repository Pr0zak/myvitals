# myvitals

Self-hosted personal health tracking & analytics. Single user.

```
Pixel Watch 3
     │
     ▼  Health Connect
  Phone (Kotlin app — Health Connect → WorkManager → Retrofit)
     │
     ▼  HTTP(S) POST + bearer token        ↩ optional log shipping
  FastAPI ingest  ──►  TimescaleDB  ◄──────  HA REST poller (env_readings)
     │
     ▼
  Vue 3 + ECharts dashboard      iOS-style: Today / Trends / Sleep / Log / Logs / Settings
```

## Status

- **Backend, frontend, Android app**: shipped through v0.1.4.
- **Production deploy**: CT 104 on `pve5` (Docker Compose, see `docs/operations.md`).
- **Releases**: signed APK + GHCR images on every `v*` tag (see `docs/releasing.md`).

## Stack

| Layer    | Tech |
|----------|------|
| Backend  | FastAPI, SQLAlchemy 2.x, asyncpg, Alembic, APScheduler |
| DB       | PostgreSQL 16 + TimescaleDB |
| Frontend | Vue 3, Vite, ECharts |
| Android  | Kotlin, Compose, Health Connect, WorkManager, Retrofit, Room, Timber |
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

## Deploy (Proxmox CT)

See `docs/releasing.md` for the keystore + secrets dance and `docs/operations.md` for the running CT.

## Repo layout

- `backend/` — FastAPI ingest + analytics
- `frontend/` — Vue 3 dashboard
- `android/` — Health Connect companion app (open in Android Studio)
- `deploy/` — CT bootstrap + upgrade scripts
- `.github/workflows/` — `images.yml` (GHCR) + `android-release.yml` (signed APK)
- `docs/` — architecture, releasing, operations

## Privacy

This is a personal-data app. Treat the repo as if it could one day be public.

- **Never commit `.env`** — it holds bearer tokens, the DB password, any HA token. `.gitignore` blocks it.
- **No real data in the repo** — the DB volume (`db_data`) lives outside the repo; migrations create empty schemas only.
- **Bearer tokens** — generate with `openssl rand -hex 32`. Rotate by editing `.env` and `docker compose restart backend`.
- **Don't paste real values into examples** — `.env.example` is a template; keep it free of locations, hostnames, IPs, or anything you wouldn't put on a sticker.
- **Before pushing**, run: `git diff --cached | grep -iE 'token|password|secret|@gmail|@outlook|192\.168|10\.\d+\.\d+'`
