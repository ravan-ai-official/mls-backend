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
    """Daily DDF sync of listings created or updated in the last 24 hours.

    Runs every 24h via DDF_SYNC_BEAT_ENABLED=1. Pulls Active listings
    whose ModificationTimestamp is within the last 24 hours — new
    creations and edits both move that timestamp forward, so the same
    filter covers both. No page/storage caps, no age-based prune.
    """
    from django.core.management import call_command

    call_command(
        "sync_ddf_properties",
        window_hours=24,
        batch_size=10000,
    )
    return {"ok": True}


@shared_task
def sync_ampre_inactive_listings() -> dict:
    """Pull Terminated/Expired/Closed from AMPRE. Enable via AMPRE_CLOSED_BEAT_ENABLED=1."""
    from django.core.management import call_command

    call_command("sync_ampre_closed")
    return {"ok": True}
