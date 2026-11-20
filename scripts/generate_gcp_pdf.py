"""Generate GCP_INFRASTRUCTURE.pdf — a reference doc covering every GCP service
this stack uses, how each is secured, and the redeploy procedure.

Run: python scripts/generate_gcp_pdf.py
Output: GCP_INFRASTRUCTURE.pdf in repo root.
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "GCP_INFRASTRUCTURE.pdf"

NAVY = colors.HexColor("#0B3D91")
STEEL = colors.HexColor("#334155")
ACCENT = colors.HexColor("#1E88E5")
MUTED = colors.HexColor("#64748B")
BG_CODE = colors.HexColor("#F1F5F9")
BG_TABLE = colors.HexColor("#E2E8F0")
WARN_BG = colors.HexColor("#FEF3C7")
WARN_BORDER = colors.HexColor("#F59E0B")


def build_styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=26, leading=30, textColor=NAVY, spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=12, leading=16, textColor=MUTED, spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, textColor=NAVY, spaceBefore=18, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=17, textColor=STEEL, spaceBefore=14, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, textColor=ACCENT, spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=colors.black, alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, leftIndent=14, bulletIndent=2,
            textColor=colors.black, spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=MUTED,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontName="Courier",
            fontSize=8.5, leading=11, textColor=colors.black, backColor=BG_CODE,
            borderPadding=6, leftIndent=0, rightIndent=0, spaceBefore=4, spaceAfter=8,
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=10, leading=14, textColor=colors.HexColor("#92400E"),
            backColor=WARN_BG, borderPadding=8, borderColor=WARN_BORDER,
            borderWidth=1, spaceBefore=6, spaceAfter=10,
        ),
    }
    return styles


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(BG_TABLE)
    canvas.setLineWidth(0.5)
    canvas.line(0.75 * inch, LETTER[1] - 0.55 * inch,
                LETTER[0] - 0.75 * inch, LETTER[1] - 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, LETTER[1] - 0.45 * inch,
                      "mls-backend · GCP Infrastructure Reference")
    canvas.drawRightString(LETTER[0] - 0.75 * inch, LETTER[1] - 0.45 * inch,
                           "homeatlas-513912 · northamerica-northeast2")
    canvas.drawCentredString(LETTER[0] / 2, 0.4 * inch,
                             f"Page {doc.page}")
    canvas.restoreState()


def kv_table(rows, col_widths=(1.6 * inch, 4.9 * inch)):
    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), STEEL),
        ("BACKGROUND", (0, 0), (0, -1), BG_CODE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, BG_TABLE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BG_TABLE),
    ]))
    return tbl


def bullets(items, style):
    return [Paragraph(f"• {t}", style) for t in items]


def code(text, style):
    return Preformatted(text.strip("\n"), style)


def build_story(styles):
    s = []

    s.append(Paragraph("GCP Infrastructure Reference", styles["title"]))
    s.append(Paragraph(
        "Production stack running on Google Cloud for the mls-backend "
        "Django application. Covers every service in use, its security "
        "configuration, and the step-by-step redeploy procedure.",
        styles["subtitle"]))
    s.append(kv_table([
        ["Project ID", "homeatlas-513912"],
        ["Primary region", "northamerica-northeast2 (Toronto)"],
        ["Architecture", "Single-VM Docker Compose stack behind Caddy TLS"],
        ["Backend framework", "Django 5.2 + Gunicorn + Celery (worker/beat)"],
        ["Container registry", "northamerica-northeast2-docker.pkg.dev/homeatlas-513912/homeatlasdbrepository"],
        ["Database", "Cloud SQL — Postgres 18, homeatlasdatabase (db-g1-small, 100 GB)"],
        ["Object storage", "GCS bucket homeatlasbucket"],
        ["VM", "homeatlas-instance-20261113-135918 (e2-medium, zone -a)"],
        ["Public IP", "34.130.129.136 (fronted by Caddy for HTTPS)"],
        ["TLS", "Caddy 2 with Let's Encrypt (automatic renewal)"],
    ]))

    # Section 1 — Architecture overview
    s.append(Paragraph("1. Architecture at a glance", styles["h1"]))
    s.append(Paragraph(
        "A single Compute Engine VM runs the full application stack via "
        "Docker Compose. The VM's attached service account authenticates to "
        "every GCP dependency over the metadata server — no JSON key files "
        "ever sit on disk. Caddy terminates TLS at the edge, forwards HTTP "
        "to Gunicorn, and Celery pulls work from an in-container Redis.",
        styles["body"]))
    s.append(code("""
                     [ Internet ]
                          |  :443 (TLS)
                          v
          +-------------------------------+
          |         Caddy (container)     |   Let's Encrypt + reverse proxy
          +-------------------------------+
                          |  :8080 (HTTP, loopback)
                          v
          +-------------------------------+
          |  Gunicorn / Django (backend)  |
          +--+--------------+-------------+
             |              |
             | :5432        | :6379
             v              v
     +-----------+   +------------+
     |cloudsql-  |   |  Redis     |   broker + cache + session store
     |  proxy    |   | (container)|
     +-----+-----+   +------------+
           |                         ^
           | mTLS tunnel             |
           v                         |
     Cloud SQL (homeatlasdatabase)   |
                                     |
     +-----------+------------+------+
     | Celery worker  |  Celery beat |   same image, different CMD
     +----------------+--------------+
