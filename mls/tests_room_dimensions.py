from django.test import SimpleTestCase

from mls.services.room_dimensions import format_room_dimensions, meters_to_feet_display


class RoomDimensionsTests(SimpleTestCase):
    def test_metric_default_when_units_blank(self):
        # TREB stores metres; blank units must not be shown as feet'inches.
        self.assertEqual(
            format_room_dimensions(5.4, 5.1, None),
            "5.4 × 5.1 m",
        )

    def test_prefers_feed_dimensions_text(self):
        self.assertEqual(
            format_room_dimensions(5.4, 5.1, "Meters", "5.40 x 5.10"),
            "5.40 x 5.10",
        )

    def test_imperial_passthrough(self):
        self.assertEqual(
            format_room_dimensions(12, 10, "Feet"),
            "12' × 10'",
        )

    def test_meters_to_feet_display(self):
        # 5.4 m ≈ 17'9"
        text = meters_to_feet_display(5.4, 5.1)
        self.assertIsNotNone(text)
        self.assertIn("×", text)
        self.assertIn("'", text)
