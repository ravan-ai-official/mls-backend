from celery import shared_task

from mls.services.newsletter_notifications import send_daily_listing_newsletters


@shared_task
def run_daily_listing_newsletters() -> dict:
    return send_daily_listing_newsletters()


@shared_task
def warm_sold_trends_cache() -> dict:
    from mls.views_market import warm_sold_trends

    return warm_sold_trends()


@shared_task
def run_saved_search_alerts() -> dict:
    from mls.services.saved_search_alerts import send_saved_search_alerts

    return send_saved_search_alerts()


@shared_task
def sync_ddf_listing_cache() -> dict:
    """Incremental DDF sync + expire ghost Actives. Enable via DDF_SYNC_BEAT_ENABLED=1.

    Tunable via env vars so the daily schedule doesn't need code changes:
      DDF_SYNC_RETENTION_DAYS   - keep Active rows seen in the last N days (default 2)
      DDF_SYNC_MAX_STORAGE_MB   - prune oldest rows to stay under this cap (default 8000)
      DDF_SYNC_BATCH_SIZE       - DB write batch size (default 5000)
    """
    import os
    from django.core.management import call_command

    retention_days = int(os.environ.get("DDF_SYNC_RETENTION_DAYS", "2"))
    max_storage_mb = int(os.environ.get("DDF_SYNC_MAX_STORAGE_MB", "8000"))
    batch_size = int(os.environ.get("DDF_SYNC_BATCH_SIZE", "5000"))

    call_command(
        "sync_ddf_properties",
        retention_days=retention_days,
        max_storage_mb=max_storage_mb,
        batch_size=batch_size,
    )
    return {"ok": True}


@shared_task
def sync_ampre_inactive_listings() -> dict:
    """Pull Terminated/Expired/Closed from AMPRE. Enable via AMPRE_CLOSED_BEAT_ENABLED=1.

    Tunable via env vars:
      AMPRE_CLOSED_DAYS               - look-back window (default 90)
      AMPRE_CLOSED_MAX_ROWS_PER_CITY  - cap per city per status family (default 800)
    """
    import os
    from django.core.management import call_command

    days = int(os.environ.get("AMPRE_CLOSED_DAYS", "90"))
    max_rows = int(os.environ.get("AMPRE_CLOSED_MAX_ROWS_PER_CITY", "800"))

    call_command(
        "sync_ampre_closed",
        days=days,
        max_rows_per_city=max_rows,
    )
    return {"ok": True}
