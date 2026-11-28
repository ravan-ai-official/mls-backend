"""Scheduled work for the homepage feeds.

Each job is a plain function so it can run from Celery beat, a management
command, or an external cron hitting the command — whichever the deployment
has (the Vercel deploy has no worker, so cron + command is the likely path).
"""

from __future__ import annotations

import logging

from django.db import transaction

from mls.services.ampre_client import AmpreClientError
from mls.views_market import GTA_CITIES

from . import ampre
from .feeds import refresh_market_snapshot
from .news import ingest_all
from .sold_below import find_repeat_sale_gains, find_repeat_sale_losses
from .subscriptions import send_nearby_alerts

logger = logging.getLogger(__name__)

# AMPRE retains ~2 years of closed sales; asking for more returns nothing extra.
SOLD_HISTORY_DAYS = 730
# The AMPRE client stops at MAX_PAGES_SAFETY (50) pages of 1000.
SOLD_ROWS_PER_CITY = 50000


def refresh_sold_below_purchase(cities=GTA_CITIES) -> dict[str, int]:
    """Rebuild SoldBelowPurchase + ProfitableInvestment from AMPRE closed history.

    One AMPRE pull per city feeds both rails (losses and 12‑month gains).
    A city whose fetch fails keeps its previous rows: each table is replaced
    city by city, never emptied because one upstream call broke.
    """
    from homepage.models import ProfitableInvestment, SoldBelowPurchase

    summary: dict[str, int] = {}
    for city in cities:
        try:
            rows = ampre.fetch_closed_sales(city, days=SOLD_HISTORY_DAYS, max_rows=SOLD_ROWS_PER_CITY)
        except AmpreClientError as exc:
            logger.warning("Repeat-sale refresh skipped %s: %s", city, exc)
            summary[city] = -1
            continue
        losses = find_repeat_sale_losses(rows)
        gains = find_repeat_sale_gains(rows)
        with transaction.atomic():
            SoldBelowPurchase.objects.filter(city__iexact=city).delete()
            SoldBelowPurchase.objects.bulk_create(
                [
                    SoldBelowPurchase(
                        listing_key=loss.listing_key,
                        address=loss.address,
                        city=loss.city,
                        property_sub_type=loss.property_sub_type,
                        bedrooms=loss.bedrooms,
                        bathrooms=loss.bathrooms,
                        close_price=loss.close_price,
                        close_date=loss.close_date,
                        previous_close_price=loss.previous_close_price,
                        previous_close_date=loss.previous_close_date,
                    )
                    for loss in losses
                ],
                # A resale in a neighbouring city's prefix match (rare) must
                # not abort the whole city.
                ignore_conflicts=True,
            )
            ProfitableInvestment.objects.filter(city__iexact=city).delete()
            ProfitableInvestment.objects.bulk_create(
                [
                    ProfitableInvestment(
                        listing_key=gain.listing_key,
                        address=gain.address,
                        city=gain.city,
                        property_sub_type=gain.property_sub_type,
                        bedrooms=gain.bedrooms,
                        bathrooms=gain.bathrooms,
                        close_price=gain.close_price,
                        close_date=gain.close_date,
                        previous_close_price=gain.previous_close_price,
                        previous_close_date=gain.previous_close_date,
                    )
                    for gain in gains
                ],
                ignore_conflicts=True,
            )
        summary[city] = len(losses)
        summary[f"{city}:gains"] = len(gains)
    return summary


# Alias used by management command / docs for the gains half of the same job.
refresh_profitable_investments = refresh_sold_below_purchase


def run_all() -> dict[str, object]:
    """Everything, in dependency-free order. Used by the combined command."""
    results: dict[str, object] = {}
    for name, job in (
        ("news", ingest_all),
        ("market_snapshot", lambda: bool(refresh_market_snapshot())),
        ("sold_below_purchase", refresh_sold_below_purchase),
        ("nearby_alerts", send_nearby_alerts),
    ):
        try:
            results[name] = job()
        except Exception as exc:  # noqa: BLE001 — one failing job must not stop the rest
            logger.exception("Homepage job %s failed", name)
            results[name] = f"error: {exc}"
    return results
