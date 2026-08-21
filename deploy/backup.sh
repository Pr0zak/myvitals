#!/usr/bin/env bash
# backup.sh — logical database dumps for myvitals (BK-1).
#
# ── Why this exists, and why it is deliberately small ────────────────
#
# Whole-container backup is already solved and is NOT this script's job.
# The Proxmox cluster runs a nightly vzdump of the CT to Proxmox Backup
# Server on a separate physical host, which captures the rootfs including
# the TimescaleDB docker volume. Catastrophic loss — the CT is destroyed,
# the disk dies, the node burns — is covered there, off-box, already.
#
# So this script does not duplicate that. There is no nightly cron here
# on purpose: the CT rootfs is 36 GB and already ~73% full, has had a
# documented disk-pressure incident, and custom-format dumps are
# effectively incompressible and change wholesale every time. Nightly
# dumps would both crowd the rootfs (crossing auto-update.sh's 85%
# reclaim trigger, which would then destroy the deploy rollback window)
# and pile undedupable chunks into PBS every night. That trade is not
# worth it for a backup that PBS is already taking.
#
# What PBS genuinely does NOT cover is this: a schema migration runs
# unattended. The backend image's CMD is
#
#     alembic upgrade head && fastapi run ...
#
# so the moment auto-update.sh recreates the backend container against a
# newly pulled image, migrations apply with nobody watching. The newest
# PBS restore point at that instant can be up to 24 hours old, and
# restoring it means rolling back the entire 36 GB container — every
# sample ingested since 01:00 goes with it.
#
# A dump taken in the seconds before that migration closes exactly that
# window, and nothing else. Hence one mode that matters: --pre-update.
#
# A pleasant side effect of writing dumps under the CT rootfs rather than
# to a docker volume: the next nightly PBS run carries them off-box too,
# so a pre-migration dump ends up with an off-site copy for free.
#
# ── Usage ────────────────────────────────────────────────────────────
#
#   deploy/backup.sh --pre-update    # called by auto-update.sh
#   deploy/backup.sh --now           # manual dump, same retention
#   deploy/backup.sh --list          # show what exists
#
# Restore is NOT automated and must not be. A TimescaleDB restore needs
# timescaledb_pre_restore()/post_restore() bracketing the pg_restore, and
# skipping them silently corrupts the hypertable catalog rather than
# failing loudly. The verified procedure is in docs/operations.md under
# "Restoring the database" — follow it there, with a human reading along.
#
# Environment overrides:
#   MYVITALS_BACKUP_DIR       where dumps live (default /var/backups/myvitals)
#   MYVITALS_BACKUP_KEEP      how many to retain (default 3)
#   MYVITALS_BACKUP_MIN_FREE  MB that must remain free after a dump (default 2048)
#   MYVITALS_BACKUP_REQUIRED  1 (default) = a failed pre-update dump blocks
#                             the update; 0 = warn and update anyway.

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

BACKUP_DIR=${MYVITALS_BACKUP_DIR:-/var/backups/myvitals}
KEEP=${MYVITALS_BACKUP_KEEP:-3}
MIN_FREE_MB=${MYVITALS_BACKUP_MIN_FREE:-2048}
REQUIRED=${MYVITALS_BACKUP_REQUIRED:-1}

LOG_TAG="[$(date -Iseconds)]"
log() { echo "$LOG_TAG $*"; }

# Credentials come from the same .env the compose stack uses, so there is
# exactly one place they are defined.
env_val() {
    local key="$1"
    grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"''
}

PGUSER=$(env_val POSTGRES_USER)
PGDB=$(env_val POSTGRES_DB)

if [ -z "$PGUSER" ] || [ -z "$PGDB" ]; then
    log "ERROR: POSTGRES_USER / POSTGRES_DB not readable from .env"
    exit 1
fi

# ── retention ────────────────────────────────────────────────────────
#
# Prunes oldest-first. Called both before a dump (to make room) and after
# (to enforce the cap), so a tight disk reclaims space before it is
# needed rather than after the write has already failed.
prune_old() {
    local keep="$1" victim
    # shellcheck disable=SC2012  # filenames are ours and timestamp-shaped
    while [ "$(ls -1 "$BACKUP_DIR"/myvitals-*.dump 2>/dev/null | wc -l)" -gt "$keep" ]; do
        victim=$(ls -1t "$BACKUP_DIR"/myvitals-*.dump 2>/dev/null | tail -1)
        [ -z "$victim" ] && break
        rm -f "$victim" "${victim}.meta" 2>/dev/null || true
        log "pruned old dump $(basename "$victim")"
    done
}

free_mb() { df --output=avail -m "$BACKUP_DIR" 2>/dev/null | tail -1 | tr -dc '0-9'; }