""", styles["code"]))

    # Section 2 — Services
    s.append(Paragraph("2. GCP services in use", styles["h1"]))

    # 2.1 Compute Engine
    s.append(Paragraph("2.1 Compute Engine (VM host)", styles["h2"]))
    s.append(kv_table([
        ["Instance", "homeatlas-instance-20261113-135918"],
        ["Zone / region", "northamerica-northeast2-a"],
        ["Machine type", "e2-medium (2 vCPU, 4 GB RAM)"],
        ["Boot disk", "20 GB pd-balanced (encrypted at rest by default)"],
        ["OS", "Debian 12"],
        ["Public IP", "34.130.129.136"],
        ["Network tags", "http-server, https-server"],
    ]))
    s.append(Paragraph("Security posture:", styles["h3"]))
    s.extend(bullets([
        "Attached service account <b>homeatlas-vm-sa@homeatlas-513912.iam.gserviceaccount.com</b> "
        "with scope <b>cloud-platform</b>. All GCP auth flows through this identity.",
        "Only ports 22 / 80 / 443 reach the VM (firewall rule <b>allow-http-https</b>; "
        "SSH via the default rule).",
        "SSH restricted to OS Login users — no static SSH keys in metadata.",
        "Boot disk is encrypted with Google-managed keys; swap is disabled.",
        "No static credentials stored on the VM other than <b>.env.prod</b> "
        "(chmod 600, owned by root) — see §3.",
    ], styles["bullet"]))

    # 2.2 Artifact Registry
    s.append(Paragraph("2.2 Artifact Registry (Docker)", styles["h2"]))
    s.append(kv_table([
        ["Repository", "homeatlasdbrepository"],
        ["Format / mode", "DOCKER · STANDARD_REPOSITORY"],
        ["Region", "northamerica-northeast2"],
        ["Image name", "mls-backend"],
        ["Full URL", "northamerica-northeast2-docker.pkg.dev/<br/>"
                    "homeatlas-513912/homeatlasdbrepository/mls-backend:latest"],
    ]))
    s.append(Paragraph("Security posture:", styles["h3"]))
    s.extend(bullets([
        "Private — only principals with <b>roles/artifactregistry.reader</b> can pull.",
        "The VM's service account pulls at startup; developers push from laptop "
        "after <code>gcloud auth configure-docker northamerica-northeast2-docker.pkg.dev</code>.",
        "Images are immutable by digest; <b>:latest</b> is a floating tag — "
        "roll back by re-tagging an older digest.",
        "Image scanning on push is available via <code>gcloud artifacts docker images scan</code>.",
    ], styles["bullet"]))

    # 2.3 Cloud SQL
    s.append(Paragraph("2.3 Cloud SQL for PostgreSQL", styles["h2"]))
    s.append(kv_table([
        ["Instance", "homeatlasdatabase"],
        ["Engine", "POSTGRES_18"],
        ["Region", "northamerica-northeast2"],
        ["Tier", "db-g1-small (shared vCPU, 1.7 GB RAM)"],
        ["Storage", "100 GB SSD with auto-grow"],
        ["Connection name", "homeatlas-513912:northamerica-northeast2:homeatlasdatabase"],
        ["Backups", "Automated daily backups"],
        ["Point-in-time recovery", "Enabled (WAL retention)"],
    ]))
    s.append(Paragraph("Security posture:", styles["h3"]))
    s.extend(bullets([
        "Accessed via the <b>Cloud SQL Auth Proxy</b> sidecar "
        "(<code>gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.14</code>) — the proxy "
        "opens a mTLS tunnel using the VM service account's <b>roles/cloudsql.client</b>.",
        "The proxy listens only on the internal Docker network "
        "(<code>cloudsql-proxy:5432</code>); the Django connection string "
        "<code>DATABASE_URL</code> targets that hostname.",
        "The DB user password is stored in <b>.env.prod</b> on the VM; never checked into Git.",
        "PITR gives roughly minute-level recovery; backups retain 7 days by default.",
    ], styles["bullet"]))
    s.append(Paragraph(
        "<b>Action item:</b> the instance currently exposes a public IPv4 "
        "(34.130.14.100) with <code>requireSsl=false</code>. The proxy "
        "tunnel makes direct connections unnecessary — consider disabling "
        "public IP (<code>gcloud sql instances patch homeatlasdatabase "
        "--no-assign-ip</code>) or at minimum enforcing SSL "
        "(<code>--require-ssl</code>) to shrink the attack surface.",
        styles["warn"]))

    # 2.4 GCS
    s.append(Paragraph("2.4 Cloud Storage (object storage)", styles["h2"]))
    s.append(kv_table([
        ["Bucket", "homeatlasbucket"],
        ["Location", "northamerica-northeast2"],
        ["Purpose", "User-uploaded media (listing photos, documents, attachments)"],
        ["Integration", "django-storages[google] + google-cloud-storage"],
    ]))
    s.append(Paragraph("Security posture:", styles["h3"]))
    s.extend(bullets([
        "The VM service account holds <b>roles/storage.objectAdmin</b> scoped to this bucket.",
        "Uniform bucket-level access removes per-object ACLs — permissions "
        "flow only through IAM.",
        "Objects are encrypted at rest with Google-managed keys. CMEK can be "
        "enabled later without a data migration.",
        "Public read is granted through an IAM binding on the bucket "
        "(<b>roles/storage.objectViewer</b> → <code>allUsers</code>). "
        "Writes always require the VM identity.",
        "CORS allows browser uploads from the app origins; everything else is rejected at the edge.",
    ], styles["bullet"]))

    # 2.5 IAM
    s.append(Paragraph("2.5 IAM — service accounts and roles", styles["h2"]))
    s.append(Paragraph(
        "A single application service account carries every role the VM needs; "
        "there are no JSON keys and no human IAM users attached to runtime identities.",
        styles["body"]))
    s.append(kv_table([
        ["Service account", "homeatlas-vm-sa@homeatlas-513912.iam.gserviceaccount.com"],
        ["Attached to", "VM homeatlas-instance-20261113-135918"],
        ["Access scopes", "https://www.googleapis.com/auth/cloud-platform"],
        ["Roles", "artifactregistry.reader · storage.objectAdmin · cloudsql.client"],
        ["Credentials", "None on disk — OAuth tokens minted via metadata server"],
    ]))
    s.append(Paragraph("Security posture:", styles["h3"]))
    s.extend(bullets([
        "Each role is the minimum required for its service — no project-wide "
        "<code>Editor</code> or <code>Owner</code> bindings.",
        "The metadata server is reachable only from inside the VM at "
        "<code>http://metadata.google.internal</code>; tokens never leave the VM.",
        "Human access to GCP uses personal Google accounts with "
        "<b>OS Login</b> for SSH and Console roles for day-to-day management.",
        "To rotate: create a new SA, bind the three roles, update the VM "
        "(<code>gcloud compute instances set-service-account</code>), reboot.",
    ], styles["bullet"]))

    # 2.6 Networking
    s.append(Paragraph("2.6 VPC, firewall, DNS", styles["h2"]))
    s.extend(bullets([
        "<b>VPC:</b> default VPC, default subnet in northamerica-northeast2. "
        "No Shared VPC or private service connect required for this scale.",
        "<b>Firewall:</b> two ingress rules apply — the default "
        "<code>default-allow-ssh</code> (tcp:22) and the custom "
        "<code>allow-http-https</code> (tcp:80,443) scoped to the "
        "<code>http-server</code> / <code>https-server</code> tags on the VM.",
        "<b>Egress:</b> unrestricted. Required for Let's Encrypt ACME, "
        "Artifact Registry pulls, Google APIs, and any third-party services "
        "(Twilio, SendGrid, AMPRE, Cloudinary, GHL).",
        "<b>DNS:</b> managed outside GCP. An A record points "
        "<code>api.&lt;yourdomain&gt;</code> at <b>34.130.129.136</b>. "
        "Caddy will not obtain a Let's Encrypt certificate until DNS resolves to this IP.",
    ], styles["bullet"]))

    # 2.7 TLS / Caddy
    s.append(Paragraph("2.7 TLS termination (Caddy)", styles["h2"]))
    s.extend(bullets([
        "Caddy 2 runs as a container on the VM and binds host ports 80 and 443.",
        "Automatic certificate issuance and renewal via Let's Encrypt. "
        "Account key and cert cache persist in the named volumes "
        "<code>caddy-data</code> and <code>caddy-config</code>.",
        "Configuration lives at <code>/opt/mls-backend/deploy/Caddyfile</code> and "
        "is mounted read-only. HTTP is redirected to HTTPS automatically.",
        "Modern TLS defaults (TLS 1.2+, strong ciphers, HSTS when enabled).",
    ], styles["bullet"]))

    # 2.8 Services not in use
    s.append(Paragraph("2.8 Google services explicitly not in use", styles["h2"]))
    s.extend(bullets([
        "<b>Secret Manager:</b> secrets live in <code>/opt/mls-backend/.env.prod</code> "
        "(chmod 600, root-owned). The VM boot disk is encrypted at rest, so the "
        "trust boundary is the VM itself. Migrating later is a simple "
        "<code>gcloud secrets versions access</code> at container start.",
        "<b>Memorystore:</b> Redis runs as a container with an AOF-persisted volume. "
        "This fits the current load; move to Memorystore if you need HA or "
        "cross-zone durability.",
        "<b>Cloud Run / GKE:</b> not deployed — the single-VM footprint is "
        "cheaper and Celery beat/worker are easier to run alongside the web "
        "process. Cloud Run remains an option for the web service alone.",
        "<b>Cloud Logging / Monitoring Agent:</b> not installed. Logs are "
        "collected by the Docker daemon (<code>docker logs ...</code>). "
        "Enable Ops Agent if you need shipped logs or custom metrics.",
        "<b>Cloud DNS, Cloud CDN, Cloud Armor, Cloud Build:</b> not used.",
    ], styles["bullet"]))

    s.append(PageBreak())

    # Section 3 — Security summary
    s.append(Paragraph("3. Security summary", styles["h1"]))
    s.append(Paragraph("Credential model", styles["h2"]))
    s.extend(bullets([
        "<b>No service-account JSON keys anywhere.</b> All GCP auth is minted "
        "on the VM through the metadata server and is scoped to the attached SA.",
        "<b>Application secrets</b> (DB password, Django <code>SECRET_KEY</code>, "
        "third-party API keys) are in <code>/opt/mls-backend/.env.prod</code> "
        "with permissions <code>-rw------- root root</code>.",
        "<b>SSH</b> is gated by OS Login + IAM; no static keys are stored in VM metadata.",
    ], styles["bullet"]))
    s.append(Paragraph("Data at rest", styles["h2"]))
    s.extend(bullets([
        "Compute Engine persistent disks: Google-managed encryption by default.",
        "Cloud SQL volumes and backups: encrypted at rest; PITR enabled.",
        "GCS bucket: encrypted at rest; upgrade path to CMEK remains open.",
    ], styles["bullet"]))
    s.append(Paragraph("Data in transit", styles["h2"]))
    s.extend(bullets([
        "Public traffic: TLS 1.2+ terminated at Caddy with Let's Encrypt certs.",
        "VM ⇄ Cloud SQL: mTLS tunnel via Cloud SQL Auth Proxy (IAM-authenticated).",
        "VM ⇄ GCS: HTTPS, OAuth2-authenticated with the VM service account.",
        "Internal container traffic stays inside the Docker bridge network and never leaves the host.",
    ], styles["bullet"]))
    s.append(Paragraph("Network perimeter", styles["h2"]))
    s.extend(bullets([
        "Only 22 / 80 / 443 are open to the internet.",
        "The database, Redis, Cloud SQL Auth Proxy, and Gunicorn bind to the "
        "compose network only — none are routable from outside the VM.",
        "Firewall rules are scoped by network tag; adding capacity later is additive.",
    ], styles["bullet"]))
    s.append(Paragraph("Open items worth addressing", styles["h2"]))
    s.extend(bullets([
        "Disable the public IPv4 on <b>homeatlasdatabase</b>, or at least set "
        "<code>--require-ssl</code>. The proxy makes direct connections unnecessary.",
        "Pin container images by digest (not <code>:latest</code>) in "
        "<code>docker-compose.prod.yml</code> to prevent drift between pulls.",
        "Add a scheduled check that confirms Cloud SQL PITR retention is still enabled.",
        "Consider enabling Vulnerability Scanning on the Artifact Registry repository.",
    ], styles["bullet"]))

    # Section 4 — Redeploy
    s.append(PageBreak())
    s.append(Paragraph("4. How to redeploy the backend", styles["h1"]))
    s.append(Paragraph(
        "The deploy flow is <b>build locally → push to Artifact Registry → "
        "SSH to VM → pull + recreate</b>. Nothing happens in CI today.",
        styles["body"]))

    s.append(Paragraph("4.1 One-time setup (dev laptop)", styles["h2"]))
    s.append(code("""
