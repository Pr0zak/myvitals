#!/usr/bin/env bash
# auto-update.sh — pull-based self-update for the myvitals CT (UPDATE-1).
#
# Designed for cron. Silent on no-op (image digests unchanged). Loud only
# when there's an actual update or a failure. Logs every run to
# /var/log/myvitals-auto-update.log so you can grep history.
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
# Suggested cron (every 15 min):
#   */15 * * * * root /opt/myvitals/deploy/auto-update.sh >> /var/log/myvitals-auto-update.log 2>&1
#
# Manual install:
#   sudo cp deploy/myvitals-auto-update.cron /etc/cron.d/myvitals-auto-update
#   sudo systemctl restart cron

set -euo pipefail

LOG_TAG="[$(date -Iseconds)]"
cd "$(dirname "$0")/.." || exit 1

# UPDATE-1 trigger: backend's POST /api/update/apply writes
# /var/lib/myvitals/update-requested. When present, log it and
# clear the flag so a single click doesn't re-fire on the next tick.
TRIGGER_FILE=/var/lib/myvitals/update-requested
if [ -f "$TRIGGER_FILE" ]; then
    echo "$LOG_TAG triggered by UI request"
    rm -f "$TRIGGER_FILE" 2>/dev/null || true
fi

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
    local svc="$1"
    local image
    image=$(docker compose config --images "$svc" 2>/dev/null | head -1)
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

# Stash previous digests for rollback.
cat > "$(dirname "$0")/last-known-good.txt" <<EOF
# Auto-written by auto-update.sh — DO NOT EDIT MANUALLY.
# Use these tags to roll back if a new image breaks startup.
backend=$before_backend
frontend=$before_frontend
EOF

# Recreate.
docker compose up -d --force-recreate backend frontend 2>&1 | tail -3

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
