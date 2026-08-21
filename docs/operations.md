# Operations

How myvitals is currently deployed and how to maintain it.

## Where it runs

| Component | Location |
|-----------|----------|
| LXC | An unprivileged Proxmox CT (`$CT_ID`) on a Proxmox host (`$PVE_HOST`), hostname `myvitals` |
| OS | Debian 12 (template `debian-12-standard_12.12-1_amd64.tar.zst`) |
| Resources | 2 vCPU, 2 GB RAM, 512 MB swap, 16 GB disk on the cluster's LVM-thin pool |
| Network | bridge `vmbr0`, IP via DHCP |
| Privilege | unprivileged, `features=keyctl=1,nesting=1` |
| App path | `/opt/myvitals` |
| Compose stack | `db` (TimescaleDB), `backend` (FastAPI :8000), `frontend` (Caddy :8080 → Vue) |
| Image source | currently `:local` (built on the CT). Switch to `ghcr.io/pr0zak/myvitals-{backend,frontend}:<tag>` after making the GHCR packages public. |
| Auto-start | `onboot=1` |
| Tags | `myvitals` |

## Getting in

These docs use `$PVE_HOST` (your Proxmox node) and `$CT_ID` (the LXC ID
the install script picked, default `104` from `deploy/ct-bootstrap.sh`).
Set them once per shell:

```bash
export PVE_HOST=your-proxmox-host
export CT_ID=104
```

```bash
# Direct (your SSH key was injected at create time)
ssh root@<CT-IP>

# Via the host (always works, no SSH config required)
ssh root@$PVE_HOST "pct exec $CT_ID -- bash -c '<cmd>'"

# CT lifecycle
ssh root@$PVE_HOST "pct status $CT_ID"
ssh root@$PVE_HOST "pct start $CT_ID"
ssh root@$PVE_HOST "pct reboot $CT_ID"
ssh root@$PVE_HOST "pct stop $CT_ID"
```

## Quick checks

```bash
# Container health
ssh root@$PVE_HOST "pct exec $CT_ID -- docker compose -f /opt/myvitals/docker-compose.yml ps"

# Backend version + git sha + build time
curl -s http://<CT-IP>:8000/version

# Recent logs (across both phone and server, last 24h)
curl -s -H "Authorization: Bearer <QUERY_TOKEN>" "http://<CT-IP>:8000/debug/logs?limit=20"

# Backend container logs (in-process, not /debug/logs)
ssh root@$PVE_HOST "pct exec $CT_ID -- docker compose -f /opt/myvitals/docker-compose.yml logs --tail=50 backend"
```

## Upgrade

See `releasing.md` for the full process. Quick path on the CT:

```bash
cd /opt/myvitals
./deploy/upgrade.sh                 # pulls latest GHCR tag (once GHCR is public)
./deploy/upgrade.sh --rebuild       # builds from local source (current default while GHCR is private)
./deploy/upgrade.sh 0.1.4           # pin to a specific version
```

## Configuration

`/opt/myvitals/.env` (mode 600) holds tokens, DB password, optional HA integration. Generate fresh tokens with:

```bash
openssl rand -hex 32
```

After editing `.env`:

```bash
docker compose up -d                # picks up new env on next container start
docker compose restart backend      # forces restart even without compose changes
```

## Database

```bash
# psql shell
ssh root@$PVE_HOST "pct exec $CT_ID -- docker compose -f /opt/myvitals/docker-compose.yml exec db psql -U myvitals -d myvitals"

# pg_dump (run on the CT, then scp the file out)
ssh root@$PVE_HOST "pct exec $CT_ID -- bash -c 'docker compose -f /opt/myvitals/docker-compose.yml exec -T db pg_dump -U myvitals myvitals | gzip > /tmp/myvitals-$(date +%F).sql.gz'"
ssh root@$PVE_HOST "pct pull $CT_ID /tmp/myvitals-$(date +%F).sql.gz ./myvitals-backup.sql.gz"
```

### Backups — what covers what

Two layers, with deliberately different jobs. Knowing which one to reach
for is most of the work during an incident.