# Install Google Cloud SDK and Docker Desktop.
gcloud auth login
gcloud config set project homeatlas-513912
gcloud auth configure-docker northamerica-northeast2-docker.pkg.dev
""", styles["code"]))

    s.append(Paragraph("4.2 Build and push the image", styles["h2"]))
    s.append(Paragraph(
        "The VM runs <code>linux/amd64</code>. On an ARM Mac or any mismatched "
        "host, the <code>--platform</code> flag is required.",
        styles["body"]))
    s.append(code("""
$env:IMAGE = "northamerica-northeast2-docker.pkg.dev/homeatlas-513912/" +
             "homeatlasdbrepository/mls-backend:latest"

docker build --platform=linux/amd64 -t $env:IMAGE .
docker push $env:IMAGE
""", styles["code"]))

    s.append(Paragraph("4.3 Roll the image onto the VM", styles["h2"]))
    s.append(code("""
gcloud compute ssh homeatlas-instance-20261113-135918 \\
    --zone=northamerica-northeast2-a \\
    --project=homeatlas-513912

# Inside the VM:
cd /opt/mls-backend
sudo docker compose -f docker-compose.prod.yml pull backend worker beat
sudo docker compose -f docker-compose.prod.yml up -d backend worker beat
""", styles["code"]))
    s.append(Paragraph(
        "The <code>docker-compose.prod.yml</code> file already contains the "
        "Artifact Registry URL via <code>${IMAGE}</code>. If the variable is "
        "unset, export it or pin it in <code>/etc/environment</code>.",
        styles["body"]))

    s.append(Paragraph("4.4 Database migrations", styles["h2"]))
    s.append(Paragraph(
        "Run migrations only when you ship a new <code>migrations/</code> "
        "file. Migrations are safe to run while the old pods are still serving.",
        styles["body"]))
    s.append(code("""
