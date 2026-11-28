from django.test import SimpleTestCase

from mls.services.listing_history import coalesce_snapshots, event_label


class ListingHistoryCoalesceTests(SimpleTestCase):
    def test_event_labels(self):
        self.assertEqual(event_label("Active"), "For Sale")
        self.assertEqual(event_label("Closed"), "Sold")
        self.assertEqual(event_label("Expired"), "Expired")

    def test_collapses_identical_mt_noise(self):
        snaps = [
            {
                "list_price": 999999,
                "standard_status": "Active",
                "source_modification_timestamp": "2026-11-19T10:00:00Z",
            },
            {
                "list_price": 999999,
                "standard_status": "Active",
                "source_modification_timestamp": "2026-11-19T12:00:00Z",
            },
            {
                "list_price": 999999,
                "standard_status": "Active",
                "source_modification_timestamp": "2026-11-19T18:00:00Z",
            },
        ]
        rows = coalesce_snapshots(snaps, listing_id="X14145328", listing_key="abc")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "For Sale")
        self.assertEqual(rows[0]["price"], 999999.0)
        self.assertEqual(rows[0]["listing_id"], "X14145328")
        self.assertIsNone(rows[0]["date_end"])
        self.assertEqual(rows[0]["date_start"], "2026-11-19T10:00:00Z")

    def test_price_change_starts_new_period(self):
        snaps = [
            {
                "list_price": 999999,
                "standard_status": "Active",
                "source_modification_timestamp": "2026-11-01T00:00:00Z",
            },
            {
                "list_price": 949999,
                "standard_status": "Active",
                "source_modification_timestamp": "2026-11-15T00:00:00Z",
            },
        ]
        rows = coalesce_snapshots(snaps, listing_id="X1")
        self.assertEqual(len(rows), 2)
        # Newest first
        self.assertEqual(rows[0]["price"], 949999.0)
        self.assertEqual(rows[0]["date_start"], "2026-11-15T00:00:00Z")
        self.assertIsNone(rows[0]["date_end"])
        self.assertEqual(rows[1]["price"], 999999.0)
        self.assertEqual(rows[1]["date_end"], "2026-11-15T00:00:00Z")