| Layer | Covers | Frequency | Lives |
|---|---|---|---|
| Proxmox Backup Server | The whole CT — rootfs, docker volumes, config | Nightly 01:00 | Separate physical host |
| `deploy/backup.sh` | A logical dump of the database alone | Before each auto-update migration | `/var/backups/myvitals` on the CT |

PBS is the disaster-recovery layer and it is already configured; there is
no cron in this repo duplicating it. Restoring from PBS gives you the
entire container back as it was at 01:00, which is the right move when
the CT itself is gone or unbootable.

`deploy/backup.sh` exists for the narrower case PBS handles badly. The
backend image's `CMD` is `alembic upgrade head && fastapi run …`, so
migrations apply unattended within ~15 minutes of a tag being pushed. If
one of them corrupts or drops data, the newest PBS restore point can be
up to 24 hours old and using it reverts *everything* — including every
sample ingested since 01:00. So `auto-update.sh` takes a dump in the
seconds before the recreate that triggers the migration.

A failed pre-update dump **blocks the update** by default. The CT stays
on its current working image and cron retries on the next tick; that is
the cheap failure. Set `MYVITALS_BACKUP_REQUIRED=0` to override for a run.

```bash
# what dumps exist, with the alembic head and app version each expects
ssh root@$PVE_HOST "pct exec $CT_ID -- /opt/myvitals/deploy/backup.sh --list"

# take one by hand (same retention rules)
ssh root@$PVE_HOST "pct exec $CT_ID -- /opt/myvitals/deploy/backup.sh --now"
```

Retention is 3 dumps (`MYVITALS_BACKUP_KEEP`). A real dump of this
database is ~100 MB and takes ~35 s, so the cap costs about 300 MB.
Because the dumps sit on the CT rootfs, the nightly PBS run carries them
off-box too.

### Restoring the database

This procedure is **not** automated and should not be run unattended. A
TimescaleDB restore must be bracketed by `timescaledb_pre_restore()` and
`timescaledb_post_restore()`; skipping them does not fail loudly, it
silently corrupts the hypertable catalog, and you will not find out until
a query returns wrong results.

Restore into a scratch database first and compare row counts. Never
restore straight over the live one — if the dump turns out to be bad you
have then destroyed both copies.

```bash
ssh root@$PVE_HOST "pct exec $CT_ID -- bash"
cd /opt/myvitals
U=$(grep ^POSTGRES_USER= .env | cut -d= -f2)
D=$(grep ^POSTGRES_DB= .env | cut -d= -f2)
DUMP=$(ls -1t /var/backups/myvitals/myvitals-*.dump | head -1)

# 1. scratch database
docker compose exec -T db psql -U $U -d postgres -c "CREATE DATABASE myvitals_restoretest;"
docker compose exec -T db psql -U $U -d myvitals_restoretest -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

# 2. the bracket — this is the step people skip
docker compose exec -T db psql -U $U -d myvitals_restoretest -tAc "SELECT timescaledb_pre_restore();"

# 3. restore
cat $DUMP | docker compose exec -T db pg_restore -U $U -d myvitals_restoretest --no-owner

# 4. close the bracket
docker compose exec -T db psql -U $U -d myvitals_restoretest -tAc "SELECT timescaledb_post_restore();"

# 5. verify before trusting it — counts must match, and all 12
#    hypertables must be present
for t in vitals_heartrate vitals_steps sleep_stages workouts strength_sets; do
  L=$(docker compose exec -T db psql -U $U -d $D -tAc "SELECT count(*) FROM $t;")
  R=$(docker compose exec -T db psql -U $U -d myvitals_restoretest -tAc "SELECT count(*) FROM $t;")
  echo "$t live=$L restored=$R"
done
docker compose exec -T db psql -U $U -d myvitals_restoretest -tAc \
  "SELECT count(*) FROM timescaledb_information.hypertables;"   # expect 12
```

Only once that checks out, promote it. Stop the backend first so nothing
writes during the swap:

