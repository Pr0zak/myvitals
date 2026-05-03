#!/usr/bin/env bash
# Upgrade myvitals on the Proxmox CT.
#
# Pulls the newest images from GHCR (per BACKEND_TAG / FRONTEND_TAG in .env)
# and restarts containers. Migrations run automatically on backend startup.
#
# Usage:
#   ./upgrade.sh                  # pull + up + verify
#   ./upgrade.sh 0.2.0            # pin to a specific tag (writes BACKEND_TAG/FRONTEND_TAG into .env)
#   ./upgrade.sh --rebuild        # build from local source instead of pulling

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Run deploy/ct-bootstrap.sh first." >&2
    exit 1
fi

REBUILD=0
PIN_TAG=""
for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=1 ;;
        -*) echo "unknown flag: $arg" >&2; exit 2 ;;
        *) PIN_TAG="$arg" ;;
    esac
done

# Ensure latest deploy code (compose file, migrations).
git fetch --tags
git pull --ff-only

if [ -n "$PIN_TAG" ]; then
    echo ">>> Pinning to tag $PIN_TAG"
    sed -i "s/^BACKEND_TAG=.*/BACKEND_TAG=$PIN_TAG/" .env
    sed -i "s/^FRONTEND_TAG=.*/FRONTEND_TAG=$PIN_TAG/" .env
fi

PREV_VERSION=$(curl -fsS http://127.0.0.1:8000/version 2>/dev/null | grep -oE '"version":"[^"]*"' || echo "(none)")

if [ "$REBUILD" = "1" ]; then
    echo ">>> Building images locally"
    docker compose build --pull
else
    echo ">>> Pulling images from GHCR"
    docker compose pull
fi

echo ">>> Restarting services"
docker compose up -d

echo ">>> Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
    if [ "$i" = "30" ]; then
        echo "ERROR: backend did not become healthy in 60s" >&2
        docker compose logs --tail=50 backend
        exit 1
    fi
done

NEW_VERSION=$(curl -fsS http://127.0.0.1:8000/version)

echo
echo "=== Upgrade complete ==="
echo "Previous: $PREV_VERSION"
echo "Now:      $NEW_VERSION"

# Prune images older than 7 days to reclaim space (keeps the previous tag for rollback).
docker image prune -af --filter "until=168h" >/dev/null 2>&1 || true
