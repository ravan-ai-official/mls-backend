#!/usr/bin/env bash
# Launch a detached, one-off DDF full-sync container using the current
# :latest image from Artifact Registry. Does NOT touch the running
# backend / worker / beat containers.
set -euo pipefail

cd /opt/mls-backend

echo "-- 1. Pulling latest backend image --"
sudo docker compose -f docker-compose.prod.yml pull backend | tail -5

echo "-- 2. Cleaning up any prior ddf-full-sync container --"
sudo docker rm -f ddf-full-sync 2>/dev/null || true

echo "-- 3. Launching detached full-sync container --"
sudo docker compose -f docker-compose.prod.yml run -d --rm --name ddf-full-sync backend \
    python manage.py sync_ddf_properties --full --batch-size 8000 --max-storage-mb 16000

echo "-- 4. ddf-full-sync status --"
sudo docker ps --filter name=ddf-full-sync --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

echo
echo "Follow logs with:  sudo docker logs -f ddf-full-sync"
echo "Stop early with:   sudo docker rm -f ddf-full-sync"