```bash
docker compose stop backend
docker compose exec -T db psql -U $U -d postgres -c "ALTER DATABASE $D RENAME TO ${D}_broken;"
docker compose exec -T db psql -U $U -d postgres -c "ALTER DATABASE myvitals_restoretest RENAME TO $D;"
docker compose up -d backend
```

Keep `${D}_broken` until you are satisfied, then drop it. Check the
dump's `.meta` sidecar before restoring — it records the `alembic_head`
the dump expects. Restoring a dump at head `0054` into a backend image
that is already at `0061` means the backend will run those seven
migrations against restored data on its next start, which may or may not
be what you want.

The DB volume (`myvitals_db_data`) lives in the container's LVM-thin pool.

## MCP server (read-only)

`POST /mcp` publishes the aggregates this app already computes as MCP
tools, so your own Claude subscription can read your health data without
every question billing the app's Anthropic key.

It is **read-only by construction** — there is no write path, and
`test_mcp_server.py` fails if a tool name so much as looks like a
mutation. Authentication reuses the existing `QUERY_TOKEN` rather than
introducing a second secret to generate, store and rotate.

Add to your Claude client's MCP config:

```json
{
  "mcpServers": {
    "myvitals": {
      "type": "http",
      "url": "http://<myvitals-host>:8000/mcp",
      "headers": { "Authorization": "Bearer <QUERY_TOKEN>" }
    }
  }
}
```

Tools: `get_daily_summary`, `compare_periods`, `get_sleep`,
`get_activities`, `get_strength_sessions`, `get_consistency`,
`get_muscle_volume`, `get_goals`.

Protocol notes:

- Speaks the current revision (`2026-07-28`) and the older handshake era
  (`2025-11-25` and earlier), so it works with clients that have not yet
  shipped the new one.
- Request/response only. No SSE, no sessions, no resumable streams —
  `2026-07-28` removed the mechanisms that needed them, and nothing here
  changes, so there is nothing to subscribe to. GET and DELETE return 405
  as the spec directs.
- Activity titles are deliberately not exposed: Strava names routinely
  embed home and workplace addresses.

## Common gotchas

- **Never `docker compose build` on the CT from a partially synced tree.**
  Syncing only `backend/src` leaves `backend/alembic` stale or absent, and
  the container then dies on start with `Can't locate revision identified
  by 'NNNN'` — taking the backend down until an image is pulled back. Deploy
  by pushing a `v*` tag and letting `auto-update.sh` pull the built image;
  that path also takes a pre-migration dump first. To recover from a broken
  local build: `docker compose pull backend && docker compose up -d
  --force-recreate backend`.
- **Docker won't start a container** — runc 1.1.x swap may have regressed (e.g. after `apt upgrade`). Re-run the relevant block from `deploy/ct-bootstrap.sh` (the `if grep container=lxc /proc/1/environ` branch) or just `apt-get install --reinstall runc && cp /usr/sbin/runc /usr/bin/runc && systemctl restart docker`.
- **Frontend can't auth** — `QUERY_TOKEN` not set in dashboard `localStorage`. Open `/settings` and paste the value from `/opt/myvitals/.env`.
- **`/version` shows old number after upgrade** — `pyproject.toml` `version` wasn't bumped along with the tag. Cosmetic; harmless.
- **Sync from phone "does nothing"** — first suspect is cleartext HTTP being blocked (Android 9+). The app's `network_security_config.xml` permits cleartext globally; if you change that, re-enable for your backend host.

## Phone app

| Item | Value |
|------|-------|
| Package | `app.myvitals` |
| Launcher | "myvitals" |
| Min SDK | 28 (Android 9) |
| Target SDK | 35 |
| Update source | GitHub Releases — `Pr0zak/myvitals` (hardcoded in `BuildConfig.GITHUB_REPO`) |
| Local DBs | `myvitals.db` (Room — buffered batches + logs), `myvitals_prefs` (plain), `myvitals_secure` (EncryptedSharedPreferences) |
| Periodic workers | `myvitals_periodic_sync` (15 min), `myvitals_log_upload` (15 min), `myvitals_update_check` (24 h) |
