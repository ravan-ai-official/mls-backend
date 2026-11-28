from django.test import SimpleTestCase

from mls.services.ddf.mapper import _map_washrooms_json, _yn_bool


class ListingDetailMappingTests(SimpleTestCase):
    def test_yn_bool(self):
        self.assertTrue(_yn_bool("Y"))
        self.assertFalse(_yn_bool("N"))
        self.assertIsNone(_yn_bool(None))

    def test_washrooms_json_from_crea_array(self):
        rows = _map_washrooms_json(
            {
                "Washrooms": [
                    {"WashroomsNumberOf": 1, "WashroomsPieces": 2, "WashroomsLevel": "Main"},
                    {"WashroomsNumberOf": 2, "WashroomsPieces": 4, "WashroomsLevel": "2nd"},
                    {"WashroomsNumberOf": 1, "WashroomsPieces": 5, "WashroomsLevel": "2nd"},
                ]
            }
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {"count": 1, "pieces": 2, "level": "Main"})
        self.assertEqual(rows[2]["pieces"], 5)
