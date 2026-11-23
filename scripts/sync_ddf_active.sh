#!/usr/bin/env bash
# sync_ddf_active.sh — synchronous DDF full sync for Active properties only.
#
# DDF upstream (CREA) is an Active-only feed, so --full = all Active listings.
# This script:
#   1. Checks the compose stack is up and there is no stale sync container.
#   2. Snapshots current Active / Total DDF row counts.
#   3. Launches `sync_ddf_properties --full` in a detached container.
#   4. Blocks until the container exits, printing milestone log lines live.
#   5. Snapshots final counts and reports the delta.
#   6. Optionally deletes any DDF rows that aren't standard_status=Active
#      (--cleanup). Run this only after a successful sync.
#
# Usage:
#   sudo bash scripts/sync_ddf_active.sh                 # sync, keep inactive residue
#   sudo bash scripts/sync_ddf_active.sh --cleanup       # sync, then delete non-Active rows
#   sudo bash scripts/sync_ddf_active.sh --priority      # tier-by-tier commits
#   sudo bash scripts/sync_ddf_active.sh --priority --cleanup
#   sudo bash scripts/sync_ddf_active.sh --help
#
# Logs: every run also writes a full log to /var/log/ddf-sync-<timestamp>.log

set -euo pipefail

COMPOSE_FILE="/opt/mls-backend/docker-compose.prod.yml"
CONTAINER_NAME="ddf-full-sync"
BATCH_SIZE=8000
MAX_STORAGE_MB=16000
POLL_INTERVAL=15      # seconds between progress polls
LOG_FILE="/var/log/ddf-sync-$(date +%Y%m%d-%H%M%S).log"

CLEANUP=false
PRIORITY=false

# ---------- helpers ----------
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
    C_CYN=$'\033[36m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
    C_RED=''; C_GRN=''; C_YLW=''; C_CYN=''; C_DIM=''; C_RST=''
fi

log()   { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }
step()  { log "${C_CYN}==>${C_RST} $*"; }
ok()    { log "${C_GRN}OK  ${C_RST} $*"; }
warn()  { log "${C_YLW}WARN${C_RST} $*"; }
fail()  { log "${C_RED}FAIL${C_RST} $*"; }

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \?//'
    exit 0
}

# ---------- Django ORM helper (clean output, no shell noise) ----------
# Runs a short Python snippet inside the backend container with Django set up.
# Echoes only whatever the snippet prints — no "N objects imported" banner.
py_in_backend() {
    docker compose -f "$COMPOSE_FILE" exec -T backend python -c "$1" 2>/dev/null
}

count_active_ddf() {
    py_in_backend "
import django; django.setup()
from mls.models import Property
print(Property.objects.filter(category_type=Property.DDF, standard_status__iexact='Active').count())
"
}

count_total_ddf() {
    py_in_backend "
import django; django.setup()
from mls.models import Property
print(Property.objects.filter(category_type=Property.DDF).count())
"
}

breakdown_ddf() {
    py_in_backend "
import django; django.setup()
from mls.models import Property
from django.db.models import Count
rows = (Property.objects.filter(category_type=Property.DDF)
        .values('standard_status').annotate(n=Count('*')).order_by('-n'))
for r in rows: print(f\"  {(r['standard_status'] or 'NULL'):20s} : {r['n']:>8,}\")
"
}

delete_non_active_ddf() {
    py_in_backend "
import django; django.setup()
from mls.models import Property
n, _ = Property.objects.filter(category_type=Property.DDF).exclude(standard_status__iexact='Active').delete()
print(n)
"
}

# ---------- parse args ----------
for arg in "$@"; do
    case "$arg" in
        --cleanup)  CLEANUP=true ;;
        --priority) PRIORITY=true ;;
        -h|--help)  usage ;;
        *) fail "Unknown option: $arg"; exit 1 ;;
    esac
done

# ---------- 1. pre-flight ----------
step "Pre-flight check"

if [ ! -f "$COMPOSE_FILE" ]; then
    fail "Compose file not found at $COMPOSE_FILE"
    exit 1
fi

if ! docker compose -f "$COMPOSE_FILE" ps backend 2>/dev/null \
        | awk 'NR>1 && $0 ~ /Up/ {found=1} END {exit !found}'; then
    fail "backend service is not Up. Start the stack first:"
    log "    sudo docker compose -f $COMPOSE_FILE up -d"
    exit 1
fi
ok "compose stack is up"

if docker ps -a --filter "name=^${CONTAINER_NAME}\$" --format '{{.Names}}' \
        | grep -q "^${CONTAINER_NAME}\$"; then
    warn "removing stale $CONTAINER_NAME container"
    docker rm -f "$CONTAINER_NAME" >/dev/null
fi

# ---------- 2. snapshot before ----------
step "DB state BEFORE sync"
BEFORE_ACTIVE=$(count_active_ddf)
BEFORE_TOTAL=$(count_total_ddf)
log "  Active DDF rows : ${BEFORE_ACTIVE}"
log "  Total  DDF rows : ${BEFORE_TOTAL}"
log "  breakdown:"
breakdown_ddf | tee -a "$LOG_FILE"

