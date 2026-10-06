"""Regression checks use temporary data files and mocked food search responses."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import app as melb
import food_lookup


def label_product(**overrides):
    product = {
        "code": "0038000000001",
        "product_name": "Original Treat",
        "brands": "Example",
        "serving_size": "1 bar (22 g)",
        "serving_quantity": 22,
        "serving_quantity_unit": "g",
        "nutriments": {
            "energy-kcal_100g": 400, "proteins_100g": 4,
            "carbohydrates_100g": 80, "fat_100g": 8,
        },
    }
    product.update(overrides)
    return product


class DailyLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="melb-food-tests-")
        folder = Path(self.temp.name)
        self.foods_path = folder / "foods.json"
        self.foods = {"Regular food": {
            "cal_per_g": 10, "protein_per_g": 1, "carbs_per_g": 2,
            "fat_per_g": 0.5, "fiber_per_g": 0.2, "category": "Meal",
        }}
        self.foods_path.write_text(json.dumps(self.foods), encoding="utf-8")
        (folder / "config.json").write_text(
            json.dumps({"shortcut_name": "Test", "health_import_token": "test"}),
            encoding="utf-8",
        )
        self.patchers = [
            patch.object(melb, "DB_PATH", folder / "test.db"),
            patch.object(melb, "FOODS_PATH", self.foods_path),
            patch.object(melb, "CONFIG_PATH", folder / "config.json"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)
        melb.app.config.update(TESTING=True)
        melb.init_db()
        self.client = melb.app.test_client()
        self.food_bytes = self.foods_path.read_bytes()

    def add(self, **overrides):
        payload = {
            "day": "2026-10-06", "name": "One-time snack",
            "serving_label": "1 bar (22 g)", "servings": 2,
            "calories": 90, "protein": 1, "carbs": 17, "fat": 2,
            "fiber": None, "source_url": "",
        }
        payload.update(overrides)
        return self.client.post("/api/day-food", json=payload)

    def test_day_only_snapshot_does_not_change_saved_foods(self):
        response = self.add()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["totals"]["calories"], 180)
        self.assertEqual(response.json["totals"]["protein"], 2)
        self.assertIsNone(response.json["entry"]["fiber"])
        self.assertEqual(self.foods_path.read_bytes(), self.food_bytes)
        self.assertEqual(melb.load_day_foods("2026-10-07"), [])
        self.foods_path.write_text("{}", encoding="utf-8")
        self.assertEqual(melb.day_totals_for("2026-10-06")["calories"], 180)

    def test_combined_totals_and_regular_entry_response(self):
        self.add(fiber=0.5)
        response = self.client.post("/api/entry", json={
            "day": "2026-10-06", "food_name": "Regular food", "amount": 3,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["totals"]["calories"], 210)
        self.assertEqual(response.json["totals"]["protein"], 5)
        self.assertEqual(response.json["totals"]["fiber"], 1.6)
        self.assertEqual(response.json["totals"]["calc_calories"], 229.5)

    def test_duplicates_are_independent_and_delete_is_date_scoped(self):
        first = self.add().json["entry"]
        second = self.add(servings=1).json["entry"]
        self.assertNotEqual(first["id"], second["id"])
        wrong_day = self.client.delete(f"/api/day-food/{first['id']}", json={"day": "2026-10-07"})
        self.assertEqual(wrong_day.status_code, 404)
        self.assertEqual(len(melb.load_day_foods("2026-10-06")), 2)
        response = self.client.delete(f"/api/day-food/{first['id']}", json={"day": "2026-10-06"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["totals"]["calories"], 90)
        self.assertEqual(melb.load_day_foods("2026-10-06")[0]["id"], second["id"])

    def test_reset_clears_both_kinds_only_on_selected_day(self):
        self.add()
        self.add(day="2026-10-07")
        for day in ("2026-10-06", "2026-10-07"):
            self.client.post("/api/entry", json={"day": day, "food_name": "Regular food", "amount": 3})
        response = self.client.post("/reset", data={"day": "2026-10-06"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(melb.day_totals_for("2026-10-06")["calories"], 0)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"], 210)

    def test_invalid_date_never_falls_back_to_today(self):
        for day in (None, "", "2026-02-30", "20261006", 20261006):
            with self.subTest(day=day):
                self.assertEqual(self.add(day=day).status_code, 400)
        self.assertEqual(melb.load_day_foods("2026-10-06"), [])

    def test_invalid_numbers_and_missing_core_macros_are_rejected(self):
        for key in ("calories", "protein", "carbs", "fat", "fiber", "servings"):
            for value in (float("nan"), float("inf"), -1, True, [], "no", 10 ** 400):
                with self.subTest(key=key, value=str(value)[:50]):
                    self.assertEqual(self.add(**{key: value}).status_code, 400)
        self.assertEqual(self.add(servings=0).status_code, 400)
        self.assertEqual(self.add(calories=None).status_code, 400)
        self.assertEqual(self.add(fiber="").status_code, 200)

    def test_untrusted_source_links_are_rejected(self):
        for source in ("javascript:alert(1)", "https://evil.example/product/0038000000001",
                       "https://world.openfoodfacts.org@evil.example/product/0038000000001"):
            with self.subTest(source=source):
                self.assertEqual(self.add(source_url=source).status_code, 400)
        self.assertEqual(self.add(source_url="https://world.openfoodfacts.org/product/0038000000001").status_code, 200)

    def test_dashboard_shows_selected_entries_and_escaped_names(self):
        self.add(name="<script>alert(1)</script>")
        response = self.client.get("/?day=2026-10-06")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Add food for this day", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("dayFood", html)
        self.assertNotIn("One-time snack", self.client.get("/?day=2026-10-07").get_data(as_text=True))

    def test_lookup_failure_and_empty_search_do_not_save_entries(self):
        self.assertEqual(self.client.get("/api/food-lookup?q=").status_code, 400)
        with patch.object(melb, "lookup_foods", side_effect=food_lookup.FoodLookupError("Offline")):
            response = self.client.get("/api/food-lookup?q=Rice+Krispies+Treats")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "Offline")
        self.assertEqual(melb.load_day_foods("2026-10-06"), [])

    def test_migration_preserves_existing_daily_entries(self):
        self.client.post("/api/entry", json={
            "day": "2026-10-06", "food_name": "Regular food", "amount": 3,
        })
        melb.init_db()
        melb.init_db()
        self.assertEqual(melb.load_amounts("2026-10-06")["Regular food"], 3)


class LookupTests(unittest.TestCase):
    def setUp(self):
        food_lookup._cache.clear()
        food_lookup._search_requests.clear()
        food_lookup._product_requests.clear()

    def test_description_alias_and_quantity(self):
        query, count = food_lookup.normalize_query("Oh I had a rice krispy treat")
        self.assertEqual(query, "Rice Krispies Treats")
        self.assertEqual(count, 1)
        query, count = food_lookup.normalize_query("I had 2 rice krispy treats chocolate")
        self.assertEqual(query, "Rice Krispies Treats chocolate")
        self.assertEqual(count, 2)
        self.assertEqual(food_lookup.normalize_query("I had 2 percent milk")[1], 1)

    def test_per_100g_is_scaled_only_with_known_gram_serving(self):
        product = food_lookup.normalize_product(label_product())
        self.assertEqual(product["basis"], "serving")
        self.assertAlmostEqual(product["calories"], 88)
        self.assertAlmostEqual(product["carbs"], 17.6)
        self.assertIsNone(product["fiber"])
        unknown = food_lookup.normalize_product(label_product(
            serving_size="", serving_quantity=None, serving_quantity_unit="",
        ))
        self.assertEqual(unknown["basis"], "100g")
        self.assertEqual(unknown["serving_label"], "100 g")
        self.assertEqual(unknown["calories"], 400)

    def test_incomplete_macros_and_nonfinite_values_are_excluded(self):
        product = label_product()
        product["nutriments"].pop("fat_100g")
        self.assertIsNone(food_lookup.normalize_product(product))
        product = label_product()
        product["nutriments"]["energy-kcal_100g"] = float("nan")
        self.assertIsNone(food_lookup.normalize_product(product))

    def test_kilojoules_are_converted_without_macro_estimates(self):
        product = label_product()
        product["nutriments"].pop("energy-kcal_100g")
        product["nutriments"]["energy_100g"] = 1673.6
        result = food_lookup.normalize_product(product)
        self.assertAlmostEqual(result["calories"], 88, places=3)

    def test_current_schema_and_total_carbohydrates(self):
        nutrients = {
            "energy-kcal": {"value": 400}, "proteins": {"value": 4},
            "carbohydrates": {"value": 75}, "carbohydrates-total": {"value": 80},
            "fat": {"value": 8},
        }
        product = label_product(nutriments=None, nutrition={
            "aggregated_set": {"preparation": "as_sold", "per": "100g", "nutrients": nutrients},
        })
        result = food_lookup.normalize_product(product)
        self.assertEqual(result["basis"], "serving")
        self.assertAlmostEqual(result["carbs"], 17.6)

    def test_volume_is_not_assumed_to_be_grams(self):
        result = food_lookup.normalize_product(label_product(
            serving_size="1 cup (250 ml)", serving_quantity=250,
            serving_quantity_unit="ml", product_quantity_unit="ml",
        ))
        self.assertIsNone(result)

    def test_barcode_lookup_and_cached_description_quantities(self):
        body = json.dumps({"products": [label_product()]}).encode()
        with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(body)) as opened:
            first = food_lookup.lookup_foods("I had 2 rice krispy treats")
            second = food_lookup.lookup_foods("I had a rice krispy treat")
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(first["suggested_servings"], 2)
        self.assertEqual(second["suggested_servings"], 1)
        self.assertIn("source_url", first["products"][0])
        self.setUp()
        body = json.dumps({"product": label_product()}).encode()
        with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(body)) as opened:
            result = food_lookup.lookup_foods("0038000000001")
        self.assertEqual(len(result["products"]), 1)
        self.assertIn("/product/0038000000001?", opened.call_args.args[0].full_url)

    def test_offline_and_unreadable_results_have_actionable_errors(self):
        with patch.object(food_lookup, "urlopen", side_effect=URLError("Offline")):
            with self.assertRaises(food_lookup.FoodLookupError):
                food_lookup.lookup_foods("Example")
        self.setUp()
        with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(b"not JSON")):
            with self.assertRaises(food_lookup.FoodLookupError):
                food_lookup.lookup_foods("Example")

    def test_rate_limit_stops_before_another_remote_call(self):
        now = food_lookup.time.monotonic()
        food_lookup._search_requests.extend([now] * 10)
        with patch.object(food_lookup, "urlopen") as opened:
            with self.assertRaises(food_lookup.FoodLookupError):
                food_lookup.lookup_foods("Different query")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
