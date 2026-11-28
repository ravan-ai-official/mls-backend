from django.test import SimpleTestCase

from mls.services.room_dimensions import (
    dual_room_dimensions,
    format_room_dimensions,
    meters_to_feet_display,
)


class RoomDimensionsTests(SimpleTestCase):
    def test_metric_default_when_units_blank(self):
        self.assertEqual(
            format_room_dimensions(5.4, 5.1, None),
            "5.4 × 5.1 m",
        )

    def test_dual_provides_both_units(self):
        dims = dual_room_dimensions(5.4, 5.1, "Meters")
        self.assertEqual(dims["dimensions_m"], "5.4 × 5.1 m")
        self.assertTrue(dims["is_metric_source"])
        self.assertIsNotNone(dims["dimensions_ft"])
        self.assertIn("'", dims["dimensions_ft"])
        self.assertEqual(dims["dimensions_display"], dims["dimensions_m"])

    def test_imperial_source_converts_to_metric(self):
        dims = dual_room_dimensions(12, 10, "Feet")
        self.assertEqual(dims["dimensions_ft"], "12' × 10'")
        self.assertFalse(dims["is_metric_source"])
        self.assertIsNotNone(dims["dimensions_m"])
        self.assertTrue(dims["dimensions_m"].endswith(" m"))

    def test_meters_to_feet_display(self):
        text = meters_to_feet_display(5.4, 5.1)
        self.assertIsNotNone(text)
        self.assertIn("×", text)
        self.assertIn("'", text)