# ---------- 3. launch detached container ----------
CMD=(python manage.py sync_ddf_properties --full
     --batch-size "$BATCH_SIZE" --max-storage-mb "$MAX_STORAGE_MB")
if $PRIORITY; then
    CMD+=(--priority-cache)
    step "Launching sync in priority-cache mode (GTA tier first, incremental commits)"
else
    step "Launching sync in full-catalogue mode (single bulk upsert at the end)"
fi
log "  command: ${CMD[*]}"

docker compose -f "$COMPOSE_FILE" run -d --name "$CONTAINER_NAME" backend "${CMD[@]}" >/dev/null
ok "container started: $CONTAINER_NAME"

# ---------- 4. block until exit, stream milestones ----------
step "Waiting for sync to finish (polling every ${POLL_INTERVAL}s — safe to Ctrl+C the poll; container keeps running)"
START_TS=$(date +%s)
LAST_LINE=""

while true; do
    STATUS=$(docker ps --filter "name=^${CONTAINER_NAME}\$" --format '{{.Status}}' 2>/dev/null || true)
    if [ -z "$STATUS" ]; then
        break   # exited
    fi

    ELAPSED=$(( $(date +%s) - START_TS ))

    # Any new milestone line we haven't echoed yet?
    NEW_LINE=$(docker logs --tail=50 "$CONTAINER_NAME" 2>&1 \
        | grep -E "Downloading|Downloaded [0-9]|Starting bulk upsert|Committed|Marked [0-9]+ stale|Deleted [0-9]+|Pruning|enforce|tier:" \
        | tail -1 || true)
    if [ -n "$NEW_LINE" ] && [ "$NEW_LINE" != "$LAST_LINE" ]; then
        printf '  %s[%3dm%02ds]%s %s\n' "$C_DIM" "$((ELAPSED/60))" "$((ELAPSED%60))" "$C_RST" "$NEW_LINE" \
            | tee -a "$LOG_FILE"
        LAST_LINE="$NEW_LINE"
    fi

    sleep "$POLL_INTERVAL"
done

EXIT_CODE=$(docker inspect --format '{{.State.ExitCode}}' "$CONTAINER_NAME" 2>/dev/null || echo "?")
TOTAL_ELAPSED=$(( $(date +%s) - START_TS ))
MIN=$((TOTAL_ELAPSED / 60)); SEC=$((TOTAL_ELAPSED % 60))

if [ "$EXIT_CODE" = "0" ]; then
    ok "sync finished in ${MIN}m${SEC}s (exit 0)"
else
    fail "sync exited with code $EXIT_CODE after ${MIN}m${SEC}s"
    log "last 40 log lines:"
    docker logs --tail=40 "$CONTAINER_NAME" 2>&1 | tee -a "$LOG_FILE" || true
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    exit "$EXIT_CODE"
fi

# Save full container log before removing it
step "Saving full container log to ${LOG_FILE%.log}-container.log"
docker logs "$CONTAINER_NAME" > "${LOG_FILE%.log}-container.log" 2>&1 || true

# ---------- 5. snapshot after ----------
step "DB state AFTER sync"
AFTER_ACTIVE=$(count_active_ddf)
AFTER_TOTAL=$(count_total_ddf)
DELTA_ACTIVE=$(( AFTER_ACTIVE - BEFORE_ACTIVE ))
DELTA_TOTAL=$(( AFTER_TOTAL  - BEFORE_TOTAL ))
NON_ACTIVE=$(( AFTER_TOTAL   - AFTER_ACTIVE ))

log "  Active DDF rows : ${AFTER_ACTIVE} (delta ${DELTA_ACTIVE:+${DELTA_ACTIVE}}${DELTA_ACTIVE:-0})"
log "  Total  DDF rows : ${AFTER_TOTAL}  (delta ${DELTA_TOTAL:+${DELTA_TOTAL}}${DELTA_TOTAL:-0})"
log "  non-Active rows : ${NON_ACTIVE}"
log "  breakdown:"
breakdown_ddf | tee -a "$LOG_FILE"

# ---------- 6. optional cleanup ----------
if $CLEANUP; then
    if [ "$NON_ACTIVE" -gt 0 ]; then
        step "Deleting ${NON_ACTIVE} non-Active DDF rows (Cancelled/Expired/Closed/Withdrawn/NULL)"
        DELETED=$(delete_non_active_ddf)
        ok "deleted ${DELETED} rows"
        FINAL_ACTIVE=$(count_active_ddf)
        FINAL_TOTAL=$(count_total_ddf)
        log "  final Active DDF: ${FINAL_ACTIVE}"
        log "  final Total  DDF: ${FINAL_TOTAL}"
    else
        ok "no non-Active DDF rows to clean up"
    fi
else
    if [ "$NON_ACTIVE" -gt 0 ]; then
        warn "${NON_ACTIVE} non-Active DDF rows remain. Re-run with --cleanup to delete them."
    fi
fi

# ---------- tidy up ----------
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
ok "done. Full log: $LOG_FILE"
