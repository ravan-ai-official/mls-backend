from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from mls.models import Property, PropertySnapshot
from mls.services.sold_access import (
    is_sold_property,
    locked_sold_feed_stub,
    redact_sold_history_payload,
    redact_sold_property_payload,
    request_is_sold_query,
    viewer_can_view_sold,
)


class SoldAccessHelperTests(SimpleTestCase):
    def test_viewer_can_view_sold(self):
        class Anon:
            is_authenticated = False

        class User:
            is_authenticated = True

        self.assertFalse(viewer_can_view_sold(Anon()))
        self.assertTrue(viewer_can_view_sold(User()))

    def test_request_is_sold_query(self):
        self.assertTrue(request_is_sold_query({"transaction_type": "sold"}))
        self.assertTrue(request_is_sold_query({"status_group": "sold"}))
        self.assertTrue(request_is_sold_query({"status": "Closed"}))
        self.assertTrue(request_is_sold_query({"sold_within_days": "30"}))
        self.assertFalse(request_is_sold_query({"transaction_type": "sale"}))
        self.assertFalse(request_is_sold_query({}))

    def test_is_sold_property(self):
        self.assertTrue(is_sold_property("Closed"))
        self.assertTrue(is_sold_property("Sold"))
        self.assertFalse(is_sold_property("Active"))

    def test_redact_clears_prices(self):
        out = redact_sold_property_payload(
            {
                "listing_key": "k1",
                "close_price": 900000,
                "list_price": 950000,
                "public_remarks": "secret",
                "media": [{"url": "a"}, {"url": "b"}],
                "rooms": [{"room_type": "Kitchen"}],
            }
        )
        self.assertTrue(out["sold_locked"])
        self.assertEqual(out["access"], "login_required")
        self.assertIsNone(out["close_price"])
        self.assertIsNone(out["list_price"])
        self.assertIsNone(out["public_remarks"])
        self.assertEqual(out["rooms"], [])
        self.assertEqual(len(out["media"]), 1)

    def test_redact_history(self):
        out = redact_sold_history_payload(
            {
                "snapshots": [{"list_price": 1, "standard_status": "Closed"}],
                "history": [{"price": 2, "event": "Sold"}],
            }
        )
        self.assertIsNone(out["snapshots"][0]["list_price"])
        self.assertIsNone(out["history"][0]["price"])
        self.assertTrue(out["sold_locked"])

    def test_locked_stub(self):
        stub = locked_sold_feed_stub(feed="sold_below_purchase")
        self.assertTrue(stub["sold_locked"])
        self.assertEqual(stub["results"], [])


class SoldAccessAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.sold = Property.objects.create(
            listing_key="sold-gate-1",
            listing_id="XSELL1",
            city="Toronto",
            state_or_province="ON",
            standard_status="Closed",
            list_price=Decimal("1000000"),
            close_price=Decimal("975000"),
            close_date=date(2026, 1, 15),
            public_remarks="Sold remarks",
            modification_timestamp=timezone.now(),
            category_type=Property.DDF,
        )
        PropertySnapshot.objects.create(
            listing_key="sold-gate-1",
            list_price=Decimal("1000000"),
            standard_status="Closed",
        )

    def test_anonymous_detail_redacts_sold(self):
        response = self.client.get("/api/mls/properties/sold-gate-1/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("sold_locked"))
        self.assertIsNone(body.get("close_price"))
        self.assertIsNone(body.get("list_price"))
        self.assertIsNone(body.get("public_remarks"))

    def test_authenticated_detail_shows_sold_price(self):
        user = get_user_model().objects.create_user(
            username="soldviewer", password="pass12345"
        )
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/mls/properties/sold-gate-1/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body.get("sold_locked"))
        self.assertEqual(float(body["close_price"]), 975000.0)

    def test_anonymous_sold_filter_locks_results(self):
        response = self.client.get(
            "/api/mls/properties/filter/",
            {"transaction_type": "sold", "limit": 10, "allow_fallback": "false"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("sold_locked"))
        self.assertTrue(body.get("sold_login_required"))
        if body.get("results"):
            row = body["results"][0]
            self.assertTrue(row.get("sold_locked"))
            self.assertIsNone(row.get("close_price"))

    def test_anonymous_snapshots_redact_prices(self):
        response = self.client.get("/api/mls/properties/sold-gate-1/snapshots/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("sold_locked"))
        for snap in body.get("snapshots") or []:
            self.assertIsNone(snap.get("list_price"))

    def test_anonymous_sold_trends_locked(self):
        response = self.client.get("/api/mls/market/sold-trends/", {"scope": "gta"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("sold_locked"))
        self.assertEqual(body.get("series"), [])

    def test_anonymous_homepage_sold_below_locked(self):
        response = self.client.get("/api/home/sold-below-purchase/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("sold_locked"))
        self.assertEqual(body.get("results"), [])

    def test_anonymous_recent_sales_requires_auth(self):
        response = self.client.get(
            "/api/mls/market/recent-sales/",
            {"city": "Toronto", "days": 30},
        )
        self.assertIn(response.status_code, {401, 403})
