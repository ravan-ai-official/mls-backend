"""DDF realtime sync — upsert every 100 listings immediately. Append-only.

Paste into:   python manage.py shell
Or run with:  python manage.py shell < scripts/sync_ddf_realtime.py

Each DDF page (100 listings) is fetched and written to the DB *before* the
next page is requested. Rows appear in real time instead of after the full
bulk-upsert phase at the end.

Behaviour:
  * Walks DDF's $nextLink pagination manually.
  * Reuses Command.process_batch() for create/update so Property + Room +
    Media + first-seen + snapshot tables stay in sync with the stock
    management command.
  * Refreshes the DDF OAuth token every TOKEN_REFRESH_EVERY pages.
  * Prints a live progress line per page.
  * Does NOT delete anything — no prune, no expire, no cleanup.
    This script is append-only; the DB only grows.
"""

import sys
import time
import warnings
from typing import Any
from django.db.models import Count
from mls.helpers import get_access_token
from mls.management.commands import sync_ddf_properties as _sdp
from mls.management.commands.sync_ddf_properties import Command
from mls.models import Property
from mls.services.ddf.client import (
    DDF_PROPERTIES_URL,
    get_page_with_retries,
)

# -------------------- silence noisy warnings --------------------
warnings.filterwarnings(
    "ignore",
    message=".*received a naive datetime.*",
    category=RuntimeWarning,
)

# -------------------- patch map_property_defaults ------------------
# The DDF mapper emits 'garages', 'garage_size', 'kitchens' which do NOT
# exist on the Property model, so Property(**defaults) blows up and every
# page's upsert gets skipped. Strip unknown keys at mapping time so the
# write-path never sees them.
_valid_property_fields = {
    f.name for f in Property._meta.get_fields()
    if getattr(f, "concrete", False) and not f.many_to_many
}
_original_map_property_defaults = _sdp.map_property_defaults

def _safe_map_property_defaults(data):
    mapped = _original_map_property_defaults(data)
    for k in [k for k in mapped if k not in _valid_property_fields]:
        mapped.pop(k, None)
    return mapped

_sdp.map_property_defaults = _safe_map_property_defaults
print(
    f"[patch] map_property_defaults monkey-patched; "
    f"{len(_valid_property_fields)} Property fields known."
)

# -------------------- knobs --------------------
# This script is APPEND-ONLY to match the sync_ddf_properties command.
# Pruning and deletion knobs that used to live here have been removed —
# every page is upserted and nothing is deleted.
MAX_PAGES = 0                           # 0 = no page limit
PAGE_SLEEP_SECONDS = 0.05               # courtesy pause between pages
TOKEN_REFRESH_EVERY = 300               # re-check token this many pages in
STATUS_FIELD_FILTER = "Active"          # label used in the before/after breakdown only

# -------------------- helpers --------------------
def ddf_counts() -> tuple[int, int]:
    """(total DDF rows, Active DDF rows)."""
    total  = Property.objects.filter(category_type=Property.DDF).count()
    active = Property.objects.filter(
        category_type=Property.DDF,
        standard_status__iexact=STATUS_FIELD_FILTER,
    ).count()
    return total, active


def print_breakdown(label: str) -> None:
    total, active = ddf_counts()
    non_active = total - active
    print(f"\n[{label}] total={total:,}  active={active:,}  non_active={non_active:,}")
    rows = (
        Property.objects.filter(category_type=Property.DDF)
        .values("standard_status")
        .annotate(n=Count("*"))
        .order_by("-n")
    )
    for r in rows:
        name = r["standard_status"] or "NULL"
        print(f"  {name:20s} : {r['n']:>8,}")


def fmt_elapsed(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}m{sec % 60:02d}s"


# -------------------- banner --------------------
print("=" * 60)
print("DDF REALTIME SYNC — page-by-page create/update")
print("=" * 60)
print_breakdown("BEFORE")

# -------------------- token --------------------
print("\nAcquiring DDF access token...")
token = get_access_token()
if not token:
    raise RuntimeError("Failed to get DDF access token. Check AccessToken rows.")
headers = {"Authorization": f"Bearer {token}"}
print("  token acquired.")

# -------------------- reuse Command.process_batch --------------------
cmd = Command()   # BaseCommand.__init__ wires stdout/style to sys.stdout + color_style
cmd.stdout = __import__("django.core.management.base", fromlist=["OutputWrapper"]).OutputWrapper(sys.stdout)

# -------------------- paginated upsert loop --------------------
url: str | None = DDF_PROPERTIES_URL
params: dict[str, Any] | None = {
    "$top": 100,
    "$orderby": "ModificationTimestamp desc",
}

page = 0
upserted_total = 0
failed_pages = 0
started_at = time.monotonic()

print("\nStarting realtime sync. Progress printed per page.\n")

while url:
    page += 1
    page_t0 = time.monotonic()
    # Periodic token refresh (safety net for multi-hour runs)
    if page > 1 and page % TOKEN_REFRESH_EVERY == 0:
        try:
            fresh = get_access_token()
            if fresh and fresh != token:
                token = fresh
                headers = {"Authorization": f"Bearer {token}"}
                print(f"  [page {page}] refreshed DDF token.")
        except Exception as exc:
            print(f"  [page {page}] token refresh failed: {exc}. Continuing with existing token.")
    # 1. Fetch one page
    try:
        resp = get_page_with_retries(url, headers=headers, params=params)
    except Exception as exc:
        print(f"  [page {page}] fetch failed: {exc}. Stopping.")
        break
    data = resp.json()
    page_listings = data.get("value", []) or []
    next_url = data.get("@odata.nextLink")
    if not page_listings:
        print(f"  [page {page}] empty response — end of catalogue.")
        break
    # 2. Upsert this page IMMEDIATELY (atomic transaction per page)
    try:
        cmd.process_batch(page_listings, insert_new_only=False)
        upserted_total += len(page_listings)
    except Exception as exc:
        failed_pages += 1
        print(f"  [page {page}] upsert failed: {exc}. Skipping page.")
    # 3. Status line (live DB counts)
    page_elapsed = time.monotonic() - page_t0
    total_now, active_now = ddf_counts()
    total_elapsed = time.monotonic() - started_at
    rate = upserted_total / total_elapsed if total_elapsed > 0 else 0
    print(
        f"  page {page:4d} "
        f"+{len(page_listings):3d} "
        f"| upserted={upserted_total:>6,} "
        f"| db total={total_now:>6,} active={active_now:>6,} "
        f"| {page_elapsed:4.1f}s/page ({rate:4.1f} rows/s) "
        f"| elapsed {fmt_elapsed(total_elapsed)}"
    )
    # 5. Move to next page
    url = next_url
    params = None   # the first request carries params; nextLink has them baked in
    if url:
        time.sleep(PAGE_SLEEP_SECONDS)
    if MAX_PAGES and page >= MAX_PAGES:
        print(f"  reached MAX_PAGES={MAX_PAGES}, stopping.")
        break

total_elapsed = time.monotonic() - started_at
print(
    f"\n--- download+upsert complete: "
    f"{upserted_total:,} listings across {page} pages "
    f"in {fmt_elapsed(total_elapsed)} "
    f"(failed pages: {failed_pages}) ---"
)

# -------------------- AFTER snapshot --------------------
# Append-only policy: no prune, no expire, no cleanup of non-Active rows.
# Everything the feed returned is kept in the DB.
print_breakdown("AFTER")

print("\nDone.")