# ── the dump itself ──────────────────────────────────────────────────
#
# -Fc (custom format) is what pg_restore needs for the selective restore
# the runbook describes; it is also already zlib-compressed, which is why
# there is no separate gzip step.
#
# Note this streams through `docker compose exec -T` rather than running
# pg_dump on the host: the host has no postgres client, and the version
# inside the db image is guaranteed to match the server.
do_dump() {
    local reason="$1"
    local stamp ts out estimate avail

    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"

    # Make room first if we are already over the cap.
    prune_old "$KEEP"

    # Estimate the dump at 60% of on-disk database size. Time-series
    # float columns compress well, so this is comfortably pessimistic;
    # being wrong in that direction is the safe way to be wrong.
    estimate=$(docker compose exec -T db psql -U "$PGUSER" -d "$PGDB" -tAc \
        "SELECT (pg_database_size(current_database()) / 1048576 * 0.6)::int;" 2>/dev/null \
        | tr -dc '0-9' || true)
    estimate=${estimate:-1024}
    avail=$(free_mb)
    avail=${avail:-0}

    if [ "$avail" -lt $((estimate + MIN_FREE_MB)) ]; then
        log "disk too tight for a dump — ${avail}MB free, need ~$((estimate + MIN_FREE_MB))MB"
        log "  dropping retention to 1 and retrying"
        prune_old 1
        avail=$(free_mb); avail=${avail:-0}
        if [ "$avail" -lt $((estimate + MIN_FREE_MB)) ]; then
            log "ERROR: still only ${avail}MB free — refusing to fill the rootfs"
            return 1
        fi
    fi

    stamp=$(date +%Y%m%dT%H%M%S)
    out="$BACKUP_DIR/myvitals-${stamp}.dump"

    # Dump to a .partial name and rename on success, so an interrupted
    # run can never leave a truncated file that looks restorable.
    if ! docker compose exec -T db pg_dump -U "$PGUSER" -d "$PGDB" -Fc \
            > "${out}.partial" 2>/tmp/myvitals-backup-err.$$; then
        log "ERROR: pg_dump failed — $(tail -2 /tmp/myvitals-backup-err.$$ | tr '\n' ' ')"
        rm -f "${out}.partial" /tmp/myvitals-backup-err.$$
        return 1
    fi
    rm -f /tmp/myvitals-backup-err.$$

    # A custom-format dump always starts with the magic "PGDMP". Checking
    # it catches the case where pg_dump exits 0 but the redirect captured
    # an error page or an empty stream.
    if [ "$(head -c 5 "${out}.partial")" != "PGDMP" ]; then
        log "ERROR: dump does not start with PGDMP header — discarding"
        rm -f "${out}.partial"
        return 1
    fi

    mv "${out}.partial" "$out"

    # Record what this dump can be restored INTO. A dump is only as
    # useful as the schema revision and extension version it expects.
    ts=$(docker compose exec -T db psql -U "$PGUSER" -d "$PGDB" -tAc \
        "SELECT extversion FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null \
        | tr -d '[:space:]' || true)
    cat > "${out}.meta" <<EOF
reason=$reason
taken=$(date -Iseconds)
alembic_head=$(docker compose exec -T backend alembic current 2>/dev/null | tail -1 | tr -d '\r' || echo "unknown")
timescaledb=${ts:-unknown}
app_version=$(curl -fsS http://127.0.0.1:8000/version 2>/dev/null | grep -oE '"version":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
size_bytes=$(stat -c%s "$out" 2>/dev/null || echo 0)
EOF

    log "dump written: $(basename "$out") ($(du -h "$out" | cut -f1), reason=$reason)"
    prune_old "$KEEP"
    return 0
}

case "${1:---now}" in
    --pre-update)
        # Called from auto-update.sh once an image change has been
        # detected but BEFORE the containers are recreated — i.e. before
        # the new image's CMD runs `alembic upgrade head`.
        if do_dump pre-update; then
            exit 0
        fi
        if [ "$REQUIRED" = "1" ]; then
            log "ERROR: pre-update dump failed and MYVITALS_BACKUP_REQUIRED=1"
            log "  refusing to migrate without a fresh restore point."
            log "  the CT stays on its current image; cron retries next tick."
            log "  override for one run with: MYVITALS_BACKUP_REQUIRED=0"
            exit 1
        fi
        log "WARNING: pre-update dump failed but MYVITALS_BACKUP_REQUIRED=0 — continuing"
        exit 0
        ;;
    --now)
        do_dump manual
        ;;
    --list)
        if [ ! -d "$BACKUP_DIR" ]; then
            echo "no backup directory at $BACKUP_DIR"
            exit 0
        fi
        printf '%-34s %8s  %s\n' "DUMP" "SIZE" "REASON / TAKEN"
        for f in $(ls -1t "$BACKUP_DIR"/myvitals-*.dump 2>/dev/null); do
            printf '%-34s %8s  %s\n' \
                "$(basename "$f")" \
                "$(du -h "$f" | cut -f1)" \
                "$(grep -hE '^(reason|taken)=' "${f}.meta" 2>/dev/null | cut -d= -f2- | paste -sd' ' -)"
        done
        ;;
    *)
        echo "usage: $0 [--pre-update|--now|--list]" >&2
        exit 2
        ;;
esac
