#!/usr/bin/env bash
# auto-update.sh — pull-based self-update for the myvitals CT (UPDATE-1).
#
# Designed for cron. Silent on no-op (image digests unchanged). Loud only
# when there's an actual update or a failure. Logs to
# /var/lib/myvitals/auto-update.log — the bind-mounted volume the backend
# container reads for the Settings "last run" display (api/update.py). Do
# NOT point the cron at /var/log/...: it isn't mounted, so the UI would
# show a stale "last run" (this exact drift bit us 2026-07).
#
# Behaviour:
#   1. git pull (so docker-compose.yml + migrations stay current)
#   2. docker compose pull backend frontend
#   3. Compare image digests before/after
#   4. If changed:
#        - record `last-known-good.txt` with the previous digests
#        - docker compose up -d --force-recreate backend frontend
#        - poll /health for up to 60s
#        - on failure, automatic rollback to last-known-good
#   5. Emit a one-line summary
#
# Install (use the canonical cron file — don't hand-write the redirect):
#   sudo cp deploy/myvitals-auto-update.cron /etc/cron.d/myvitals-auto-update
#   sudo chmod 644 /etc/cron.d/myvitals-auto-update
#   sudo systemctl restart cron

set -euo pipefail

LOG_TAG="[$(date -Iseconds)]"
cd "$(dirname "$0")/.." || exit 1

# Heartbeat for the /update/status health check. That endpoint (api/update.py)
# judges cron liveness from the mtime of this log (fresh < 20 min) and shows
# its tail in the Settings UI. But this script is silent on no-op, and an
# append redirect does NOT bump mtime when nothing is written — so a perfectly
# healthy cron reads as "stale/unhealthy" between actual updates. Touch the log
# on every run (all exit paths via trap) so mtime tracks "cron ran", while the
# tail still shows only real events.
#
# THIS PATH MUST STAY IN SYNC in three places, or the UI reads the wrong file:
#   - the cron redirect  (deploy/myvitals-auto-update.cron)
#   - this heartbeat
#   - the backend read   (api/update.py LOG_FILE)
# All three: /var/lib/myvitals/auto-update.log — the bind-mounted volume the
# backend container can see. (2026-07: the installed cron had drifted to
# /var/log/myvitals-auto-update.log, which isn't mounted, so the UI showed a
# stale "last run".)
HEARTBEAT_LOG=/var/lib/myvitals/auto-update.log
trap 'touch "$HEARTBEAT_LOG" 2>/dev/null || true' EXIT

# UPDATE-1 trigger: backend's POST /api/update/apply writes
# /var/lib/myvitals/update-requested. When present, log it and
# clear the flag so a single click doesn't re-fire on the next tick.
TRIGGER_FILE=/var/lib/myvitals/update-requested
if [ -f "$TRIGGER_FILE" ]; then
    echo "$LOG_TAG triggered by UI request"
    rm -f "$TRIGGER_FILE" 2>/dev/null || true
fi

# Disk-pressure safeguard (PRUNE-2). Runs on EVERY tick — before the
# no-op early-exit below — so the CT self-heals within one cron interval
# regardless of whether the weekly Sun-04:00 docker-prune fired. That
# weekly job is wall-clock cron with no anacron catch-up, so it silently
# misses whenever the CT is migrating/down at that instant; meanwhile a
# burst of same-day releases each leaves a <7-day dangling image that the
# post-update `until=168h` prune won't touch. Left unchecked the 36 GB
# rootfs creeps to 99% and the next image pull dies with "no space left
# on device", stranding the backend on its old image (seen 2026-07-28).
#
# When the rootfs crosses the high-water mark, aggressively reclaim all
# unused images + BuildKit cache. Running containers keep their images;
# the TimescaleDB named volume is untouched (no --volumes). Under real
# pressure, free space wins over the 7-day rollback window — the in-run
# health-check rollback still protects the deploy actually in flight.
DISK_HIGH_PCT=${MYVITALS_DISK_HIGH_PCT:-85}
reclaim_if_low_disk() {
    local used after
    used=$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')
    [ -z "$used" ] && return 0
    [ "$used" -lt "$DISK_HIGH_PCT" ] && return 0
    echo "$LOG_TAG disk at ${used}% (>=${DISK_HIGH_PCT}%) — reclaiming docker space"
    docker image prune -af >/dev/null 2>&1 || true
    docker builder prune -af >/dev/null 2>&1 || true
    after=$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')
    echo "$LOG_TAG   reclaim done — disk ${used}% -> ${after:-?}%"
}
reclaim_if_low_disk

