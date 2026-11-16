# Deploy mls-backend to GCP — single-VM path

**Target capacity: 100 concurrent users on a single VM + Cloud SQL.**

**Stack:** one `e2-medium` VM (2 vCPU burst, 4 GB RAM) running Docker Compose:
backend (4 gunicorn workers × 4 threads = 16 concurrent slots) + Celery worker
+ Celery beat + Redis + Caddy (TLS) + Cloud SQL Auth Proxy.
Database is **Cloud SQL Postgres** (managed, `db-g1-small` Enterprise).
Media goes to GCS (set up in [ENV_GCP_GUIDE.md](ENV_GCP_GUIDE.md)).

**Flow:** `docker build` → push to Artifact Registry → VM pulls → `docker compose up -d`.

**Expected monthly cost: ~$42 – $48.**

> If you want scale-to-zero / managed instead of cheapest, see the Cloud Run
> variant at the bottom of this file.

---

## Architecture

```
                        api.yourdomain.com
                              │ (443/80)
                      ┌───────▼────────┐
                      │  Caddy (TLS)   │
                      └───────┬────────┘
                              │ reverse_proxy
                      ┌───────▼────────┐    ┌─────────────┐
                      │  backend       │◄──►│ redis       │
                      │  (gunicorn)    │    └─────────────┘
                      └───┬────────┬───┘
                          │        │
              ┌───────────┘        └──────────┐
              ▼                               ▼
    ┌──────────────────┐          ┌────────────────────┐
    │ cloudsql-proxy   │─TLS/IAM──►│   Cloud SQL        │
    │ (sidecar)        │          │   Postgres (mgd)   │
    └──────────────────┘          └────────────────────┘
                          ▼
                 ┌───────────────┐
                 │  GCS bucket   │  (media)
                 └───────────────┘

              ┌──────────────┐   ┌──────────────┐
              │ celery worker│   │  celery beat │
              └──────────────┘   └──────────────┘
```

All services except Caddy stay inside the docker network. Only ports 22/80/443
are exposed on the VM.

---

## Step 0 — config

```powershell
$PROJECT_ID = "mls-backend-prod"
$REGION     = "us-central1"
$ZONE       = "us-central1-a"
$REPO       = "mls"
$IMAGE_NAME = "mls-backend"
$VM_NAME    = "mls-vm"
$MACHINE    = "e2-medium"            # 2 vCPU, 4 GB — sized for ~100 concurrent users
$IMAGE      = "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE_NAME:latest"

gcloud config set project $PROJECT_ID
```

---

## Step 1 — enable APIs + create registry

```powershell
gcloud services enable `
    artifactregistry.googleapis.com `
    compute.googleapis.com `
    storage.googleapis.com `
    iam.googleapis.com

gcloud artifacts repositories create $REPO `
    --repository-format=docker `
    --location=$REGION
```

---

## Step 2 — create a least-privilege service account for the VM

Attaching a dedicated SA lets the VM pull images and write to GCS without
JSON key files.

```powershell
$SA_NAME  = "mls-vm-sa"
$SA_EMAIL = "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create $SA_NAME `
    --display-name="mls-backend VM runtime"

gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/artifactregistry.reader"

# GCS media bucket access — see ENV_GCP_GUIDE.md step 1 for the bucket itself.
$BUCKET = "mls-media-$PROJECT_ID"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/storage.objectAdmin"

# Cloud SQL: let the VM's SA open an authenticated proxy connection.
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SA_EMAIL" `
    --role="roles/cloudsql.client"
```

---

## Step 3 — provision Cloud SQL (managed Postgres)

```powershell
gcloud services enable sqladmin.googleapis.com

$INSTANCE = "mls-db"
$DB_NAME  = "mls"
$DB_USER  = "mls_app"

# db-g1-small Enterprise edition: 1.7 GB RAM, 1 shared vCPU, zonal (no HA).
# Comfortable for 100 concurrent users with careful tuning. Upgrade to
# db-custom-1-3840 (1 vCPU / 3.75 GB, ~$30/mo) if you see sustained >70% CPU
# or page cache pressure.
gcloud sql instances create $INSTANCE `
    --database-version=POSTGRES_16 `
    --tier=db-g1-small `
    --edition=ENTERPRISE `
    --region=$REGION `
    --storage-size=10 `
    --storage-type=SSD `
    --storage-auto-increase `
    --availability-type=ZONAL `
    --backup `
    --backup-start-time=06:00 `
    --retained-backups-count=7 `
    --database-flags=max_connections=60,shared_buffers=131072,work_mem=8192,maintenance_work_mem=131072

