# myvitals — Claude project guide

Self-hosted personal health tracking. Single user. Vue 3 dashboard +
FastAPI/TimescaleDB backend + Kotlin/Compose Android companion app +
optional Claude AI narration layer.

## Where everything runs

- **Production:** unprivileged Proxmox LXC, Docker Compose, hostname
  `myvitals`. Use the placeholders `$PVE_HOST` / `$CT_ID` in any docs
  or commands you write — never hard-code the real host names.
- **App path on the CT:** `/opt/myvitals`
- **Compose stack:** `db` (TimescaleDB), `backend` (FastAPI :8000),
  `frontend` (Caddy :8080 → Vue)
- **GHCR images:** `ghcr.io/pr0zak/myvitals-{backend,frontend}`
- **APK releases:** GitHub Releases on every `v*` tag
- **Public repo:** `Pr0zak/myvitals`

## How to ship a change

1. Make the change locally (`/home/spider/myvitals`)
2. Sync + rebuild on the CT:
   ```bash
   tar cz -C /home/spider/myvitals \
     --exclude='.git' --exclude='node_modules' --exclude='.venv' \
     --exclude='*.apk' --exclude='*.jks' --exclude='keystore.properties' \
     --exclude='.env' --exclude='frontend/dist' --exclude='android' . | \
     ssh root@$PVE_HOST "pct exec $CT_ID -- bash -c 'cd /opt/myvitals && tar xz'" && \
   ssh root@$PVE_HOST "pct exec $CT_ID -- bash -c 'cd /opt/myvitals && \
     docker compose build backend frontend && \
     docker compose up -d --force-recreate backend frontend'"
   ```
3. Bump `backend/pyproject.toml` `version = "..."` so `/version`
   matches the tag. **Forgetting this leaves the side-nav chip
   stuck on the previous version.**
4. `git commit` with the v0.5.x style (verbose body, Co-Authored-By
   trailer matching prior commits)
5. `git tag vX.Y.Z && git push origin main && git push origin vX.Y.Z`
6. Pushing the tag triggers `android-release.yml` → signed APK lands
   on GitHub Releases ~4 min later
7. Phone's `UpdateCheckWorker` (6 h periodic + on-launch one-shot)
   notifies the user

## Public-repo discipline

The repo is **public**. Personal data must never land in it.

- `.env`, `keystore.properties`, `*.jks`, `*.apk` are gitignored —
  keep it that way.
- Never reference internal hostnames, IPs, or the maintainer's
  email/name in tracked files. Use `$PVE_HOST` / `$CT_ID`.
- Health data is in TimescaleDB on the CT; **never** dump it into
  the repo. The Sober Time CSV importer in Settings reads from the
  user's local disk only.
- Author email is `myhealthdev@users.noreply.github.com` (GitHub's
  privacy alias). Don't leak the real one in commits.
- Run `git diff --cached | grep -iE 'token|password|secret|@gmail|
  10\\.\\d+\\.\\d+|192\\.168'` before pushing if uncertain.

## AI integration — design notes

The **AI layer is opt-in**. Default off; enabled via
Settings → AI by pasting an Anthropic key.

Architecture choices worth preserving:

- **Two-tier:** statistical detection (no LLM, deterministic, free)
  feeds the trend badges + anomaly cron. Claude only handles
  *narration* of pre-aggregated facts, never raw samples.
- **Bounded payload:** see `claude.py:build_summary_payload`,
  `build_topic_payload`, `build_verdict_payload`. Adding a new
  surface should NOT mean sending more raw data — derive new
  aggregates server-side first.
- **Structured output** via Claude tool-use (`give_analysis` /
  `give_all_topics` schemas) — render as cards, not prose.
- **Prompt caching** on system prompts (`cache_control: ephemeral`)
  — keep system text fixed-ish to maximise cache hits.
- **Cache by payload hash** (`ai_summaries.payload_hash`) — same
  data should never re-bill.
- **Daily call limit** server-side (`ai_config.daily_call_limit`,
  default 30) — clients can't run away with the bill.
- **Default model is Haiku 4.5.** Sonnet/Opus selectable; for the
  structured output we produce, Haiku is plenty.
- **Tone setting** (Supportive / Blunt / Data-only) — plumbed
  through every system prompt builder.

When adding a new AI surface:
1. Build the payload server-side from existing aggregates
2. Use structured output (tool-use) so the frontend can render
   cards, not prose
3. Cache it (range_kind + payload_hash)
4. Hook through `_check_and_bump_quota` for the daily limit
5. Audit the payload — does anything new sneak in that wasn't there
   before? Update the privacy section in the README.

## Common gotchas

- **HC permissions revoke on APK upgrade.** Each install often wipes
  Health Connect grants. v0.5.9 added an auto-sync-on-grant; the
  banner-on-dashboard ("Health Connect permissions lost") catches
  the rest.
