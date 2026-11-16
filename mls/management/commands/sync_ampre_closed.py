"""
Pull recent Closed / Expired / Cancelled / Withdrawn listings from AMPRE
into the local Property table so Sold and De-listed tabs have rows.

CREA DDF (realtor.ca) is Active-only, so pulling more Active listings never
fills those tabs. AMPRE carries the off-market history the tabs need.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from homepage.services.ampre import RESIDENTIAL_CLAUSE, city_clause
from mls.models import ListingSyncStatus, Property
from mls.services.ampre_client import AmpreClientError, fetch_property_page
from mls.services.ampre_media import (
    is_trreb_property,
    refresh_property_media_from_ampre,
)
from mls.views_market import GTA_CITIES


SELECT_FIELDS = [
    "ListingKey",
    "ListingId",
    "StandardStatus",
    "ListPrice",
    "ClosePrice",
    "CloseDate",
    "PreviousListPrice",
    "PriceChangeTimestamp",
    "UnparsedAddress",
    "City",
    "CityRegion",
    "StateOrProvince",
    "PostalCode",
    "PropertySubType",
    "StructureType",
    "PropertyAttachedYN",
    "BedroomsTotal",
    "BedroomsAboveGrade",
    "BedroomsBelowGrade",
    "BathroomsTotalInteger",
    "LivingArea",
    "LivingAreaMinimum",
    "LivingAreaMaximum",
    "AboveGradeFinishedArea",
    "BuildingAreaTotal",
    "YearBuilt",
    "ApproximateAge",
    "TaxAnnualAmount",
    "AssociationFee",
    "AssociationFeeFrequency",
    "AssociationFeeIncludes",
    "ParkingTotal",
    "ParkingFeatures",
    "BuildingFeatures",
    "CommonInterest",
    "Latitude",
    "Longitude",
    "PublicRemarks",
    "OriginalEntryTimestamp",
    "ModificationTimestamp",
    "TransactionType",
]


def _dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dt(value):
    if not value:
        return None
    if isinstance(value, str):
        return parse_datetime(value.replace("Z", "+00:00")) or None
    return value


def _date(value):
    if not value:
        return None
    if isinstance(value, str):
        return parse_date(value[:10])
    return value


def map_ampre_inactive(row: dict) -> dict:
    """Reuse the shared AMPRE field map so closed/terminated rows stay rich."""
    from mls.services.listing_refresh import map_ampre_row

    mapped = map_ampre_row(row)
    status = (mapped.get("standard_status") or "Closed").strip() or "Closed"
    mapped["standard_status"] = status[:50]
    mapped["category_type"] = Property.DDF
    return mapped


class Command(BaseCommand):
    help = (
        "Upsert recent AMPRE Closed/Expired/Cancelled/Withdrawn listings so "
        "Sold and De-listed search tabs are populated."
    )

    # Overlap guards against boundary rows and late/skipped runs.
    INCREMENTAL_OVERLAP_HOURS = 6
    DEFAULT_BACKFILL_DAYS = 90
    # Incremental is time-bounded; a 30h GTA window realistically yields a
    # few hundred rows. Cap is a defensive stop, not a tuning parameter.
    INCREMENTAL_MAX_ROWS = 10000

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help=(
                "Explicit look-back window in days. Default: incremental from "
                "the last successful run (or a 90-day backfill on the first run)."
            ),
        )
        parser.add_argument(
            "--max-rows-per-city",
            type=int,
            default=800,
            help="Max AMPRE rows per city per status family (default: 800).",
        )

    def handle(self, *args, **options):
        max_rows = max(50, int(options["max_rows_per_city"]))
        last_status = ListingSyncStatus.objects.filter(key="ampre_closed").first()
        explicit_days = options["days"] is not None

        if explicit_days or not last_status:
            days = max(1, int(options["days"] or self.DEFAULT_BACKFILL_DAYS))
            today = timezone.now().date()
            start = (today - timedelta(days=days)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            self.stdout.write(
                f"AMPRE backfill: {days}-day window "
                f"({'explicit --days' if explicit_days else 'no prior sync'}). "
                f"Per-city cap = {max_rows}."
            )
            plan = self._backfill_plan(start=start, end=end, row_cap=max_rows)
        else:
            incremental_since = last_status.last_successful_at - timedelta(
                hours=self.INCREMENTAL_OVERLAP_HOURS
            )
            ts = (
                incremental_since.replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            self.stdout.write(
                f"AMPRE incremental: ModificationTimestamp >= {ts} "
                f"(GTA-wide, 2 queries, cap = {self.INCREMENTAL_MAX_ROWS})."
            )
            plan = self._incremental_plan(ts=ts)

        created = 0
        updated = 0
        fetched = 0
        media_filled = 0
        cap_hits: list[str] = []

        for label, scope, filter_expression, orderby, row_cap in plan:
            self.stdout.write(f"{scope} | {label}...")
            try:
                rows = fetch_property_page(
                    filter_expression=filter_expression,
                    select_fields=SELECT_FIELDS,
                    orderby=orderby,
                    top=min(1000, row_cap),
                    max_rows=row_cap,
                )
            except AmpreClientError as exc:
                self.stderr.write(self.style.WARNING(f"  skipped: {exc}"))
                continue

            if len(rows) >= row_cap:
                cap_hits.append(f"{scope}/{label}")
                self.stderr.write(
                    self.style.WARNING(
                        f"  hit row cap ({row_cap}); results may be truncated."
                    )
                )

            fetched += len(rows)
            for row in rows:
                ampre_key = str(row.get("ListingKey") or "").strip()
                if not ampre_key:
                    continue
                defaults = map_ampre_inactive(row)
                existing = (
                    Property.objects.filter(
                        Q(listing_id=ampre_key) | Q(listing_key=ampre_key)
                    )
                    .order_by("id")
                    .first()
                )
                if existing:
                    for field, value in defaults.items():
                        if field == "category_type":
                            continue
                        setattr(existing, field, value)
                    existing.save()
                    updated += 1
                    prop = existing
                else:
                    prop = Property.objects.create(
                        listing_key=ampre_key, **defaults
                    )
                    created += 1

                # Closed sync historically wrote listing rows with no
                # Media, so Sold / De-listed cards showed the house
                # placeholder. Pull live AMPRE photos when the gallery
                # is empty.
                if (
                    is_trreb_property(prop)
                    and not prop.media.exists()
                ):
                    try:
                        written = refresh_property_media_from_ampre(prop)
                    except AmpreClientError as exc:
                        self.stderr.write(
                            self.style.WARNING(
                                f"  media skip {prop.listing_id or ampre_key}: {exc}"
                            )
                        )
                        written = 0
                    if written:
                        media_filled += 1

            self.stdout.write(f"  {len(rows):,} rows")

        ListingSyncStatus.objects.update_or_create(
            key="ampre_closed",
            defaults={
                "last_successful_at": timezone.now(),
                "listing_count": fetched,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Fetched {fetched:,}. Created {created:,}, updated {updated:,}. "
                f"Filled media for {media_filled:,}."
            )
        )
        if cap_hits:
            self.stderr.write(
                self.style.WARNING(
                    f"Row cap hit in {len(cap_hits)} partition(s): "
                    f"{', '.join(cap_hits[:10])}"
                    f"{'...' if len(cap_hits) > 10 else ''}. "
                    "Data may be incomplete. Raise --max-rows-per-city (backfill) "
                    "or clear the ampre_closed ListingSyncStatus row to re-backfill."
                )
            )

    def _backfill_plan(self, *, start: str, end: str, row_cap: int):
        """Per-city, per-family queries using CloseDate/ModificationTimestamp
        windows. One tuple per (city, status family)."""
        plan = []
        for city in GTA_CITIES:
            city_filter = city_clause([city])
            plan.append((
                "Closed", city,
                f"({city_filter}) and StandardStatus eq 'Closed' "
                f"and TransactionType eq 'For Sale' and {RESIDENTIAL_CLAUSE} "
                f"and CloseDate ge {start} and CloseDate le {end}",
                "CloseDate desc",
                row_cap,
            ))
            plan.append((
                "De-listed", city,
                f"({city_filter}) and ("
                "StandardStatus eq 'Expired' or StandardStatus eq 'Canceled' "
                "or StandardStatus eq 'Cancelled' or StandardStatus eq 'Withdrawn' "
                "or StandardStatus eq 'Terminated'"
                f") and {RESIDENTIAL_CLAUSE} "
                f"and ModificationTimestamp ge {start}T00:00:00Z",
                "ModificationTimestamp desc",
                row_cap,
            ))
        return plan

    def _incremental_plan(self, *, ts: str):
        """Two GTA-wide queries (Closed, De-listed) filtered by
        ModificationTimestamp. 48 per-city requests collapse to 2."""
        combined_city_filter = city_clause(list(GTA_CITIES))
        return [
            (
                "Closed", "GTA",
                f"({combined_city_filter}) and StandardStatus eq 'Closed' "
                f"and TransactionType eq 'For Sale' and {RESIDENTIAL_CLAUSE} "
                f"and ModificationTimestamp ge {ts}",
                "ModificationTimestamp desc",
                self.INCREMENTAL_MAX_ROWS,
            ),
            (
                "De-listed", "GTA",
                f"({combined_city_filter}) and ("
                "StandardStatus eq 'Expired' or StandardStatus eq 'Canceled' "
                "or StandardStatus eq 'Cancelled' or StandardStatus eq 'Withdrawn' "
                "or StandardStatus eq 'Terminated'"
                f") and {RESIDENTIAL_CLAUSE} "
                f"and ModificationTimestamp ge {ts}",
                "ModificationTimestamp desc",
                self.INCREMENTAL_MAX_ROWS,
            ),
        ]