gcloud sql databases create $DB_NAME --instance=$INSTANCE

# App DB user (the password lands in DATABASE_URL in .env.prod).
$DB_PASSWORD = python -c "import secrets; print(secrets.token_urlsafe(24))"
gcloud sql users create $DB_USER --instance=$INSTANCE --password=$DB_PASSWORD

# Values you need for .env.prod:
$CONNECTION_NAME = "$PROJECT_ID`:$REGION`:$INSTANCE"
Write-Host "CLOUD_SQL_INSTANCE = $CONNECTION_NAME"
Write-Host "DATABASE_URL       = postgres://${DB_USER}:${DB_PASSWORD}@cloudsql-proxy:5432/${DB_NAME}"
```

Paste both values into `.env.prod`.

> The `cloudsql-proxy` sidecar in [docker-compose.prod.yml](docker-compose.prod.yml)
> handles the tunnel + IAM auth. No public IP, no authorized-networks list, no
> DB password in any secret store beyond `.env.prod` on the VM.

### Flags explained

| Flag                       | Why                                                      |
|----------------------------|----------------------------------------------------------|
| `max_connections=60`       | 16 gunicorn + 2 worker + 1 beat + headroom (`CONN_MAX_AGE=600` reuses). |
| `shared_buffers=131072`    | 1 GB (units = 8 KB pages). ~60% of 1.7 GB RAM.           |
| `work_mem=8192`            | 8 MB per sort/hash op — enough for listing queries.      |
| `maintenance_work_mem=131072` | 1 GB — speeds up VACUUM and index builds.              |
| `--retained-backups-count=7` | Keep a week of automated backups.                      |
| `--availability-type=ZONAL`  | No HA — cuts cost in half. Add `REGIONAL` ($30+ extra) if uptime matters. |

---

## Step 4 — create the VM

```powershell
# e2-medium: 2 vCPU burst, 4 GB RAM. Not in free tier but handles 100 concurrent.
# 20 GB boot disk gives room for Postgres data + Docker image layers.
gcloud compute instances create $VM_NAME `
    --zone=$ZONE `
    --machine-type=$MACHINE `
    --image-family=debian-12 `
    --image-project=debian-cloud `
    --boot-disk-size=20GB `
    --boot-disk-type=pd-balanced `
    --service-account=$SA_EMAIL `
    --scopes=cloud-platform `
    --tags=http-server,https-server `
    --metadata=enable-oslogin=TRUE

# Open 80/443 (SSH is already allowed via the default-allow-ssh rule).
gcloud compute firewall-rules create allow-http-https `
    --allow=tcp:80,tcp:443 `
    --target-tags=http-server,https-server `
    --source-ranges=0.0.0.0/0
```

Grab the public IP:

```powershell
gcloud compute instances describe $VM_NAME --zone=$ZONE `
    --format="value(networkInterfaces[0].accessConfigs[0].natIP)"
```

Point your DNS `api.yourdomain.com` A record at that IP. Caddy can't get a cert
until DNS resolves.

---

## Step 5 — build & push the image

From your laptop (no Cloud Build charge):

```powershell
docker build --platform=linux/amd64 -t $IMAGE .
docker push $IMAGE
```

---

## Step 6 — SSH into the VM and bootstrap it

```powershell
gcloud compute ssh $VM_NAME --zone=$ZONE
```

Inside the VM:

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/<you>/mls-backend/main/deploy/bootstrap-vm.sh)"
```

If you don't want to curl from GitHub, just `scp` the bootstrap script up:

```powershell
gcloud compute scp deploy/bootstrap-vm.sh ${VM_NAME}:/tmp/ --zone=$ZONE
gcloud compute ssh $VM_NAME --zone=$ZONE --command="sudo bash /tmp/bootstrap-vm.sh"
```

The script installs Docker + Compose and configures Artifact Registry auth via
the VM's attached service account.

---

## Step 7 — copy app files + env to the VM

```powershell
# From your laptop, in the repo root:
gcloud compute scp docker-compose.prod.yml ${VM_NAME}:/tmp/ --zone=$ZONE
gcloud compute scp .env.prod               ${VM_NAME}:/tmp/ --zone=$ZONE
gcloud compute scp deploy\Caddyfile        ${VM_NAME}:/tmp/ --zone=$ZONE

gcloud compute ssh $VM_NAME --zone=$ZONE --command=@'
sudo mkdir -p /opt/mls-backend/deploy
sudo mv /tmp/docker-compose.prod.yml /opt/mls-backend/
sudo mv /tmp/.env.prod               /opt/mls-backend/
sudo mv /tmp/Caddyfile                /opt/mls-backend/deploy/
sudo chmod 600 /opt/mls-backend/.env.prod
'@
```

