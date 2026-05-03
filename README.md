# myvitals

Self-hosted personal health tracking & analytics. Single user.

```
Pixel Watch 3
     │
     ▼  (Health Connect)
  Phone (Android companion app)
     │
     ▼  HTTPS POST + bearer token
  FastAPI ingest  ──►  TimescaleDB
     │
     ▼
  Vue 3 + ECharts dashboard
```

## Stack

| Layer    | Tech |
|----------|------|
| Backend  | FastAPI, SQLAlchemy 2.x, asyncpg, Alembic |
| DB       | PostgreSQL 16 + TimescaleDB |
| Frontend | Vue 3, Vite, ECharts, Pinia |
| Android  | Kotlin, Health Connect, WorkManager, Retrofit, Room |
| Deploy   | Docker Compose in a Proxmox LXC |
| Tooling  | uv (Python), pnpm (frontend) |

## Quickstart (dev)

```bash
cp .env.example .env
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head && uv run fastapi dev src/myvitals/main.py
cd frontend && pnpm install && pnpm dev
```

## Deploy (Proxmox CT)

See `deploy/ct-bootstrap.sh`.

## Repo layout

- `backend/` — FastAPI ingest + analytics
- `frontend/` — Vue 3 dashboard
- `android/` — Health Connect companion app (open in Android Studio)
- `deploy/` — CT provisioning + reverse proxy config
- `docs/` — architecture notes

## Privacy

This is a personal-data app. Treat the repo as if it could one day be public.

- **Never commit `.env`** — it holds bearer tokens, the DB password, and any HA token. `.gitignore` blocks it.
- **No real data in the repo** — the DB volume (`db_data`) lives outside the repo; migrations create empty schemas only.
- **Bearer tokens** — generate with `openssl rand -hex 32`. Rotate by editing `.env` and `docker compose restart backend`.
- **Don't paste real values into examples** — `.env.example` is a template; keep it free of locations, hostnames, IPs, or anything you wouldn't put on a sticker.
- **Before pushing**, run: `git diff --cached | grep -iE 'token|password|secret|@gmail|@outlook|192\.168|10\.\d+\.\d+'`
