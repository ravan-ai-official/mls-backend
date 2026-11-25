#!/usr/bin/env bash
# One-shot full catalogue sync for DDF (Active) + AMPRE (Closed/De-listed).
# Append-only — never deletes Property rows.
#
# After this completes, enable daily incremental via .env.prod:
#   DDF_SYNC_BEAT_ENABLED=1
#   AMPRE_CLOSED_BEAT_ENABLED=1
# Celery beat then pulls only listings created/updated in the last 24h.
#
# Usage (on the prod VM):
#   sudo bash scripts/run_full_listing_sync.sh
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/mls-backend/docker-compose.prod.yml}"
BATCH_SIZE="${BATCH_SIZE:-10000}"
DDF_NAME="ddf-full-sync"
AMPRE_NAME="ampre-full-sync"

cd "$(dirname "$0")/.." 2>/dev/null || cd /opt/mls-backend

echo "==> Cleaning prior one-off sync containers"
sudo docker rm -f "$DDF_NAME" "$AMPRE_NAME" 2>/dev/null || true

echo "==> 1/2 DDF full catalogue (Active) — batch_size=$BATCH_SIZE"
# --skip-ampre: AMPRE runs as its own full pass next (faster + clearer logs).
sudo docker compose -f "$COMPOSE_FILE" run -d --name "$DDF_NAME" backend \
  python manage.py sync_ddf_properties --full --batch-size "$BATCH_SIZE" --skip-ampre

echo "    follow: sudo docker logs -f $DDF_NAME"
echo "    waiting for DDF container to exit..."
sudo docker wait "$DDF_NAME"
DDF_EXIT=$(sudo docker inspect --format '{{.State.ExitCode}}' "$DDF_NAME")
sudo docker logs --tail=40 "$DDF_NAME" || true
sudo docker rm -f "$DDF_NAME" >/dev/null 2>&1 || true
if [ "$DDF_EXIT" != "0" ]; then
  echo "DDF full sync failed with exit $DDF_EXIT" >&2
  exit "$DDF_EXIT"
fi
echo "    DDF full sync OK"

echo "==> 2/2 AMPRE full catalogue (Closed / De-listed) including media"
sudo docker compose -f "$COMPOSE_FILE" run -d --name "$AMPRE_NAME" backend \
  python manage.py sync_ampre_closed --full

echo "    follow: sudo docker logs -f $AMPRE_NAME"
echo "    waiting for AMPRE container to exit..."
sudo docker wait "$AMPRE_NAME"
AMPRE_EXIT=$(sudo docker inspect --format '{{.State.ExitCode}}' "$AMPRE_NAME")
sudo docker logs --tail=40 "$AMPRE_NAME" || true
sudo docker rm -f "$AMPRE_NAME" >/dev/null 2>&1 || true
if [ "$AMPRE_EXIT" != "0" ]; then
  echo "AMPRE full sync failed with exit $AMPRE_EXIT" >&2
  exit "$AMPRE_EXIT"
fi

echo
echo "Full sync complete (append-only)."
echo "Enable 24h incremental in .env.prod then recreate beat:"
echo "  DDF_SYNC_BEAT_ENABLED=1"
echo "  AMPRE_CLOSED_BEAT_ENABLED=1"
echo "  sudo docker compose -f $COMPOSE_FILE up -d --force-recreate beat worker"