---

## Step 8 — bring up the stack

SSH into the VM one more time:

```bash
cd /opt/mls-backend

# Required env vars (the compose file reads these).
export IMAGE="us-central1-docker.pkg.dev/<PROJECT>/mls/mls-backend:latest"
export DOMAIN="api.yourdomain.com"
export ADMIN_EMAIL="you@yourdomain.com"

sudo -E docker compose -f docker-compose.prod.yml pull
sudo -E docker compose -f docker-compose.prod.yml up -d

# First-run migrations.
sudo -E docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
sudo -E docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

To persist those exports across reboots, put them in `/etc/environment`:

```bash
sudo tee -a /etc/environment <<EOF
IMAGE=us-central1-docker.pkg.dev/<PROJECT>/mls/mls-backend:latest
DOMAIN=api.yourdomain.com
ADMIN_EMAIL=you@yourdomain.com
EOF
```

---

## Step 9 — smoke test

```powershell
curl https://api.yourdomain.com/health/
curl https://api.yourdomain.com/health/ready/
```

`health/ready/` returning `{"status":"ok","database":"ok"}` means Postgres is
reachable. Caddy's first run takes ~30s while it fetches the TLS cert.

---

## Redeploys

Push a new image from your laptop, then on the VM:

```bash
cd /opt/mls-backend
sudo docker compose -f docker-compose.prod.yml pull backend worker beat
sudo docker compose -f docker-compose.prod.yml up -d backend worker beat
# Run migrations if the diff touched models:
sudo docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
```

Zero downtime isn't realistic on one VM — a brief restart is expected.

---

## Backups

**Database**: Cloud SQL automatic backups are already on (configured at
instance create with `--backup --retained-backups-count=7`). Restore from the
Cloud Console → SQL → your instance → Backups tab.

**On-demand snapshot** before a risky migration:

```powershell
gcloud sql backups create --instance=$INSTANCE --description="pre-migration"
```

**Point-in-time recovery** (PITR): enable write-ahead-log archiving once you
have real data:

```powershell
gcloud sql instances patch $INSTANCE --enable-point-in-time-recovery
```

**VM** (code, Redis state, Caddy certs): weekly disk snapshot is enough since
all mutable data lives in Cloud SQL and GCS now.

```powershell
gcloud compute resource-policies create snapshot-schedule mls-weekly `
    --region=$REGION `
    --max-retention-days=28 `
    --start-time=06:00 `
    --weekly-schedule --weekly-schedule-from-file=weekly.yaml

gcloud compute disks add-resource-policies ${VM_NAME} `
    --zone=$ZONE `
    --resource-policies=mls-weekly
```

---

## Logs & ops

```bash
# live logs for all services
sudo docker compose -f docker-compose.prod.yml logs -f

# just the backend
sudo docker compose -f docker-compose.prod.yml logs -f backend

