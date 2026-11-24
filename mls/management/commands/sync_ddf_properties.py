import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone

from mls.helpers import get_access_token
from mls.models import (
    ListingSyncStatus,
    Media,
    Property,
    Room,
)
from mls.services.ddf.client import fetch_all_properties, iter_property_pages
from mls.services.ddf.converters import (
    safe_bool,
    safe_decimal,
    safe_int,
    safe_str,
)
from mls.services.ddf.mapper import map_property_defaults
from mls.services.map_aggregates import rebuild_h3_aggregates
from mls.snapshot_utils import (
    bulk_record_listing_first_seen,
    bulk_record_property_snapshots,
)


class Command(BaseCommand):
    """
    Sync DDF listings into the Property table. Append-only.

    This command NEVER deletes Property rows. Every sync either INSERTS
    new listings or UPDATES existing ones; stale rows are left in place.
    The only deletions anywhere in this file are on Room / Media child
    rows inside process_batch, and those are immediately re-created from
    the fresh DDF payload (refresh semantics, not purge).
    """

    help = "Sync DDF listings (full catalogue or N-hour window). Append-only."

    INCREMENTAL_OVERLAP_MINUTES = 10

    GTA_CITIES = (
        "Toronto",
        "Mississauga",
        "Brampton",
        "Vaughan",
        "Markham",
        "Richmond Hill",
        "Oakville",
        "Burlington",
        "Milton",
        "Halton Hills",
        "Caledon",
        "King",
        "Aurora",
        "Newmarket",
        "Georgina",
        "East Gwillimbury",
        "Whitchurch-Stouffville",
        "Pickering",
        "Ajax",
        "Whitby",
        "Oshawa",
        "Clarington",
        "Scugog",
        "Uxbridge",
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help=(
                "Fetch the entire catalogue, ignoring the incremental "
                "watermark. Use for manual full resyncs."
            ),
        )

        parser.add_argument(
            "--window-hours",
            type=int,
            default=0,
            help=(
                "Fetch listings modified in the last N hours. "
                "Overrides the default watermark-based incremental. "
                "0 (default) keeps watermark behavior. The scheduled "
                "Celery task passes 24."
            ),
        )

        parser.add_argument(
            "--threads",
            type=int,
            default=10,
            help=(
                "Deprecated. Kept temporarily for compatibility. "
                "DDF pagination is sequential."
            ),
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Properties per DB batch.",
        )

        parser.add_argument(
            "--max-pages",
            type=int,
            default=0,
            help=(
                "Optional safety cap for pages during testing. "
                "0 means no cap."
            ),
        )

        parser.add_argument(
            "--insert-new-only",
            action="store_true",
            help=(
                "Insert unseen listing keys only; never update "
                "existing DDF rows."
            ),
        )

        parser.add_argument(
            "--priority-cache",
            action="store_true",
            help=(
                "Seed GTA listings first, followed by the rest "
                "of Ontario."
            ),
        )

        parser.add_argument(
            "--max-pages-per-tier",
            type=int,
            default=100,
            help=(
                "Maximum 100-listing pages to fetch per priority "
                "tier (default: 100)."
            ),
        )

    def build_incremental_filter(self):
        """
        Build the DDF filter used for an incremental sync.

        The overlap window helps avoid missing records modified close
        to the boundary between two sync runs.
        """
        latest_property = (
            Property.objects
            .filter(category_type=Property.DDF)
            .order_by("-modification_timestamp")
            .first()
        )

        latest_timestamp = (
            latest_property.modification_timestamp
            if latest_property
            else None
        )

        cutoff = (
            latest_timestamp or timezone.now()
        ) - timedelta(
            minutes=self.INCREMENTAL_OVERLAP_MINUTES
        )

        return (
            "ModificationTimestamp gt "
            f"{cutoff.isoformat()}"
        )

    def handle(self, *args, **options):
        start_time = time.time()

        if options["full"] and options["window_hours"]:
            raise CommandError(
                "--full and --window-hours are mutually exclusive."
            )

        if options["window_hours"] < 0:
            raise CommandError(
                "--window-hours must be >= 0."
            )

        if options["max_pages_per_tier"] < 1:
            raise CommandError(
                "--max-pages-per-tier must be at least 1."
            )

        cache_is_empty = not Property.objects.filter(
            category_type=Property.DDF
        ).exists()

        token = get_access_token()

        if not token:
            self.stderr.write(
                self.style.ERROR(
                    "Failed to get access token."
                )
            )
            return

        headers = {
            "Authorization": f"Bearer {token}",
        }

        self.stdout.write(
            "Downloading DDF properties..."
        )

        if options["priority_cache"]:
            downloaded_count, page_count = (
                self.sync_priority_cache_in_stages(
                    headers=headers,
                    max_pages=(
                        options["max_pages"]
                        or options["max_pages_per_tier"]
                    ),
                    batch_size=options["batch_size"],
                    insert_new_only=options[
                        "insert_new_only"
                    ],
                )
            )

        else:
            max_pages = options["max_pages"]

            if options["full"]:
                filter_expression = None
                self.stdout.write(
                    "--full: fetching the entire catalogue "
                    f"(cap: {max_pages or 'none'} pages)."
                )
            elif options["window_hours"]:
                cutoff = timezone.now() - timedelta(
                    hours=options["window_hours"]
                )
                filter_expression = (
                    "ModificationTimestamp gt "
                    f"{cutoff.isoformat()}"
                )
                self.stdout.write(
                    f"--window-hours={options['window_hours']}: "
                    f"fetching listings modified since {cutoff.isoformat()}."
                )
            else:
                filter_expression = (
                    self.build_incremental_filter()
                )

            if cache_is_empty:
                # First-ever seed: pull the full catalogue.
                # Only an explicit --max-pages still bounds it (for testing).
                filter_expression = None
                self.stdout.write(
                    "DDF cache is empty; seeding the full catalogue."
                )

            # STREAMING UPSERT.
            # Each page is committed to the DB before the next one is
            # requested. Peak memory stays constant (~5 MB) regardless of
            # catalogue size, rows land in near real time, and committed
            # work survives interruption.
            connections.close_all()
            downloaded_count = 0
            page_count = 0
            pages_iter = iter_property_pages(
                headers=headers,
                filter_expression=filter_expression,
                max_pages=max_pages,
                progress_callback=self.stdout.write,
            )
            for page in pages_iter:
                page_count += 1
                if not page:
                    continue
                try:
                    self.process_batch(
                        page,
                        insert_new_only=options["insert_new_only"],
                    )
                except Exception as exc:
                    self.stderr.write(
                        self.style.WARNING(
                            f"Page {page_count:,} upsert failed: {exc}. "
                            "Continuing with next page."
                        )
                    )
                    continue
                downloaded_count += len(page)

            self.stdout.write(
                f"Streamed {page_count:,} pages "
                f"containing {downloaded_count:,} listings "
                "into the DB."
            )

            if downloaded_count == 0:
                self.stdout.write(
                    "No properties returned."
                )
                return

        self.stdout.write(
            "Rebuilding H3 map aggregates..."
        )

        aggregate_cells = (
            rebuild_h3_aggregates()
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Built {aggregate_cells:,} "
                "aggregate cells."
            )
        )

        # Open-house tab reads Postgres OpenHouse rows; keep them in sync
        # with the Active catalogue after every property pull.
        try:
            self.sync_open_houses(headers=headers)
        except Exception as exc:
            self.stderr.write(
                self.style.WARNING(
                    f"Open House sync skipped after property pull: {exc}"
                )
            )

        # DDF is Active-only; Sold / De-listed tabs need AMPRE inactive rows.
        try:
            from django.core.management import call_command

            call_command(
                "sync_ampre_closed",
                days=90,
                max_rows_per_city=500,
                stdout=self.stdout,
                stderr=self.stderr,
            )
        except Exception as exc:
            self.stderr.write(
                self.style.WARNING(
                    f"AMPRE Closed/De-listed sync skipped: {exc}"
                )
            )

        ListingSyncStatus.objects.update_or_create(
            key="ddf_properties",
            defaults={
                "last_successful_at": (
                    timezone.now()
                ),
                "listing_count": (
                    downloaded_count
                ),
            },
        )
        from mls.services.listing_sync_status import clear_cache as clear_listing_sync_status_cache

        clear_listing_sync_status_cache()

        elapsed = time.time() - start_time

        rate = (
            downloaded_count / elapsed
            if elapsed > 0
            else 0
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"COMPLETED in {elapsed:.1f} "
                f"seconds ({rate:.1f} props/sec)"
            )
        )

    def sync_priority_cache_in_stages(
        self,
        headers,
        max_pages,
        batch_size,
        insert_new_only,
    ):
        """
        Fetch and commit each priority tier before requesting
        the next one.

        This ensures listings from completed tiers remain saved
        if a later DDF request fails or the command is interrupted.
        """
        downloaded_count = 0
        page_count = 0
        seen_listing_keys = set()

        gta_city_page_limit = max(
            1,
            max_pages // len(self.GTA_CITIES),
        )

        gta_tiers = tuple(
            (
                f"GTA: {city}",
                f"City eq '{city}'",
                gta_city_page_limit,
            )
            for city in self.GTA_CITIES
        )

        tiers = gta_tiers + (
            (
                "remaining Ontario",
                "StateOrProvince eq 'Ontario'",
                max_pages,
            ),
        )

        for (
            tier_name,
            filter_expression,
            tier_page_limit,
        ) in tiers:

            self.stdout.write(
                f"Fetching {tier_name} priority "
                f"tier (up to "
                f"{tier_page_limit * 100:,} "
                "listings)..."
            )

            properties, tier_pages = (
                fetch_all_properties(
                    headers=headers,
                    filter_expression=(
                        filter_expression
                    ),
                    max_pages=tier_page_limit,
                    progress_callback=(
                        self.stdout.write
                    ),
                )
            )

            page_count += tier_pages

            unique_properties = []

            for property_data in properties:
                listing_key = (
                    property_data.get(
                        "ListingKey"
                    )
                )

                if (
                    listing_key
                    and listing_key
                    not in seen_listing_keys
                ):
                    seen_listing_keys.add(
                        listing_key
                    )
                    unique_properties.append(
                        property_data
                    )

            downloaded_count += len(
                unique_properties
            )

            if not unique_properties:
                self.stdout.write(
                    f"{tier_name}: no new "
                    "listing keys to write."
                )
                continue

            self.stdout.write(
                f"{tier_name}: committing "
                f"{len(unique_properties):,} "
                "listings before continuing..."
            )

            connections.close_all()

            self.bulk_upsert(
                unique_properties,
                batch_size=batch_size,
                insert_new_only=(
                    insert_new_only
                ),
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"{tier_name}: committed "
                    f"{len(unique_properties):,} "
                    "listings."
                )
            )

        self.stdout.write(
            "Downloaded and checkpointed "
            f"{page_count:,} pages containing "
            f"{downloaded_count:,} unique "
            "listings."
        )

        return (
            downloaded_count,
            page_count,
        )

    def bulk_upsert(
        self,
        properties_data,
        batch_size=5000,
        insert_new_only=False,
    ):
        """
        Persist DDF records in independent batches.

        Separate transactions avoid one enormous transaction
        consuming excessive temporary PostgreSQL storage.
        """
        total_batches = (
            len(properties_data)
            + batch_size
            - 1
        ) // batch_size

        for batch_number, start in enumerate(
            range(
                0,
                len(properties_data),
                batch_size,
            ),
            start=1,
        ):
            batch = properties_data[
                start:start + batch_size
            ]

            self.process_batch(
                batch,
                insert_new_only=(
                    insert_new_only
                ),
            )

            self.stdout.write(
                f"Processed batch "
                f"{batch_number}/"
                f"{total_batches}"
            )

    @transaction.atomic
    def process_batch(
        self,
        batch,
        insert_new_only=False,
    ):
        listing_keys = [
            data["ListingKey"]
            for data in batch
            if data.get("ListingKey")
        ]

        existing = (
            Property.objects
            .filter(
                listing_key__in=listing_keys
            )
            .in_bulk(
                field_name="listing_key"
            )
        )

        property_objs = []
        properties_to_update = []

        first_seen_rows = []
        snapshot_rows = []

        # Store child payloads by listing key rather than constructing
        # Room/Media rows immediately. This ensures new Property rows
        # have database IDs before their children are created.
        rooms_by_listing_key = {}
        media_by_listing_key = {}

        for data in batch:
            key = data.get(
                "ListingKey"
            )

            if not key:
                continue

            defaults = (
                map_property_defaults(
                    data
                )
            )

            first_seen_rows.append(
                (
                    key,
                    defaults.get(
                        "modification_timestamp"
                    )
                    or defaults.get(
                        "original_entry_timestamp"
                    ),
                )
            )

            if key in existing:
                if insert_new_only:
                    continue

                prop = existing[key]

                old_price = prop.list_price

                old_status = (
                    prop.standard_status
                    or ""
                ).strip()

                old_modification_timestamp = (
                    prop.modification_timestamp
                )

                new_price = defaults.get(
                    "list_price"
                )

                new_status = (
                    defaults.get(
                        "standard_status"
                    )
                    or ""
                ).strip()

                new_modification_timestamp = (
                    defaults.get(
                        "modification_timestamp"
                    )
                )

                # Track list-price cuts so the UI Price Drop badge and
                # HouseSigma-style history stay honest after sync.
                if (
                    old_price is not None
                    and new_price is not None
                    and old_price != new_price
                ):
                    defaults["previous_list_price"] = old_price
                    defaults["price_change_timestamp"] = (
                        new_modification_timestamp
                        or timezone.now()
                    )

                snapshot_changed = (
                    old_price != new_price
                    or old_status
                    != new_status
                    or old_modification_timestamp
                    != new_modification_timestamp
                )

                for field, value in (
                    defaults.items()
                ):
                    setattr(
                        prop,
                        field,
                        value,
                    )

                properties_to_update.append(
                    prop
                )

                if snapshot_changed:
                    snapshot_rows.append(
                        (
                            key,
                            new_price,
                            new_status,
                            new_modification_timestamp,
                        )
                    )

            else:
                prop = Property(
                    listing_key=key,
                    **defaults,
                )

                property_objs.append(
                    prop
                )

                snapshot_rows.append(
                    (
                        key,
                        defaults.get(
                            "list_price"
                        ),
                        defaults.get(
                            "standard_status"
                        )
                        or "",
                        defaults.get(
                            "modification_timestamp"
                        ),
                    )
                )

            rooms_by_listing_key[key] = (
                data.get("Rooms")
                or []
            )

            media_by_listing_key[key] = (
                data.get("Media")
                or []
            )

        if property_objs:
            Property.objects.bulk_create(
                property_objs,
                ignore_conflicts=False,
            )

        if properties_to_update:
            update_fields = [
                field.name
                for field
                in Property._meta.fields
                if field.name
                not in {
                    "id",
                    "listing_key",
                }
            ]

            Property.objects.bulk_update(
                properties_to_update,
                fields=update_fields,
            )

        affected_listing_keys = (
            set(
                rooms_by_listing_key.keys()
            )
            | set(
                media_by_listing_key.keys()
            )
        )

        if affected_listing_keys:
            affected_properties = (
                Property.objects
                .filter(
                    listing_key__in=(
                        affected_listing_keys
                    )
                )
                .in_bulk(
                    field_name="listing_key"
                )
            )

            affected_property_ids = [
                prop.id
                for prop
                in affected_properties.values()
            ]

            if affected_property_ids:
                Room.objects.filter(
                    property_id__in=(
                        affected_property_ids
                    )
                ).delete()

                Media.objects.filter(
                    property_id__in=(
                        affected_property_ids
                    )
                ).delete()

            room_objs = []

            for (
                listing_key,
                rooms,
            ) in rooms_by_listing_key.items():
                prop = (
                    affected_properties.get(
                        listing_key
                    )
                )

                if prop is None:
                    continue

                for room_data in rooms:
                    room_objs.append(
                        Room(
                            property=prop,
                            room_type=safe_str(
                                room_data.get(
                                    "RoomType"
                                )
                            ),
                            room_length=(
                                safe_decimal(
                                    room_data.get(
                                        "RoomLength"
                                    )
                                )
                            ),
                            room_width=(
                                safe_decimal(
                                    room_data.get(
                                        "RoomWidth"
                                    )
                                )
                            ),
                            room_level=safe_str(
                                room_data.get(
                                    "RoomLevel"
                                )
                            ),
                            room_description=(
                                safe_str(
                                    room_data.get(
                                        "RoomDescription"
                                    )
                                )
                            ),
                            room_dimensions=(
                                safe_str(
                                    room_data.get(
                                        "RoomDimensions"
                                    )
                                )
                            ),
                            room_length_width_units=(
                                safe_str(
                                    room_data.get(
                                        "RoomLengthWidthUnits"
                                    )
                                )
                            ),
                        )
                    )

            media_objs = []

            for (
                listing_key,
                media_items,
            ) in media_by_listing_key.items():
                prop = (
                    affected_properties.get(
                        listing_key
                    )
                )

                if prop is None:
                    continue

                for media_data in media_items:
                    media_objs.append(
                        Media(
                            property=prop,
                            media_url=safe_str(
                                media_data.get(
                                    "MediaURL"
                                )
                            ),
                            media_category=(
                                safe_str(
                                    media_data.get(
                                        "MediaCategory"
                                    )
                                )
                            ),
                            is_preferred=(
                                safe_bool(
                                    media_data.get(
                                        "PreferredPhotoYN"
                                    )
                                )
                            ),
                            order=safe_int(
                                media_data.get(
                                    "Order"
                                ),
                                999,
                            ),
                        )
                    )

            if room_objs:
                Room.objects.bulk_create(
                    room_objs,
                    ignore_conflicts=True,
                )

            if media_objs:
                Media.objects.bulk_create(
                    media_objs,
                    ignore_conflicts=True,
                )

            # DDF CDN URLs for TRREB listings often 404 while AMPRE still
            # hosts the same photos. Rebuild gallery rows from AMPRE when
            # the preferred DDF URL is already dead so sync does not leave
            # (or re-introduce) blank house-icon galleries.
            if affected_properties:
                from mls.services.ampre_media import repair_dead_ddf_media

                repaired = repair_dead_ddf_media(
                    affected_properties.values(),
                    only_if_dead=True,
                )
                if repaired:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Refreshed gallery URLs from AMPRE for "
                            f"{repaired} listing(s) with dead DDF CDN links."
                        )
                    )

        if first_seen_rows:
            bulk_record_listing_first_seen(
                first_seen_rows
            )

        if snapshot_rows:
            bulk_record_property_snapshots(
                snapshot_rows
            )

    def sync_open_houses(self, headers):
        """Persist upcoming Open House rows and refresh the Redis cache."""
        from mls.services.ddf.open_house_cache import refresh_open_house_cache

        self.stdout.write("Syncing Open Houses...")
        result = refresh_open_house_cache(
            headers=headers,
            progress_callback=self.stdout.write,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Open Houses synced: "
                f"{result.get('stored_count', 0):,} rows stored, "
                f"{result.get('cached_count', 0):,} cached, "
                f"{result.get('properties_upserted', 0):,} parents upserted."
            )
        )
        return result


# Append-only DDF sync — no Property rows are ever deleted by this file.
#
# Incremental sync (watermark-based):
#   python manage.py sync_ddf_properties --batch-size 8000
#
# Full catalogue sync:
#   python manage.py sync_ddf_properties --full --batch-size 8000
#
# Scheduled 24h window (what the Celery beat task uses):
#   python manage.py sync_ddf_properties --window-hours 24 --batch-size 8000
#
# Testing with a page cap:
#   python manage.py sync_ddf_properties --max-pages 1 --batch-size 500
#
# Priority GTA/Ontario cache:
#   python manage.py sync_ddf_properties --priority-cache