# ── ORPHAN-1: recreate-orphan sweep ──────────────────────────────────
# `docker compose up -d --force-recreate` swaps a service by RENAMING the
# live container to "<old-id-prefix>_<name>" and creating a fresh one under
# the real name. If the run dies between those two steps — OOM, disk
# pressure, a compose timeout, the CT being migrated mid-deploy — the
# rename survives and nothing owns the real name cleanly. Every later run
# then aborts with:
#
#   Error response from daemon: Conflict. The container name
#   "/<id>_myvitals-backend-1" is already in use by container "<id>"
#
# and the CT silently sticks on its old image until someone SSHes in
# (2026-08-06).
#
# Runs on EVERY tick, BEFORE the no-op early-exit, so a stranded orphan is
# cleared within one cron interval instead of waiting for the next release.
#
# SAFETY — learned the hard way: a *running* orphan is not garbage. It may
# still be the container actually serving traffic. Force-removing one is
# how a failed update becomes an outage (which is exactly what happened
# when this was cleaned up by hand). So: remove only non-running orphans,
# and merely warn about running ones.
sweep_recreate_orphans() {
    local removed=0 line cid cname cstate
    while read -r cid cname cstate; do
        [ -z "${cid:-}" ] && continue
        case "$cstate" in
            running|restarting|paused)
                echo "$LOG_TAG WARNING: running recreate-orphan $cname ($cstate)"
                echo "$LOG_TAG   left in place — it may still be serving."
                echo "$LOG_TAG   inspect: docker ps -a --filter name=_myvitals-"
                ;;
            *)
                if docker rm -f "$cid" >/dev/null 2>&1; then
                    echo "$LOG_TAG removed stale recreate-orphan $cname ($cstate)"
                    removed=$((removed + 1))
                fi
                ;;
        esac
    done < <(
        docker ps -a --format '{{.ID}} {{.Names}} {{.State}}' 2>/dev/null \
            | grep -E '^[0-9a-f]+ [0-9a-f]{6,}_myvitals-[a-z]+-1 ' || true
    )
    [ "$removed" -gt 0 ] && echo "$LOG_TAG swept $removed stale container(s)"
    return 0
}
sweep_recreate_orphans

# NOTE: the CT's /opt/myvitals is not a git checkout under the current
# bootstrap (deploy uses tar+rsync). So we don't `git pull` here — only
# image pulls, which cover the 99% case. If docker-compose.yml or the
# alembic migrations need updating, run the manual deploy from the dev
# machine first; cron will pick up the new images on the next tick.

digest_running() {
    # Image ID currently bound to the running container for a service.
    # Empty if the service isn't up.
    local svc="$1"
    local cid
    cid=$(docker compose ps --quiet "$svc" 2>/dev/null | head -1)
    [ -z "$cid" ] && return
    docker container inspect --format '{{.Image}}' "$cid" 2>/dev/null
}

digest_local() {
    # Image ID of the local copy of whatever the compose file points
    # at — i.e. what we'd recreate the service against if we
    # restarted right now. Captures the pull result without applying it.
    #
    # NOTE: compose v2's `config --images <svc>` prints the service AND
    # its depends_on images (backend pulls in timescaledb; frontend pulls
    # in backend), so a bare `head -1` grabs the *dependency's* image and
    # the digest never matches the running container — a false "update
    # detected" + needless recreate on every tick. auto-update only ever
    # manages the ghcr myvitals-<svc> images, so filter to this service's
    # own line. (Was head -1; broke when compose was upgraded.)
    local svc="$1"
    local image
    image=$(docker compose config --images "$svc" 2>/dev/null \
        | grep "myvitals-${svc}" | head -1)
    [ -z "$image" ] && return
    docker image inspect --format '{{.Id}}' "$image" 2>/dev/null || true
}