# disk usage (keep an eye on postgres-data volume)
sudo docker system df
```

Cloud Logging agent is **not** installed in this setup — docker handles logs.
If you want logs in Cloud Logging, `gcloud compute instances add-metadata`
with `google-logging-enabled=true` + install the Ops Agent (adds ~50MB RAM).

---

## Capacity & sizing

### Target: 100 concurrent users

A "concurrent user" here = a browser session actively using the app (not a
request in flight). Assuming each session makes ~1 request every 5 s with
average 100 ms backend latency, 100 users ≈ **20 req/sec sustained**, **~5 avg
in-flight** requests, peaks around **20-40 in-flight**.

The compose stack is sized to absorb that:

| Component     | Resource budget            | Why it fits                                               |
|---------------|----------------------------|-----------------------------------------------------------|
| gunicorn      | 4 workers × 4 threads = 16 | Handles bursts up to 16 concurrent HTTP requests.         |
| Cloud SQL     | db-g1-small (1.7 GB, shared vCPU), max_connections=60 | `CONN_MAX_AGE=600` keeps ~16 conns open, plenty of headroom. |
| Redis         | 256 MB, allkeys-lru        | Cache + Celery broker. 100 users is negligible load.      |
| Celery worker | 2 concurrency              | Background only (emails, alerts) — not in the request path. |
| cloudsql-proxy | ~50 MB                    | Tunnels backend ↔ Cloud SQL with VM-SA auth.              |
| **VM total**  | **e2-medium: 2 vCPU, 4 GB** | Working set ~1.9 GB (DB offloaded), 2.1 GB headroom.     |

### VM sizing cheat-sheet (DB offloaded to Cloud SQL)

| VM             | RAM  | vCPU         | Cost/mo | Verdict                                                           |
|----------------|------|--------------|---------|--------------------------------------------------------------------|
| e2-micro       | 1 GB | 2 (shared, bursty) | $0 (free) | ❌ Still tight once Redis + Django + Celery + Caddy stack up. |
| **e2-small**   | **2 GB** | **2 (shared, 50%)**| **~$13** | ✅ Workable for 100 users with `WEB_CONCURRENCY=2` (8 slots). |
| e2-medium      | 4 GB | 2 (shared, 100%)    | ~$25     | ✅ **Our default — 4 workers, bursts comfortably to 100+.**   |
| e2-standard-2  | 8 GB | 2 (dedicated)      | ~$50     | ✅ Dedicated CPU. Needed if latency is spiky under load.      |
| e2-standard-4  | 16 GB | 4 (dedicated)     | ~$100    | For 300+ concurrent users or hot CPU paths (image resize etc). |

### Cloud SQL sizing cheat-sheet

| Tier                    | RAM    | vCPU       | Cost/mo | Verdict for 100 users                      |
|-------------------------|--------|------------|---------|---------------------------------------------|
| db-f1-micro Enterprise  | 0.6 GB | shared     | ~$8     | ⚠ OK for staging, tight for prod.           |
| **db-g1-small Enterprise** | **1.7 GB** | **shared** | **~$17** | ✅ **Our default — handles 100 concurrent.** |
| db-custom-1-3840 Enterprise | 3.75 GB | 1 dedicated | ~$30 | ✅ Comfortable; upgrade target if CPU bound. |
| db-custom-2-7680 Enterprise | 7.5 GB  | 2 dedicated | ~$55 | For 300+ users or complex analytics.        |

Add storage (~$0.17/GB SSD/mo) and backups (~$0.09/GB/mo) on top. 10 GB SSD
+ 7 daily backups ≈ ~$2/mo extra.

### How to downsize or upsize

Edit `.env.prod`:
```env
WEB_CONCURRENCY=4          # (2*vCPU)+1 — keep in step with machine size
WEB_THREADS=4              # 4 is a good default for IO-bound Django
CELERY_CONCURRENCY=2
```

Then resize the VM in place (requires brief stop):
```powershell
gcloud compute instances stop $VM_NAME --zone=$ZONE
gcloud compute instances set-machine-type $VM_NAME --zone=$ZONE --machine-type=e2-standard-2
gcloud compute instances start $VM_NAME --zone=$ZONE
```

Then on the VM: `sudo -E docker compose -f docker-compose.prod.yml up -d --force-recreate backend`.

### When to split out services (grow beyond one VM)

Postgres is already on Cloud SQL (managed). Next moves as traffic grows:

1. **Redis → Memorystore Basic 1 GB** (~$35/mo) — once Redis contention shows.
2. **Backend → Managed Instance Group** + **Cloud Load Balancing** — horizontal
   scale, zero-downtime deploys.
3. **Celery → its own VM / Cloud Run Job** — isolate background work from request path.
4. **Cloud SQL → `db-custom-1-3840` or HA (REGIONAL)** — DB CPU or SLA pressure.

### Risks & mitigations

| Risk                          | Mitigation                                                     |
|-------------------------------|----------------------------------------------------------------|
| OOM under traffic spike       | Monitor `docker stats`. Add swap if needed, or resize to e2-standard-2. |
| Boot disk fills with docker logs/images  | `docker system prune`, resize disk live: `gcloud compute disks resize`. |
| Egress from GCS media         | Front with Cloud CDN if hot; cheap caching tier.               |
| Single VM = brief downtime on reboot | DB/media are off the VM. Restart is <1min; use MIG + LB later if needed. |

### Load test before you declare victory

Numbers above are from capacity planning, not measurement. Validate on your
own routes (which involve DB joins, Cloudinary/GCS fetches, external APIs):

```bash
# From any Linux box (not the VM itself):
docker run --rm -v $PWD:/scripts grafana/k6 run /scripts/loadtest.js
```

A quick [k6](https://k6.io) script hitting your top 5 endpoints at 100 VUs for
3 minutes will catch p99 latency issues before users do.

---

## Alternative: Cloud Run (scale-to-zero, no VM)

If you'd rather use managed serverless, skip this file and follow the
Cloud Run commands in [ENV_GCP_GUIDE.md](ENV_GCP_GUIDE.md) step 5. That path
removes the need for Caddy and the VM at the cost of (a) no Celery worker,
(b) ~$10/mo for Cloud SQL since Cloud Run can't host its own Postgres.