sudo docker compose -f docker-compose.prod.yml exec backend \\
    python manage.py migrate --noinput
""", styles["code"]))

    s.append(Paragraph("4.5 Verify", styles["h2"]))
    s.append(code("""
# From anywhere:
curl -fsS https://api.<yourdomain>/health/ && echo OK

# On the VM:
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml logs --tail=100 backend worker beat
""", styles["code"]))

    s.append(Paragraph("4.6 Rollback", styles["h2"]))
    s.append(Paragraph(
        "Artifact Registry keeps every digest. To roll back, repoint "
        "<code>:latest</code> at the previous digest and redo §4.3.",
        styles["body"]))
    s.append(code("""
# List recent digests (newest first):
gcloud artifacts docker images list \\
  northamerica-northeast2-docker.pkg.dev/homeatlas-513912/homeatlasdbrepository/mls-backend \\
  --sort-by=~UPDATE_TIME --limit=5

# Re-tag an older digest as :latest, then repeat §4.3:
gcloud artifacts docker tags add \\
  northamerica-northeast2-docker.pkg.dev/homeatlas-513912/homeatlasdbrepository/mls-backend@sha256:<OLD_DIGEST> \\
  northamerica-northeast2-docker.pkg.dev/homeatlas-513912/homeatlasdbrepository/mls-backend:latest
