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
    # Removed (AMPRE 400 "property not defined in type 'Property'"):
    #   LivingArea, LivingAreaMinimum, LivingAreaMaximum
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
    # Removed: BuildingFeatures, CommonInterest — not in AMPRE schema.
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
    # Backfill fetches all pages per (city, family) up to the client's
    # MAX_PAGES_SAFETY (50 pages × 1000/page = 50K). Set to the ceiling so
    # the client paginates the full result set, not the fetch_property_page
    # default of 500.
    BACKFILL_MAX_ROWS = 50000

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help=(
                "Fetch all historical Closed / De-listed listings available "
                "from AMPRE (ignores incremental watermark and --days / "
                "--window-hours). Use for manual full resyncs."
            ),
        )
        parser.add_argument(
            "--window-hours",
            type=int,
            default=0,
            help=(
                "Fetch listings modified in the last N hours. Overrides the "
                "default incremental/backfill behavior. 0 (default) keeps "
                "the existing watermark logic. The scheduled Celery task "
                "passes 24."
            ),
        )
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
            default=None,
            help=(
                "Max AMPRE rows per city per status family. Default: full "
                "sync (50K rows / 50 pages per partition via nextLink)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch a small sample from 1 partition and validate the "
                "mapper + Property() instantiation. NO DB writes, NO status "
                "update, NO media refresh."
            ),
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=5,
            help="Rows to fetch per partition in --dry-run (default: 5).",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        sample_size = max(1, int(options.get("sample") or 5))

        # Explicit --max-rows-per-city still binds (for throttled re-runs);
        # default now pulls the full per-(city, family) result set via the
        # client's MAX_PAGES_SAFETY ceiling.
        explicit_max_rows = options["max_rows_per_city"] is not None
        max_rows = (
            max(50, int(options["max_rows_per_city"]))
            if explicit_max_rows
            else self.BACKFILL_MAX_ROWS
        )
        last_status = (
            None if dry_run
            else ListingSyncStatus.objects.filter(key="ampre_closed").first()
        )
        explicit_days = options["days"] is not None
        full_sync = bool(options.get("full"))
        window_hours = int(options.get("window_hours") or 0)

        if full_sync and (explicit_days or window_hours):
            from django.core.management.base import CommandError
            raise CommandError(
                "--full is mutually exclusive with --days and --window-hours."
            )
        if window_hours < 0:
            from django.core.management.base import CommandError
            raise CommandError("--window-hours must be >= 0.")

        if full_sync:
            # Huge look-back window → effectively "everything AMPRE has".
            days = 36500  # ~100 years
            today = timezone.now().date()
            start = (today - timedelta(days=days)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            self.stdout.write(
                f"AMPRE --full: pulling all history (window={days} days). "
                f"Per-city cap = {max_rows} rows."
            )
            plan = self._backfill_plan(start=start, end=end, row_cap=max_rows)
            if dry_run:
                plan = [p for p in plan if p[1] == "Toronto"][:1]
                plan = [(p[0], p[1], p[2], p[3], sample_size) for p in plan]
        elif window_hours:
            incremental_since = timezone.now() - timedelta(hours=window_hours)
            ts = (
                incremental_since.replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            self.stdout.write(
                f"AMPRE --window-hours={window_hours}: "
                f"ModificationTimestamp >= {ts} "
                f"(GTA-wide, 2 queries, cap = {self.INCREMENTAL_MAX_ROWS})."
            )
            plan = self._incremental_plan(ts=ts)
            if dry_run:
                plan = plan[:1]
                plan = [(p[0], p[1], p[2], p[3], sample_size) for p in plan]
        elif explicit_days or not last_status:
            days = max(1, int(options["days"] or self.DEFAULT_BACKFILL_DAYS))
            today = timezone.now().date()
            start = (today - timedelta(days=days)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            self.stdout.write(
                f"AMPRE backfill: {days}-day window "
                f"({'explicit --days' if explicit_days else 'no prior sync'}). "
                f"Per-city cap = {max_rows} rows "
                f"({'explicit' if explicit_max_rows else 'default full-sync'})."
            )
            plan = self._backfill_plan(start=start, end=end, row_cap=max_rows)
            if dry_run:
                # Trim to 1 partition (Toronto Closed) and shrink row cap.
                plan = [p for p in plan if p[1] == "Toronto"][:1]
                plan = [(p[0], p[1], p[2], p[3], sample_size) for p in plan]
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
            if dry_run:
                plan = plan[:1]  # Closed only
                plan = [(p[0], p[1], p[2], p[3], sample_size) for p in plan]

        created = 0
        updated = 0
        fetched = 0
        media_filled = 0
        cap_hits: list[str] = []

        for label, scope, filter_expression, orderby, row_cap in plan:
            self.stdout.write(f"{scope} | {label}...")
            # Fail-fast: AMPRE errors abort the whole sync instead of
            # silently skipping partitions. A partial first-ever backfill
            # would advance ListingSyncStatus and permanently lose history.
            rows = fetch_property_page(
                filter_expression=filter_expression,
                select_fields=SELECT_FIELDS,
                orderby=orderby,
                top=min(1000, row_cap),
                max_rows=row_cap,
            )

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
                if dry_run:
                    # Instantiate (no save) to validate mapper kwargs match
                    # the model — catches crashes like the DDF kitchens/
                    # garages mismatch without touching the DB.
                    Property(listing_key=ampre_key, **defaults)
                    created += 1
                    continue
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

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN OK. Fetched {fetched:,} rows, "
                    f"instantiated {created:,} Property objects (no DB writes, "
                    f"no status update)."
                )
            )
            return

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
