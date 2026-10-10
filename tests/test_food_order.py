"""Food ordering is persisted without changing nutrition or archived days."""
import unittest
import test_daily_foods as daily_tests
from test_category_history import clock
import app as melb


class FoodOrderTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def seed(self):
        meta = melb.load_foods()["Regular food"]
        foods = {
            "First": dict(meta),
            "Other category": {**meta, "category": "Snacks"},
            "Second": dict(meta),
            "Third": {**meta, "input_mode": "checkbox", "checkbox_amount": 50},
        }
        melb.save_foods(foods)
        return melb.load_foods()

    def move(self, name, direction):
        return self.client.post("/foods/reorder", data={"name": name, "direction": direction})

    def assert_order(self, html, names):
        positions = [html.index('data-name="' + name + '"') for name in names]
        self.assertEqual(positions, sorted(positions))

    def test_moves_within_category_and_preserves_metadata_and_export_order(self):
        before = self.seed()
        response = self.move("Second", "up")
        self.assertEqual(response.status_code, 303)
        self.assertIn("#food-category-0", response.location)
        current = melb.load_foods()
        self.assertEqual(list(current), ["Second", "Other category", "First", "Third"])
        self.assertEqual(current, before)
        self.assertEqual(list(melb.load_foods_for_day("2026-10-07")), list(current))
        self.assert_order(self.client.get("/?day=2026-10-07").get_data(as_text=True),
                          ["Second", "First", "Third"])
        export = self.client.get("/foods/export")
        self.assertEqual(list(export.json["foods"]), list(current))
        export.close()
        self.assertEqual(self.move("Second", "down").status_code, 303)
        self.assertEqual(list(melb.load_foods()), list(before))

    def test_reordering_preserves_past_and_locked_days(self):
        before = self.seed()
        with clock("2026-10-08"):
            self.client.post("/api/day-lock", json={"day": "2026-10-08", "locked": True})
            self.move("Third", "up")
            self.assertEqual(list(melb.load_foods()), ["First", "Other category", "Third", "Second"])
            self.assertEqual(list(melb.load_foods_for_day("2026-10-07")), list(before))
            self.assertEqual(list(melb.load_foods_for_day("2026-10-08")), list(before))
            self.assert_order(self.client.get("/?day=2026-10-08").get_data(as_text=True),
                              ["First", "Second", "Third"])
            self.client.post("/api/day-lock", json={"day": "2026-10-08", "locked": False})
            self.assertEqual(list(melb.load_foods_for_day("2026-10-08")),
                             ["First", "Other category", "Third", "Second"])

    def test_boundaries_and_invalid_requests_do_not_change_library(self):
        self.seed()
        before = self.foods_path.read_bytes()
        self.assertEqual(self.move("First", "up").status_code, 303)
        self.assertEqual(self.move("Third", "down").status_code, 303)
        self.assertEqual(self.move("Other category", "up").status_code, 303)
        self.assertEqual(self.move("Missing", "up").status_code, 404)
        self.assertEqual(self.move("Second", "sideways").status_code, 400)
        self.assertEqual(self.foods_path.read_bytes(), before)
        self.assertFalse((self.foods_path.parent / "food_backups").exists())
        html = self.client.get("/foods").get_data(as_text=True)
        self.assertEqual(html.count('class="food-reorder"'), 4)
        self.assertIn('action="/foods/reorder"', html)
