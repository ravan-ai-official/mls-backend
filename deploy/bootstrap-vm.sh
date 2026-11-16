#!/usr/bin/env bash
# One-shot bootstrap for a fresh Debian 12 / Ubuntu 22.04 GCE VM.
# Run as root (or via `sudo bash bootstrap-vm.sh`).
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/bootstrap-vm.sh \
#       | sudo bash
#
# Or scp this file over and run it manually.

set -euo pipefail

# -------- Config -----------------------------------------------------------
: "${REGION:=us-central1}"
: "${REPO:=mls}"
: "${IMAGE_NAME:=mls-backend}"
: "${APP_DIR:=/opt/mls-backend}"

echo "[bootstrap] Updating apt + installing docker..."
apt-get update -y
apt-get install -y ca-certificates curl gnupg lsb-release

# Docker Engine + Compose plugin (official repo).
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

echo "[bootstrap] Configuring docker to auth to Artifact Registry via VM SA..."
# The VM's attached service account has roles/artifactregistry.reader.
# gcloud is pre-installed on GCE Debian/Ubuntu images.
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "[bootstrap] Creating ${APP_DIR}..."
mkdir -p "${APP_DIR}/deploy"

cat <<'NOTE'
========================================================================
Next steps (run as root in ${APP_DIR}):

  1. Copy your .env.prod into ${APP_DIR}/.env.prod
  2. Copy docker-compose.prod.yml into ${APP_DIR}/
  3. Copy deploy/Caddyfile into ${APP_DIR}/deploy/
  4. Export IMAGE (full Artifact Registry path), DOMAIN, ADMIN_EMAIL:

       export IMAGE=${REGION}-docker.pkg.dev/<PROJECT>/${REPO}/${IMAGE_NAME}:latest
       export DOMAIN=api.yourdomain.com
       export ADMIN_EMAIL=you@yourdomain.com

  5. docker compose -f docker-compose.prod.yml pull
  6. docker compose -f docker-compose.prod.yml up -d
  7. docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
  8. Point api.yourdomain.com's DNS A record at this VM's external IP.
========================================================================
NOTE
