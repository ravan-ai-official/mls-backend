"""
Pull AMPRE listings (all statuses) into the local Property table.

CREA DDF is Active-only, so Closed / Expired / Cancelled / Withdrawn
(and TRREB Active gaps) are filled from AMPRE. Syncs every property
type except Agriculture / Farm / Industrial.

Append-only: this command NEVER deletes Property rows. It only inserts
new listings or updates existing ones.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from homepage.services.ampre import city_clause
from mls.models import ListingSyncStatus, Property
from mls.services.ampre_client import AmpreClientError, fetch_property_page
from mls.services.ampre_media import (
    is_trreb_property,
    refresh_property_media_from_ampre,
)
from mls.services.listing_sync_status import clear_cache as clear_listing_sync_status_cache
from mls.services.sync_filters import EXCLUDE_AG_INDUSTRY_CLAUSE
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
    # LivingArea / LivingAreaMinimum / LivingAreaMaximum / BuildingFeatures /
    # CommonInterest are NOT in AMPRE Property metadata — selecting them
    # returns HTTP 400 ("property ... is not defined in type 'Property'").
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
    """Parse AMPRE timestamps as timezone-aware UTC."""
    if not value:
        return None
    if isinstance(value, str):
        parsed = parse_datetime(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        return None
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


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


INACTIVE_STATUS_FILTER = (
    "("
    "StandardStatus eq 'Expired' or StandardStatus eq 'Canceled' "
    "or StandardStatus eq 'Cancelled' or StandardStatus eq 'Withdrawn' "
    "or StandardStatus eq 'Terminated'"
    ")"
)

# All non-ag / non-industrial types (Residential, Commercial, Retail, …).
TYPE_CLAUSE = EXCLUDE_AG_INDUSTRY_CLAUSE

# Fields written on every upsert (everything map_ampre_inactive returns
# except category_type, which we never overwrite on existing rows).
_UPDATE_FIELDS = [
    "listing_id",
    "standard_status",
    "list_price",
    "close_price",
    "close_date",
    "previous_list_price",
    "price_change_timestamp",
    "unparsed_address",
    "city",
    "city_region",
    "state_or_province",
    "postal_code",
    "property_sub_type",
    "structure_type",
    "property_attached_yn",
    "bedrooms_total",
    "bedrooms_above_grade",
    "bedrooms_below_grade",
    "bathrooms_total_integer",
    "living_area",
    "living_area_minimum",
    "living_area_maximum",
    "above_grade_finished_area",
    "building_area_total",
    "year_built",
    "tax_annual_amount",
    "association_fee",
    "association_fee_frequency",
    "association_fee_includes",
    "parking_total",
    "parking_features",
    "building_features",
    "common_interest",
    "public_remarks",
    "original_entry_timestamp",
    "modification_timestamp",
    "status_change_timestamp",
]


class Command(BaseCommand):
    help = (
        "Upsert AMPRE listings for all statuses "
        "(Active / Closed / De-listed), excluding Agriculture / "
        "Industrial. Append-only — never deletes Property rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help=(
                "Fetch all historical Closed / De-listed listings available "
                "from AMPRE (ignores --days / --window-hours)."
            ),
        )
        parser.add_argument(
            "--window-hours",
            type=int,
            default=0,
            help=(
                "Fetch listings modified in the last N hours "
                "(new + updated). Celery beat passes 24."
            ),
        )
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help=(
                "Look-back window in days when neither --full nor "
                "--window-hours is set (default: 90)."
            ),
        )
        parser.add_argument(
            "--max-rows-per-city",
            type=int,
            default=800,
            help=(
                "Max AMPRE rows per city per status family "
                "(default: 800; raised automatically for --full)."
            ),
        )
        parser.add_argument(
            "--skip-media",
            action="store_true",
            help="Skip empty-gallery AMPRE media fills (faster full sync).",
        )

    def handle(self, *args, **options):
        if options["full"] and options["window_hours"]:
            raise CommandError(
                "--full and --window-hours are mutually exclusive."
            )
        if options["window_hours"] < 0:
            raise CommandError("--window-hours must be >= 0.")

        is_full = bool(options["full"])
        window_hours = int(options["window_hours"] or 0)
        days = max(1, int(options["days"]))
        # Full catalogue needs a high per-city budget; AMPRE pages at 1000.
        if is_full:
            max_rows = max(50_000, int(options["max_rows_per_city"]))
        else:
            max_rows = max(50, int(options["max_rows_per_city"]))
        # Media is part of a complete sync. Only skip when the operator
        # explicitly passes --skip-media (e.g. a data-only emergency run).
        skip_media = bool(options["skip_media"])

        if is_full:
            # AMPRE returns HTTP 400 on unbounded Closed/De-listed queries.
            # Use a long CloseDate / ModificationTimestamp lookback instead
            # of dropping the temporal filter entirely.
            today = timezone.now().date()
            start = (today - timedelta(days=3650)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            mode_label = f"full catalogue (~10y lookback {start} .. {end})"
            active_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {start}T00:00:00Z"
            )
            closed_extra = (
                f"and {TYPE_CLAUSE} "
                f"and CloseDate ge {start} and CloseDate le {end}"
            )
            delisted_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {start}T00:00:00Z"
            )
            closed_order = "CloseDate desc"
        elif window_hours:
            cutoff = timezone.now() - timedelta(hours=window_hours)
            # OData needs a Zulu literal; strip microseconds for compatibility.
            cutoff_lit = (
                cutoff.astimezone(dt_timezone.utc)
                .replace(microsecond=0)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            mode_label = f"window={window_hours}h since {cutoff_lit}"
            # ModificationTimestamp covers both newly created and newly
            # updated rows across Active / Closed / De-listed.
            active_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {cutoff_lit}"
            )
            closed_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {cutoff_lit}"
            )
            delisted_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {cutoff_lit}"
            )
            closed_order = "ModificationTimestamp desc"
        else:
            today = timezone.now().date()
            start = (today - timedelta(days=days)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            mode_label = f"days={days} ({start} .. {end})"
            active_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {start}T00:00:00Z"
            )
            closed_extra = (
                f"and {TYPE_CLAUSE} "
                f"and CloseDate ge {start} and CloseDate le {end}"
            )
            delisted_extra = (
                f"and {TYPE_CLAUSE} "
                f"and ModificationTimestamp ge {start}T00:00:00Z"
            )
            closed_order = "CloseDate desc"

        self.stdout.write(
            f"AMPRE sync mode: {mode_label} "
            "(all statuses; excludes Agriculture / Industrial; append-only)"
        )

        created = 0
        updated = 0
        skipped = 0
        fetched = 0
        media_filled = 0

        for city in GTA_CITIES:
            city_filter = city_clause([city])

            queries = [
                (
                    "Active",
                    f"({city_filter}) and StandardStatus eq 'Active' "
                    f"and TransactionType eq 'For Sale' {active_extra}",
                    "ModificationTimestamp desc",
                ),
                (
                    "Closed",
                    f"({city_filter}) and StandardStatus eq 'Closed' "
                    f"and TransactionType eq 'For Sale' {closed_extra}",
                    closed_order,
                ),
                (
                    "De-listed",
                    f"({city_filter}) and {INACTIVE_STATUS_FILTER} "
                    f"{delisted_extra}",
                    "ModificationTimestamp desc",
                ),
            ]

            for label, filter_expression, orderby in queries:
                self.stdout.write(f"{city} · {label}...")
                self.stdout.flush()
                try:
                    rows = fetch_property_page(
                        filter_expression=filter_expression,
                        select_fields=SELECT_FIELDS,
                        orderby=orderby,
                        top=min(1000, max_rows),
                        max_rows=max_rows,
                        progress_callback=self.stdout.write,
                    )
                except AmpreClientError as exc:
                    self.stderr.write(self.style.WARNING(f"  skipped: {exc}"))
                    continue

                self.stdout.write(
                    f"  upserting {len(rows):,} rows"
                    f"{'' if skip_media else ' (+ media fill)'}..."
                )
                self.stdout.flush()
                fetched += len(rows)
                c, u, s, m = self._bulk_upsert_rows(
                    rows,
                    skip_media=skip_media,
                )
                created += c
                updated += u
                skipped += s
                media_filled += m
                self.stdout.write(
                    f"  {len(rows):,} rows "
                    f"(+{c:,} / ~{u:,} / skip {s:,})"
                )

        ListingSyncStatus.objects.update_or_create(
            key="ampre_closed",
            defaults={
                "last_successful_at": timezone.now(),
                "listing_count": fetched,
            },
        )
        clear_listing_sync_status_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Fetched {fetched:,}. Created {created:,}, "
                f"updated {updated:,}, unchanged {skipped:,}. "
                f"Filled media for {media_filled:,}."
            )
        )

    def _bulk_upsert_rows(self, rows, *, skip_media: bool):
        """Insert/update a page of AMPRE rows. Never deletes Property."""
        keyed: dict[str, dict] = {}
        for row in rows:
            ampre_key = str(row.get("ListingKey") or "").strip()
            if not ampre_key:
                continue
            keyed[ampre_key] = row

        if not keyed:
            return 0, 0, 0, 0

        keys = list(keyed.keys())
        existing_qs = Property.objects.filter(
            Q(listing_key__in=keys) | Q(listing_id__in=keys)
        )
        by_listing_key: dict[str, Property] = {}
        by_listing_id: dict[str, Property] = {}
        for prop in existing_qs:
            if prop.listing_key:
                by_listing_key.setdefault(prop.listing_key, prop)
            if prop.listing_id:
                by_listing_id.setdefault(prop.listing_id, prop)

        to_create: list[Property] = []
        to_update: list[Property] = []
        media_candidates: list[Property] = []
        created = updated = skipped = media_filled = 0

        for ampre_key, row in keyed.items():
            defaults = map_ampre_inactive(row)
            existing = by_listing_key.get(ampre_key) or by_listing_id.get(
                ampre_key
            )

            if existing:
                new_mt = defaults.get("modification_timestamp")
                old_mt = existing.modification_timestamp
                # Skip property-field write when upstream has not moved,
                # but still queue the row for empty-gallery media fill.
                if (
                    old_mt is not None
                    and new_mt is not None
                    and old_mt == new_mt
                    and (existing.standard_status or "")
                    == (defaults.get("standard_status") or "")
                ):
                    skipped += 1
                    media_candidates.append(existing)
                    continue

                for field, value in defaults.items():
                    if field == "category_type":
                        continue
                    setattr(existing, field, value)
                to_update.append(existing)
                updated += 1
                media_candidates.append(existing)
            else:
                to_create.append(
                    Property(listing_key=ampre_key, **defaults)
                )
                created += 1

        if to_create:
            Property.objects.bulk_create(to_create, batch_size=1000)
            media_candidates.extend(to_create)

        if to_update:
            Property.objects.bulk_update(
                to_update,
                fields=_UPDATE_FIELDS,
                batch_size=1000,
            )

        if skip_media or not media_candidates:
            return created, updated, skipped, media_filled

        from django.db.models import Exists, OuterRef

        from mls.models import Media

        candidate_ids = [p.id for p in media_candidates if getattr(p, "id", None)]
        empty_ids = set(
            Property.objects.filter(id__in=candidate_ids)
            .annotate(
                _has_media=Exists(
                    Media.objects.filter(property_id=OuterRef("pk"))
                )
            )
            .filter(_has_media=False)
            .values_list("id", flat=True)
        )
        by_id = {p.id: p for p in media_candidates if getattr(p, "id", None)}
        empty_list = [
            by_id[i]
            for i in empty_ids
            if i in by_id and is_trreb_property(by_id[i])
        ]
        total_empty = len(empty_list)
        if total_empty:
            self.stdout.write(
                f"  filling media URLs for {total_empty:,} empty galleries "
                f"(AMPRE API only — no image download)..."
            )
            self.stdout.flush()

        from concurrent.futures import ThreadPoolExecutor, as_completed

        from django.db import connection

        def _fill(prop: Property) -> int:
            try:
                return refresh_property_media_from_ampre(
                    prop, verify_url=False
                )
            except (AmpreClientError, Exception) as exc:
                # Never let one bad AMPRE Media response abort the full sync.
                self.stderr.write(
                    self.style.WARNING(
                        f"  media skip {prop.listing_id or prop.listing_key}: {exc}"
                    )
                )
                return 0
            finally:
                connection.close()

        # Parallel URL fetches — bottleneck was serial AMPRE Media calls
        # plus an optional CDN probe (now disabled).
        workers = min(12, max(4, total_empty and 12))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_fill, prop) for prop in empty_list]
            for fut in as_completed(futures):
                written = fut.result() or 0
                if written:
                    media_filled += 1
                done += 1
                if done % 200 == 0 or done == total_empty:
                    self.stdout.write(
                        f"  media progress {done:,}/{total_empty:,} "
                        f"(filled {media_filled:,})"
                    )
                    self.stdout.flush()

        return created, updated, skipped, media_filled