- **Docker in unprivileged Proxmox LXC:** `runc` 1.2+ from
  `containerd.io` crashes with sysctl errors. The CT bootstrap
  script swaps in Debian's 1.1.x. Don't `apt upgrade containerd.io`
  without re-applying.
- **Sober history CSV** on the maintainer's machine has the user's
  real name in the `addiction` column. The importer keeps that local
  — never echo it back to the public repo.
- **Anthropic key in DB, not .env.** Don't add `ANTHROPIC_API_KEY` to
  `.env.example` — keep the secret in `ai_config` only.
- **/version freezes if pyproject not bumped.** Bump the file each
  release.

## Repo layout

```
backend/                    FastAPI ingest + analytics + alembic
  src/myvitals/api/         ingest, query, summary, analytics, ai,
                            sober, profile, strava, exports, ...
  src/myvitals/api/workout/ strength.py — generated workouts, sets,
                            equipment, exercise catalog
  src/myvitals/data/        bundled exercise catalog
                            (free-exercise-db, public domain) +
                            ~24 MB of exercise JPGs served via
                            StaticFiles at /exercises/img/
  src/myvitals/integrations/  claude.py, strava.py, home_assistant.py
  src/myvitals/analytics/   sleep.py, advanced.py, trends.py,
                            strength.py — split selector, recovery-
                            aware adjustment, micro-loader-aware
                            weight rounder, deterministic generator
  alembic/versions/         migrations (current head: 0022)
frontend/                   Vue 3 + Vite + ECharts dashboard
  src/views/                Today, Insights, Trends, Sober, Goals, ...
  src/components/           SideNav, TrendBadges, AppLogo, ...
  src/api/client.ts         single API client
  src/format.ts             time/date formatters (12h/24h pref)
android/                    Kotlin / Compose companion app
  app/src/main/kotlin/app/myvitals/
    ui/                     SoberHomeScreen, SettingsScreen, BrandMark
    ui/strength/            StrengthTodayScreen (preview + active
                            workout + set logging + rest timer),
                            StrengthHistoryScreen
    strength/               StrengthRepository (API + offline buffer),
                            StrengthPlanCache (encrypted-prefs cache)
    sync/                   SyncWorker, BackendClient, Models
    health/                 HealthConnectGateway, DataMapper
    update/                 UpdateChecker, Notifier (notif. channel)
    debug/                  RoomLogTree, LogUploadWorker, LogViewer
deploy/                     ct-bootstrap.sh, upgrade.sh
docs/                       architecture.md, operations.md, releasing.md
.github/workflows/          images.yml, android-release.yml
TODO.md                     deferred work (incl. batch 3 phone alerts)
```

## Versioning convention

Tags are `vMAJOR.MINOR.PATCH`. The current line is `v0.6.x` (jumped
from `0.5.x` for the strength-training feature in v0.6.0). Every
release tag triggers the Android release CI; backend changes are
deployed manually via the rebuild flow above. Bump
`backend/pyproject.toml` for every tag.

## Strength training (v0.6.0+)

A Fitbod-style generated workout per day, filtered to the user's
actual home-gym equipment. The whole feature lives under the
`/workout/strength/*` API namespace and a `Workout` SideNav group
on the dashboard.

- **Generation runs server-side** so phone + dashboard render the
  same plan. Algorithm: `analytics/strength.py:generate_plan()`.
- **Equipment shape** is JSON in `user_equipment.payload`; adding a
  field doesn't need a migration. The Pydantic `EquipmentPayload`
  in `api/workout/strength.py` is the source of truth.
- **Recovery integration** is opt-in (`user_profile.strength_recovery_aware`).
  When on, the planner reads `daily_summary.recovery_score`,
  `sleep_duration_s`, `readiness_score` for today and applies a
  deload factor (or recommends a rest day below thresholds).
- **Micro-loader-aware weight rounder** — distinguishing feature.
  Bridges the gap between dumbbell pairs using sub-5lb wrist
  weights so prescriptions hit ~0.5lb resolution. No other strength
  app I checked (Fitbod, Hevy, Strong, JEFIT) does this. Tested in
  `backend/tests/test_strength_rounder.py`.
- **Catalog**: `data/exercises.json` from yuhonas/free-exercise-db
  (Unlicense / public domain), ~200 exercises filtered to
  `{dumbbell, bench, bodyweight}`. Images served via FastAPI
  `StaticFiles` at `/exercises/img/<slug>/{0,1}.jpg`.
- **AI workout review** — `POST /ai/strength/review/{id}` returns a
  structured 4-field card (headline, highlights, concerns,
  next-session suggestion) for a completed session. Cached by
  `ai_summaries.payload_hash` like other AI surfaces.

## Documentation map

- `README.md` — public-facing pitch + features
- `docs/architecture.md` — components, schema, AI design, jobs
- `docs/operations.md` — day-to-day commands ($PVE_HOST / $CT_ID)
- `docs/releasing.md` — keystore + GHCR + APK release flow
- `TODO.md` — deferred work
- `android/README.md` — phone-app starter notes
- `CLAUDE.md` — this file
