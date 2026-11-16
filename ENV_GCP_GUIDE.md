# Prod env for GCP (single-VM path) — fill-in guide

Everything on GCP. Sized for **100 concurrent users**. Target stack:

| Concern         | GCP service                                                 | Est. cost (100 users)   |
|-----------------|-------------------------------------------------------------|-------------------------|
| Compute         | GCE `e2-medium` VM (2 vCPU, 4 GB)                           | **~$25 / mo**           |
| **Database**    | **Cloud SQL `db-g1-small` Postgres Enterprise, zonal**      | **~$17 / mo**           |
| DB storage      | 10 GB SSD + 7 daily backups                                 | ~$2 / mo                |
| Redis           | Redis in docker-compose on the same VM                      | $0                      |
| Celery worker   | docker-compose service on the same VM                       | $0                      |
| TLS             | Caddy in docker-compose (Let's Encrypt)                     | $0                      |
| Image registry  | Artifact Registry                                           | ~$0.05 / mo             |
| Media           | Cloud Storage (GCS) standard bucket                         | ~$0 – $1 / mo           |
| Email           | SendGrid (external; GCP has no email svc)                   | free tier               |
| Boot disk 20 GB | GCE pd-balanced                                             | ~$2 / mo                |

**Total realistic monthly spend: ~$46 – $50.** The honest tradeoffs:
- Cloud SQL instance is **zonal** (no HA) — down during zone outages (~5 min/yr).
  Flip to `--availability-type=REGIONAL` to double cost for HA.
- `e2-medium` and `db-g1-small` are both shared-core. If latency gets spiky
  during sustained bursts, bump the VM to `e2-standard-2` (dedicated, ~$50/mo)
  or the DB to `db-custom-1-3840` (dedicated, ~$30/mo). See cheat-sheets in
  [DEPLOY_GCP.md](DEPLOY_GCP.md).

> See [.env.prod.example](.env.prod.example) for the full template. Copy it to
> `.env.prod` (gitignored). On the VM this file lives at `/opt/mls-backend/.env.prod`.

---

## Step 0 — set shell variables

```powershell
$PROJECT_ID = "mls-backend-prod"
$REGION     = "us-central1"
$ZONE       = "us-central1-a"
$REPO       = "mls"
$IMAGE_NAME = "mls-backend"
$VM_NAME    = "mls-vm"
$BUCKET     = "mls-media-$PROJECT_ID"
gcloud config set project $PROJECT_ID
```

---

## Step 1 — provision Cloud Storage bucket (media)

```powershell
gcloud services enable storage.googleapis.com

gcloud storage buckets create "gs://$BUCKET" `
    --location=$REGION `
    --default-storage-class=STANDARD `
    --uniform-bucket-level-access `
    --public-access-prevention=inherited

# Public-read so listing photos load without signed URLs.
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" `
    --member=allUsers `
    --role=roles/storage.objectViewer
```

CORS (so the SPA can upload direct from the browser) — create `cors.json`:

```json
[
  {
    "origin": ["https://app.vsell4u.ca", "https://*.vercel.app", "http://localhost:3000"],
    "method": ["GET", "HEAD", "PUT", "POST"],
    "responseHeader": ["Content-Type", "Content-MD5", "x-goog-resumable"],
    "maxAgeSeconds": 3600
  }
]
```

```powershell
gcloud storage buckets update "gs://$BUCKET" --cors-file=cors.json
```

Paste `$BUCKET` into `.env.prod` under `GS_BUCKET_NAME=`. Set
`GS_PROJECT_ID=$PROJECT_ID`.

*(The VM's attached service account — created in [DEPLOY_GCP.md](DEPLOY_GCP.md)
step 2 — already gets `storage.objectAdmin` on this bucket, so Django's GCS
backend auths via the metadata server. No JSON key file needed.)*

---

## Step 2 — Django SECRET_KEY + Cloud SQL values

```powershell
# Django secret key (paste into SECRET_KEY)
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

The DB user password + `CLOUD_SQL_INSTANCE` come out of
[DEPLOY_GCP.md](DEPLOY_GCP.md) step 3 (the `gcloud sql instances create …`
block prints them). Paste both into `.env.prod`:

```env
SECRET_KEY=<the 64-char value>

CLOUD_SQL_INSTANCE=mls-backend-prod:us-central1:mls-db
DATABASE_URL=postgres://mls_app:<DB_PASSWORD>@cloudsql-proxy:5432/mls
```

`@cloudsql-proxy:5432` is the hostname of the Auth Proxy sidecar — do **not**
replace it with the Cloud SQL IP. The proxy handles auth through the VM's
service account (no public DB endpoint, no authorized-networks list).

---

## Step 3 — fill third-party keys

Open each account and paste the value into `.env.prod`:

| Section in template | Where to get it                                                   |
|---------------------|-------------------------------------------------------------------|
| GCS bucket (media)  | Created in step 1 — no API key; the VM SA has access.             |
| CREA DDF            | Your DDF developer account.                                       |
| AMPRE / TRREB       | AMPRE OData portal.                                               |
| SendGrid            | Settings → API Keys → Create API Key (Mail Send only).            |
| Google OAuth        | GCP Console → APIs & Services → Credentials → OAuth 2.0 Client.   |
| Facebook OAuth      | Meta for Developers → App → Settings → Basic.                     |
| Twilio Verify       | Twilio Console → Verify → Service SID + account SID/auth token.   |
| GoHighLevel         | GHL Settings → Integrations → API Key.                            |
| OpenAI / Gemini     | platform.openai.com → API keys  **or** aistudio.google.com.       |

Leave blank anything you don't use yet — the code guards every integration.

---

## Step 4 — ship the file to the VM

```powershell
gcloud compute scp .env.prod ${VM_NAME}:/tmp/ --zone=$ZONE

gcloud compute ssh $VM_NAME --zone=$ZONE --command=@'
sudo mv /tmp/.env.prod /opt/mls-backend/.env.prod
sudo chmod 600 /opt/mls-backend/.env.prod
sudo chown root:root /opt/mls-backend/.env.prod
'@
```

> The file sits on the VM's encrypted boot disk. No Secret Manager needed for
> this stack — the VM is the trust boundary.

---

## Step 5 — bring up the stack + migrate

On the VM (see [DEPLOY_GCP.md](DEPLOY_GCP.md) steps 5-7 for how to get there):

```bash
cd /opt/mls-backend
sudo -E docker compose -f docker-compose.prod.yml pull
sudo -E docker compose -f docker-compose.prod.yml up -d
sudo -E docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
sudo -E docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

---

## Step 6 — smoke test

```powershell
curl https://api.vsell4u.ca/health/
curl https://api.vsell4u.ca/health/ready/
```

`health/ready/` returning `{"status":"ok","database":"ok"}` means the compose
network is healthy end-to-end. Caddy's first startup takes ~30 s to fetch a
Let's Encrypt cert.

---

## Rotating a secret later

```powershell
# 1. Edit .env.prod locally with the new value.
# 2. Ship the new file:
gcloud compute scp .env.prod ${VM_NAME}:/tmp/ --zone=$ZONE
gcloud compute ssh $VM_NAME --zone=$ZONE --command=@'
sudo mv /tmp/.env.prod /opt/mls-backend/.env.prod
sudo chmod 600 /opt/mls-backend/.env.prod
cd /opt/mls-backend
sudo -E docker compose -f docker-compose.prod.yml up -d --force-recreate backend worker beat
'@
```

---

## Fill-in checklist

- [ ] `DOMAIN` + `ADMIN_EMAIL` + `IMAGE` (section 0)
- [ ] `SECRET_KEY` (step 2)
- [ ] `CLOUD_SQL_INSTANCE` + matching `DATABASE_URL` (step 2, printed by DEPLOY_GCP.md step 3)
- [ ] `DJANGO_ALLOWED_HOSTS` includes your `$DOMAIN`
- [ ] `PUBLIC_BACKEND_URL` (e.g. `https://api.vsell4u.ca`)
- [ ] `FRONTEND_URL` (where the SPA lives)
- [ ] `GS_BUCKET_NAME` + `GS_PROJECT_ID` (step 1)
- [ ] `DDF_CLIENT_ID` + `DDF_CLIENT_SECRET`
- [ ] `AMPRE_ODATA_BEARER_TOKEN`
- [ ] `SENDGRID_API_KEY` (or SMTP equivalents)
- [ ] `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (if Google login used)
- [ ] `FACEBOOK_APP_ID` + `FACEBOOK_APP_SECRET` (if Facebook login used)
- [ ] `TWILIO_*` trio (if phone OTP used)
- [ ] `GHL_*` trio (if GHL CRM used)
- [ ] `OPENAI_API_KEY` or `GEMINI_API_KEY` (if AI features used)
- [ ] Enable the Celery beat tasks you want (`*_BEAT_ENABLED=1`) — safe to
      leave at `0` until features are ready.