before_backend=$(digest_running backend)
before_frontend=$(digest_running frontend)

docker compose pull backend frontend --quiet 2>/dev/null || true

new_backend=$(digest_local backend)
new_frontend=$(digest_local frontend)

if [ "$new_backend" = "$before_backend" ] && [ "$new_frontend" = "$before_frontend" ]; then
    # No update — silent exit.
    exit 0
fi

echo "$LOG_TAG update detected; recreating services"
echo "$LOG_TAG   backend  $before_backend → $new_backend"
echo "$LOG_TAG   frontend $before_frontend → $new_frontend"

# ── BK-1: pre-migration dump ─────────────────────────────────────────
# The backend image's CMD is `alembic upgrade head && fastapi run`, so
# the recreate below applies schema migrations unattended. Nightly PBS
# snapshots cover the CT, but the newest restore point can be up to 24h
# old at this instant and rolling back to it means reverting the whole
# container — every sample ingested since 01:00 goes with it.
#
# Take a logical dump first. By default a failure here BLOCKS the update:
# the CT stays on its current, working image and cron retries on the next
# tick, which is the cheap failure. Migrating without a fresh restore
# point is the expensive one. Override with MYVITALS_BACKUP_REQUIRED=0.
if [ -x "$(dirname "$0")/backup.sh" ]; then
    if ! "$(dirname "$0")/backup.sh" --pre-update; then
        echo "$LOG_TAG update ABORTED — no pre-migration backup (see above)"
        exit 1
    fi
else
    echo "$LOG_TAG WARNING: deploy/backup.sh missing or not executable"
    echo "$LOG_TAG   migrating without a pre-update dump"
fi

# Stash previous digests for rollback.
cat > "$(dirname "$0")/last-known-good.txt" <<EOF
# Auto-written by auto-update.sh — DO NOT EDIT MANUALLY.
# Use these tags to roll back if a new image breaks startup.
backend=$before_backend
frontend=$before_frontend
EOF

# Recreate.
#
# `| tail -3` makes the pipeline's status tail's, so a compose failure here
# does NOT trip `set -e`. That is deliberate (we want the health probe and
# rollback below to run), but it means a failed swap reaches the probe with
# a half-renamed container still holding the name. Capture the status so
# the log says WHY rather than only that /health never answered.
recreate_rc=0
docker compose up -d --force-recreate backend frontend 2>&1 | tail -3 \
    || recreate_rc=$?
if [ "${PIPESTATUS[0]:-0}" -ne 0 ] || [ "$recreate_rc" -ne 0 ]; then
    echo "$LOG_TAG WARNING: compose up returned non-zero — swap may be partial"
    sweep_recreate_orphans
    echo "$LOG_TAG retrying recreate once after sweep"
    docker compose up -d --force-recreate backend frontend 2>&1 | tail -3 || true
fi

# Health probe — give the backend up to 60s to come up.
healthy=0
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 2
done

if [ "$healthy" = "0" ]; then
    echo "$LOG_TAG backend unhealthy after upgrade — rolling back to $before_backend"
    if [ -n "$before_backend" ]; then
        docker tag "$before_backend" ghcr.io/pr0zak/myvitals-backend:rollback || true
        BACKEND_TAG=rollback docker compose up -d --force-recreate backend 2>&1 | tail -3
    fi
    echo "$LOG_TAG rollback complete; investigate via: docker compose logs --tail=80 backend"
    exit 1
fi

new_version=$(curl -fsS http://127.0.0.1:8000/version 2>/dev/null \
    | grep -oE '"version":"[^"]*"' | cut -d'"' -f4 || echo "?")
echo "$LOG_TAG update succeeded — now running v$new_version"

# Prune images older than 7d to keep the CT lean (last-known-good is
# preserved because the rollback path tags it explicitly).
docker image prune -af --filter "until=168h" >/dev/null 2>&1 || true
