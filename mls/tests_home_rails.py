"""Homepage rails: Featured listings and the New Pre-construction ordering."""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import Content, PreComProperty, Property

FEATURED_URL = "/api/mls/properties/featured-properties/"
PRECON_URL = "/api/mls/precon-properties/"


def _listing(key, *, days_old=1, status="Active", remarks="", **extra):
    return Property.objects.create(
        listing_key=key,
        city="Toronto",
        state_or_province="ON",
        list_price=800000,
        standard_status=status,
        public_remarks=remarks,
        original_entry_timestamp=timezone.now() - timedelta(days=days_old),
        modification_timestamp=timezone.now() - timedelta(days=days_old),
        category_type=Property.DDF,
        **extra,
    )


def _curated_listing(key, *, list_price=800000, days_old=1, **extra):
    year = timezone.now().year
    defaults = {
        "structure_type": "House",
        "property_attached_yn": False,
        "year_built": year - 1,
        "stories": 2,
        "above_grade_finished_area": 2200,
        "list_price": list_price,
        "days_old": days_old,
    }
    defaults.update(extra)
    return _listing(key, **defaults)


class FeaturedPropertiesTests(TestCase):
    def setUp(self):
        cache.clear()

    def keys(self, **params):
        response = self.client.get(FEATURED_URL, params)
        self.assertEqual(response.status_code, 200)
        return [(r["listing_key"], r["featured_source"]) for r in response.json()["results"]]

    def test_pinned_first_in_featured_order_then_exclusive_fill(self):
        _listing("pin-b", is_featured=True, featured_order=2)
        _listing("pin-a", is_featured=True, featured_order=1, days_old=9)
        _listing("pin-unordered", is_featured=True)
        _listing("excl", remarks="EXCLUSIVE to our brokerage: corner lot")
        _listing("plain")

        self.assertEqual(
            self.keys(limit=5),
            [
                ("pin-a", "pinned"),
                ("pin-b", "pinned"),
                ("pin-unordered", "pinned"),
                ("excl", "exclusive"),
            ],
        )

    def test_expired_and_inactive_pins_are_skipped(self):
        _listing("expired", is_featured=True, featured_until=timezone.now() - timedelta(hours=1))
        _listing("sold", is_featured=True, status="Sold")
        _listing("pending", is_featured=True, status="Pending")
        _listing("live", is_featured=True, featured_until=timezone.now() + timedelta(days=3))
        _listing("sold-excl", status="Closed", remarks="Exclusive: just sold")

        self.assertEqual(self.keys(limit=6), [("live", "pinned")])

    def test_fill_false_returns_only_pinned(self):
        _listing("pin", is_featured=True)
        _listing("excl", remarks="exclusive listing")
        self.assertEqual(self.keys(limit=6, fill="false"), [("pin", "pinned")])

    def test_limit_caps_pinned(self):
        for i in range(4):
            _listing(f"pin-{i}", is_featured=True, featured_order=i + 1)
        response = self.client.get(FEATURED_URL, {"limit": 2}).json()
        self.assertEqual([r["listing_key"] for r in response["results"]], ["pin-0", "pin-1"])
        self.assertEqual(response["pinned_count"], 2)

    def test_default_limit_is_twelve(self):
        for i in range(15):
            _listing(
                f"excl-{i}",
                remarks="EXCLUSIVE to our brokerage: corner lot",
                list_price=500000 + i * 1000,
                days_old=i + 1,
            )
        response = self.client.get(FEATURED_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 12)

    def test_bad_limit_is_400(self):
        self.assertEqual(self.client.get(FEATURED_URL, {"limit": "abc"}).status_code, 400)

    def test_history_city_fill_follows_admin_pins(self):
        _listing("pin", is_featured=True, featured_order=1, city="Toronto", list_price=900000)
        _listing("hist-a", city="Oakville", days_old=2, list_price=700000)
        _listing("hist-b", city="Oakville", days_old=1, list_price=600000)
        _listing("excl", remarks="EXCLUSIVE to our brokerage: corner lot", city="Toronto")

        response = self.client.get(FEATURED_URL, {"limit": 3, "cities": "Oakville"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pinned_count"], 1)
        self.assertTrue(body["has_search_history"])
        self.assertGreaterEqual(body["history_count"], 1)
        sources = [row["featured_source"] for row in body["results"]]
        self.assertEqual(sources[0], "pinned")
        self.assertIn("history", sources)
        # History stage sorts price low → high after the pin.
        hist_keys = [r["listing_key"] for r in body["results"] if r["featured_source"] == "history"]
        self.assertEqual(hist_keys[:2], ["hist-b", "hist-a"])

    def test_pinned_rental_is_excluded(self):
        _listing("rent-pin", is_featured=True, featured_order=1, lease_amount=2800)
        _listing("sale-pin", is_featured=True, featured_order=2)
        self.assertEqual(self.keys(limit=6, fill="false"), [("sale-pin", "pinned")])

    def test_no_history_uses_curated_before_exclusive(self):
        year = timezone.now().year
        _curated_listing("curated-hit", list_price=750000, days_old=2)
        _listing(
            "curated-miss-old",
            structure_type="House",
            property_attached_yn=False,
            year_built=year - 10,
            stories=2,
            above_grade_finished_area=2500,
            days_old=1,
        )
        _listing(
            "curated-miss-condo",
            structure_type="Apartment",
            property_attached_yn=True,
            year_built=year - 1,
            stories=2,
            above_grade_finished_area=2500,
            days_old=1,
        )
        _listing(
            "curated-miss-small",
            structure_type="House",
            property_attached_yn=False,
            year_built=year - 1,
            stories=2,
            above_grade_finished_area=1200,
            days_old=1,
        )
        _listing(
            "curated-miss-storeys",
            structure_type="House",
            property_attached_yn=False,
            year_built=year - 1,
            stories=1,
            above_grade_finished_area=2500,
            days_old=1,
        )
        _listing(
            "curated-rent",
            structure_type="House",
            property_attached_yn=False,
            year_built=year - 1,
            stories=2,
            above_grade_finished_area=2500,
            lease_amount=3200,
            days_old=1,
        )
        _listing("excl", remarks="EXCLUSIVE to our brokerage: corner lot", days_old=3)

        keys = self.keys(limit=4)
        self.assertEqual(keys[0], ("curated-hit", "curated"))
        self.assertEqual(keys[1], ("excl", "exclusive"))
        sources = {source for _, source in keys}
        self.assertNotIn("local", sources)
        self.assertNotIn("history", sources)

    def test_ip_city_local_then_curated_when_no_search_history(self):
        _listing("ip-local", city="Mississauga", days_old=1, list_price=650000)
        _curated_listing("curated-hit", city="Toronto", list_price=900000, days_old=2)
        _listing(
            "excl",
            remarks="EXCLUSIVE to our brokerage: corner lot",
            city="Toronto",
            days_old=3,
            list_price=500000,
        )

        response = self.client.get(
            FEATURED_URL,
            {"limit": 3},
            HTTP_CF_IPCITY="Mississauga",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        pairs = [(r["listing_key"], r["featured_source"]) for r in body["results"]]
        self.assertEqual(
            pairs,
            [
                ("ip-local", "local"),
                ("curated-hit", "curated"),
                ("excl", "exclusive"),
            ],
        )
        self.assertFalse(body["has_search_history"])
        self.assertEqual(body["local_count"], 1)
        self.assertEqual(body["curated_count"], 1)

    def test_search_history_skips_curated_and_uses_exclusive(self):
        _listing("oak-local", city="Oakville", days_old=1, list_price=700000)
        _curated_listing("curated-hit", city="Toronto", list_price=500000, days_old=2)
        _listing(
            "excl",
            remarks="EXCLUSIVE to our brokerage: corner lot",
            city="Toronto",
            days_old=3,
            list_price=600000,
        )

        pairs = self.keys(limit=3, cities="Oakville")
        self.assertEqual(
            pairs,
            [
                ("oak-local", "history"),
                ("excl", "exclusive"),
            ],
        )
        self.assertNotIn(("curated-hit", "curated"), pairs)

    def test_history_beds_filter_is_applied(self):
        _listing("oak-2bed", city="Oakville", bedrooms_total=2, list_price=500000)
        _listing("oak-4bed", city="Oakville", bedrooms_total=4, list_price=600000)
        pairs = self.keys(limit=3, cities="Oakville", beds_min=3)
        keys = {key for key, _ in pairs}
        self.assertIn("oak-4bed", keys)
        self.assertNotIn("oak-2bed", keys)

    def test_local_and_exclusive_rentals_are_excluded(self):
        _listing("oak-rent", city="Oakville", lease_amount=2500, days_old=1)
        _listing("oak-sale", city="Oakville", days_old=2)
        _listing(
            "excl-rent",
            remarks="EXCLUSIVE to our brokerage: rental suite",
            lease_amount=3000,
            days_old=1,
        )
        _listing("excl-sale", remarks="EXCLUSIVE to our brokerage: corner lot", days_old=3)

        pairs = self.keys(limit=4, cities="Oakville")
        keys = {key for key, _ in pairs}
        self.assertIn("oak-sale", keys)
        self.assertIn("excl-sale", keys)
        self.assertNotIn("oak-rent", keys)
        self.assertNotIn("excl-rent", keys)

    def test_curated_price_sorts_low_to_high(self):
        _curated_listing("curated-high", list_price=1200000, days_old=1)
        _curated_listing("curated-low", list_price=700000, days_old=2)
        pairs = self.keys(limit=2)
        self.assertEqual(
            pairs,
            [
                ("curated-low", "curated"),
                ("curated-high", "curated"),
            ],
        )


class ExclusivePropertiesReadOnlyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_listing_the_rail_does_not_retag_rows(self):
        row = _listing("excl", remarks="Exclusive offering in Leslieville")
        response = self.client.get("/api/mls/properties/exclusive-properties/", {"limit": 6})
        self.assertEqual(response.status_code, 200)
        self.assertIn("excl", [r["listing_key"] for r in response.json()["results"]])
        row.refresh_from_db()
        self.assertEqual(row.category_type, Property.DDF)


class PreconOrderingTests(TestCase):
    def setUp(self):
        now = timezone.now()

        def project(wp_id, *, published_days_ago, stage="", title=None, **extra):
            content = Content.objects.create(
                wp_id=wp_id,
                content_type=Content.PROPERTY,
                title=title or f"Project {wp_id}",
                slug=f"project-{wp_id}",
                status=Content.PUBLISH,
                published_at=now - timedelta(days=published_days_ago),
            )
            # Saving a property Content may already have created its row.
            project, _ = PreComProperty.objects.update_or_create(
                content=content, defaults={"sales_stage": stage, **extra}
            )
            return project

        # Created in this order, so the legacy "-id" order is the reverse.
        self.newest = project(1, published_days_ago=1, stage=PreComProperty.SALES_STAGE_NOW_SELLING)
        self.sold = project(2, published_days_ago=2, stage=PreComProperty.SALES_STAGE_SOLD_OUT)
        self.oldest = project(3, published_days_ago=30, stage=PreComProperty.SALES_STAGE_COMING_SOON)
        self.pinned = project(4, published_days_ago=60, is_featured=True, featured_order=1)

    def wp_ids(self, **params):
        response = self.client.get(PRECON_URL, params)
        self.assertEqual(response.status_code, 200)
        return [r["wp_id"] for r in response.json()["results"]]

    def test_default_order_unchanged(self):
        self.assertEqual(self.wp_ids(), [4, 3, 2, 1])

    def test_newest_orders_by_published_at(self):
        self.assertEqual(self.wp_ids(ordering="newest"), [1, 2, 3, 4])

    def test_featured_puts_pins_first_and_excludes_sold_out(self):
        self.assertEqual(self.wp_ids(ordering="featured", exclude_stage="sold_out"), [4, 1, 3])

    def test_list_exposes_is_featured(self):
        rows = self.client.get(PRECON_URL, {"ordering": "featured"}).json()["results"]
        self.assertTrue(rows[0]["is_featured"])
        self.assertFalse(rows[1]["is_featured"])

    def test_no_history_is_unfiltered_and_flags_false(self):
        response = self.client.get(
            PRECON_URL,
            {"ordering": "featured", "exclude_stage": "sold_out"},
            HTTP_CF_IPCITY="Mississauga",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["has_search_history"])
        self.assertEqual(body["cities"], [])
        # IP alone must not city-filter — same featured order as without IP.
        self.assertEqual([r["wp_id"] for r in body["results"]], [4, 1, 3])


class PreconSearchHistoryFilterTests(TestCase):
    def setUp(self):
        now = timezone.now()

        def project(wp_id, *, title, address="", developer="", **extra):
            content = Content.objects.create(
                wp_id=wp_id,
                content_type=Content.PROPERTY,
                title=title,
                slug=f"project-{wp_id}",
                status=Content.PUBLISH,
                published_at=now - timedelta(days=wp_id),
            )
            project, _ = PreComProperty.objects.update_or_create(
                content=content,
                defaults={
                    "address": address,
                    "developer_name": developer,
                    "sales_stage": PreComProperty.SALES_STAGE_NOW_SELLING,
                    **extra,
                },
            )
            return project

        self.oak = project(
            10,
            title="Oakville Towers",
            address="123 Lakeshore Rd, Oakville ON",
            bedrooms=2,
            bathrooms="2.0",
            price=700000,
        )
        self.miss = project(
            11,
            title="Square One Condos",
            address="100 City Centre Dr, Mississauga ON",
            bedrooms=3,
            bathrooms="2.0",
            price=900000,
        )
        self.toronto = project(
            12,
            title="King West Lofts",
            address="500 King St W, Toronto ON",
            bedrooms=1,
            bathrooms="1.0",
            price=500000,
            is_featured=True,
            featured_order=1,
        )

    def results(self, **params):
        response = self.client.get(PRECON_URL, params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_cities_filters_to_matching_place(self):
        body = self.results(ordering="featured", cities="Oakville")
        self.assertTrue(body["has_search_history"])
        self.assertEqual(body["cities"], ["Oakville"])
        self.assertEqual([r["wp_id"] for r in body["results"]], [10])

    def test_multi_city_or_match(self):
        body = self.results(ordering="featured", cities="Oakville,Mississauga")
        ids = {r["wp_id"] for r in body["results"]}
        self.assertEqual(ids, {10, 11})
        self.assertEqual(set(body["cities"]), {"Oakville", "Mississauga"})

    def test_beds_and_price_filters(self):
        body = self.results(
            ordering="featured",
            cities="Oakville,Mississauga,Toronto",
            beds_min=2,
            price_min=650000,
            price_max=850000,
        )
        self.assertEqual([r["wp_id"] for r in body["results"]], [10])

    def test_ip_header_alone_does_not_filter(self):
        body = self.results(ordering="featured")
        unfiltered = {r["wp_id"] for r in body["results"]}
        with_ip = self.client.get(
            PRECON_URL,
            {"ordering": "featured"},
            HTTP_CF_IPCITY="Oakville",
        ).json()
        self.assertFalse(with_ip["has_search_history"])
        self.assertEqual(with_ip["cities"], [])
        self.assertEqual({r["wp_id"] for r in with_ip["results"]}, unfiltered)
        self.assertIn(12, unfiltered)
        self.assertIn(11, unfiltered)
        self.assertIn(10, unfiltered)