""", styles["code"]))

    s.append(Paragraph("4.7 Full rebuild of the VM (disaster recovery)", styles["h2"]))
    s.extend(bullets([
        "Create a new e2-medium VM in <code>northamerica-northeast2-a</code> "
        "with the same service account, cloud-platform scope, and "
        "<code>http-server,https-server</code> tags.",
        "Run <code>deploy/bootstrap-vm.sh</code> on the new VM — it installs "
        "Docker, configures Artifact Registry auth, and creates "
        "<code>/opt/mls-backend/</code>.",
        "Copy <code>docker-compose.prod.yml</code>, <code>deploy/Caddyfile</code>, "
        "and a fresh <code>.env.prod</code> to <code>/opt/mls-backend/</code>.",
        "Repoint the DNS A record at the new public IP; Caddy will fetch "
        "certs on first boot.",
        "<code>docker compose -f docker-compose.prod.yml up -d</code> brings the stack up. "
        "Cloud SQL data survives on the managed instance, so no restore is needed.",
    ], styles["bullet"]))

    s.append(Paragraph("4.8 Common pitfalls", styles["h2"]))
    s.extend(bullets([
        "<b>Wrong platform</b>: omitting <code>--platform=linux/amd64</code> on "
        "an ARM host ships an arm64 image and the VM fails to start.",
        "<b>Missing dependency in requirements.txt</b>: build succeeds locally "
        "because the editable virtualenv has extras installed, but the image "
        "fails at <code>collectstatic</code>. Keep "
        "<code>requirements.txt</code> in sync with every new import.",
        "<b>Stale .env.prod</b>: if the VM reboots and env vars "
        "like <code>IMAGE</code>, <code>DOMAIN</code>, "
        "<code>ADMIN_EMAIL</code> aren't in <code>/etc/environment</code>, "
        "<code>docker compose up</code> silently falls back to empty values.",
        "<b>Caddy certificate thrash</b>: if DNS flips between IPs during a "
        "rebuild, Let's Encrypt rate-limits. Finish DNS cutover before "
        "starting Caddy.",
    ], styles["bullet"]))

    s.append(Spacer(1, 12))
    s.append(Paragraph(
        "Document generated from the live state of project "
        "<b>homeatlas-513912</b> and the deploy guides under "
        "<code>DEPLOY_GCP.md</code> and <code>ENV_GCP_GUIDE.md</code>.",
        styles["small"]))

    return s


def main():
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.7 * inch,
        title="mls-backend — GCP Infrastructure Reference",
        author="mls-backend",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="default", frames=frame,
                                       onPage=header_footer)])
    styles = build_styles()
    doc.build(build_story(styles))
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
