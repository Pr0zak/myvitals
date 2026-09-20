#!/usr/bin/env bash
# Weekly Docker reclaim for the CT (PRUNE-1).
#
# The CT's ~36 GB rootfs fills up after a handful of image rebuilds —
# unused images and BuildKit cache are the hogs (a full myvitals image
# is ~1.5 GB; the Playwright/Chromium build cache alone runs to tens of
# GB across rebuilds). When the disk hits ~99% the next rebuild dies at
# the Playwright `apt` step with "No space left on device".
#
# Safe by construction:
#   - `docker system prune -af` removes only UNUSED images — the running
#     db / backend / frontend containers keep theirs.
#   - `--volumes` is deliberately NOT passed, so the named TimescaleDB
#     data volume is preserved.
#
# Install on the CT (done by ct-bootstrap.sh):
#   cp deploy/myvitals-docker-prune.cron /etc/cron.d/myvitals-docker-prune
#   chmod 644 /etc/cron.d/myvitals-docker-prune
#   systemctl restart cron
#
# Logs: /var/log/docker-prune.log (truncated each run).
set -uo pipefail
exec >/var/log/docker-prune.log 2>&1
echo "=== docker prune $(date -u +%FT%TZ) ==="
echo "--- before ---"; df -h / | tail -1
docker system prune -af
echo "--- after ---"; df -h / | tail -1
