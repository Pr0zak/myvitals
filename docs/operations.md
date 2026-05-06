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

The DB volume (`myvitals_db_data`) lives in the container's LVM-thin pool. For real backups, schedule a periodic `pg_dump` to a CIFS share or to a Proxmox Backup Server.

## Common gotchas

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
