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
        body = json.dumps({"products": [label_product(product_name="Rice Krispies Treats Original")]}).encode()
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



class ImprovedLookupTests(unittest.TestCase):
    def setUp(self):
        food_lookup._cache.clear()
        food_lookup._search_requests.clear()
        food_lookup._product_requests.clear()
        food_lookup._inflight.clear()

    def test_plain_foods_return_verified_reference_without_network(self):
        with patch.object(food_lookup, "urlopen", side_effect=AssertionError("Plain foods must work offline")):
            for query in ("carrot", "carrots", "I had a carrot", "apple", "banana", "broccoli", "spinach", "potato", "egg", "rice", "chicken"):
                with self.subTest(query=query):
                    result = food_lookup.lookup_foods(query)
                    self.assertTrue(result["products"])
                    for product in result["products"]:
                        self.assertEqual(product["kind"], "generic")
                        self.assertEqual(product["basis"], "serving")
                        self.assertGreater(product["serving_g"], 0)
                        self.assertIn("~", product["serving_label"])
                        self.assertTrue(product["source_url"].startswith("https://fdc.nal.usda.gov/food-details/"))
            carrot = food_lookup.lookup_foods("carrot")["products"][0]
        self.assertEqual(carrot["name"], "Carrots, raw")
        self.assertEqual(carrot["nutrition_per_100g"]["calories"], 41)
        self.assertEqual(carrot["nutrition_per_100g"]["protein"], 0.93)
        self.assertEqual(carrot["nutrition_per_100g"]["carbs"], 9.58)
        self.assertEqual(carrot["nutrition_per_100g"]["fat"], 0.24)
        self.assertEqual(carrot["nutrition_per_100g"]["fiber"], 2.8)

    def test_preparation_and_product_queries_are_distinct(self):
        raw = food_lookup.lookup_foods("raw carrots")["products"]
        cooked = food_lookup.lookup_foods("cooked carrots")["products"]
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(cooked), 1)
        self.assertIn("cooked", cooked[0]["name"])
        self.assertEqual(cooked[0]["nutrition_per_100g"]["calories"], 35)
        self.assertEqual(cooked[0]["serving_g"], 46)
        for query in ("carrot cake", "carrot juice"):
            with self.subTest(query=query):
                with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(b'{"products":[]}')) as opened:
                    result = food_lookup.lookup_foods(query)
                self.assertEqual(result["products"], [])
                opened.assert_called_once()

    def test_packaged_results_match_titles_and_rank_closest_first(self):
        products = [
            label_product(code="0038000000002", product_name="Kimchi", ingredients_text="mega snack carrot"),
            label_product(code="0038000000003", product_name="Mega Snack Chocolate"),
            label_product(code="0038000000004", product_name="Mega Snack"),
        ]
        with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(json.dumps({"products": products}).encode())):
            result = food_lookup.lookup_foods("mega snack")
        self.assertEqual([item["name"] for item in result["products"]], ["Mega Snack", "Mega Snack Chocolate"])

    def test_transient_database_failure_retries_once(self):
        from urllib.error import HTTPError
        error = HTTPError("https://example.invalid", 503, "Busy", {}, None)
        response = io.BytesIO(json.dumps({"products":[label_product(product_name="Mega Snack")]}).encode())
        with patch.object(food_lookup, "urlopen", side_effect=[error, response]) as opened:
            with patch.object(food_lookup.time, "sleep"):
                result = food_lookup.lookup_foods("mega snack")
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(len(food_lookup._search_requests), 2)
        self.assertEqual(result["products"][0]["name"], "Mega Snack")
        with patch.object(food_lookup, "urlopen", side_effect=AssertionError("Successful results must be cached")):
            self.assertEqual(food_lookup.lookup_foods("Mega Snack")["products"], result["products"])

    def test_two_timeouts_stop_and_allow_a_later_retry(self):
        with patch.object(food_lookup, "urlopen", side_effect=TimeoutError("Timeout")) as opened:
            with patch.object(food_lookup.time, "sleep"):
                with self.assertRaises(food_lookup.FoodLookupError):
                    food_lookup.lookup_foods("mega snack")
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(food_lookup._inflight, {})
        body = json.dumps({"products":[label_product(product_name="Mega Snack")]}).encode()
        with patch.object(food_lookup, "urlopen", return_value=io.BytesIO(body)):
            self.assertTrue(food_lookup.lookup_foods("mega snack")["products"])

    def test_slow_search_does_not_block_a_different_query(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import parse_qs, urlparse
        started = threading.Event()
        release = threading.Event()
        def respond(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)["search_terms"][0]
            if query == "alpha snack":
                started.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release search")
            name = "Alpha Snack" if query == "alpha snack" else "Beta Snack"
            return io.BytesIO(json.dumps({"products":[label_product(product_name=name)]}).encode())
        with patch.object(food_lookup, "urlopen", side_effect=respond):
            with ThreadPoolExecutor(max_workers=2) as pool:
                slow = pool.submit(food_lookup.lookup_foods, "alpha snack")
                self.assertTrue(started.wait(2))
                try:
                    fast = pool.submit(food_lookup.lookup_foods, "beta snack")
                    self.assertEqual(fast.result(timeout=2)["products"][0]["name"], "Beta Snack")
                finally:
                    release.set()
                self.assertEqual(slow.result(timeout=2)["products"][0]["name"], "Alpha Snack")


    def test_interrupted_read_retries_then_fails_safely(self):
        from http.client import IncompleteRead, RemoteDisconnected
        for error_type in (IncompleteRead, RemoteDisconnected):
            with self.subTest(error_type=error_type):
                self.setUp()
                def failure():
                    return IncompleteRead(b"partial", 100) if error_type is IncompleteRead else RemoteDisconnected("Disconnected")
                body = json.dumps({"products":[label_product(product_name="Mega Snack")]}).encode()
                with patch.object(food_lookup, "urlopen", side_effect=[failure(), io.BytesIO(body)]) as opened:
                    with patch.object(food_lookup.time, "sleep"):
                        self.assertTrue(food_lookup.lookup_foods("mega snack")["products"])
                self.assertEqual(opened.call_count, 2)
                self.setUp()
                with patch.object(food_lookup, "urlopen", side_effect=[failure(), failure()]) as opened:
                    with patch.object(food_lookup.time, "sleep"):
                        with self.assertRaises(food_lookup.FoodLookupError):
                            food_lookup.lookup_foods("mega snack")
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(food_lookup._inflight, {})


class ReferenceSourceLoggingTests(unittest.TestCase):
    setUp = DailyLoggingTests.setUp
    add = DailyLoggingTests.add

    def test_reference_lookup_and_fractional_portion_are_day_scoped(self):
        with patch.object(food_lookup, "urlopen", side_effect=AssertionError("Carrot lookup must be offline")):
            response = self.client.get("/api/food-lookup?q=carrot")
        self.assertEqual(response.status_code, 200)
        carrot = response.json["products"][0]
        saved = self.add(name=carrot["name"], serving_label=carrot["serving_label"], servings=0.3,
                         calories=carrot["calories"], protein=carrot["protein"],
                         carbs=carrot["carbs"], fat=carrot["fat"], fiber=carrot["fiber"],
                         source_url=carrot["source_url"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json["totals"]["calories"], 7.5)
        self.assertEqual(saved.json["entry"]["calories"], 25.01)
        self.assertEqual(saved.json["entry"]["serving_label"], "1 medium carrot (~61 g)")
        self.assertEqual(saved.json["entry"]["source_url"], "https://fdc.nal.usda.gov/food-details/170393/nutrients")
        self.assertEqual(melb.load_day_foods("2026-10-07"), [])
        self.assertEqual(self.foods_path.read_bytes(), self.food_bytes)

    def test_source_url_requires_exact_canonical_ascii_links(self):
        urls = [
            "https://world.openfoodfacts.org/product/12345678;redirect=evil",
            "https://world.openfoodfacts.org/product/" + chr(0xff11) * 8,
            "https://world.openfoodfacts.org:443/product/12345678",
            "https://fdc.nal.usda.gov/food-details/170393/nutrients?redirect=evil",
            "https://fdc.nal.usda.gov/food-details/170393/nutrients#fragment",
            "https://fdc.nal.usda.gov:443/food-details/170393/nutrients",
            "https://fdc.nal.usda.gov.evil.example/food-details/170393/nutrients",
            "https://user:pass@fdc.nal.usda.gov/food-details/170393/nutrients",
            "https://fdc.nal.usda.gov/food-details/170393/../170393/nutrients",
            "https://fdc.nal.usda.gov/food-details/%31%37%30%33%39%33/nutrients",
            "https://fdc.nal.usda.gov/food-details/170393/nutrients\n",
        ]
        for source in urls:
            with self.subTest(source=source):
                self.assertEqual(self.add(source_url=source).status_code, 400)
        self.assertEqual(melb.load_day_foods("2026-10-06"), [])



class TypicalPortionTests(unittest.TestCase):
    def test_every_catalog_food_has_sourced_portions_and_scaled_default(self):
        with patch.object(food_lookup, "urlopen", side_effect=AssertionError("Reference portions are offline")):
            for food in food_lookup._generic_catalog:
                with self.subTest(food=food["name"]):
                    products = food_lookup.lookup_foods(food["aliases"][0])["products"]
                    product = next(p for p in products if p["source_url"].endswith(f"/{food['fdc_id']}/nutrients"))
                    self.assertTrue(product["portion_estimated"])
                    self.assertFalse(product["requires_weight"])
                    default = next(p for p in product["portions"] if p["id"] == product["default_portion_id"])
                    self.assertGreater(default["grams"], 0)
                    self.assertEqual(product["serving_g"], default["grams"])
                    for portion in product["portions"]:
                        self.assertTrue(portion["source_modifier"])
                        self.assertGreater(portion["source_amount"], 0)
                    for key in ("calories", "protein", "carbs", "fat", "fiber"):
                        self.assertEqual(product["nutrition_per_100g"][key], float(food[key]))
                        self.assertAlmostEqual(product[key], float(food[key]) * default["grams"] / 100, places=4)

    def test_sizes_counts_and_preparations_use_their_own_weights(self):
        with patch.object(food_lookup, "urlopen", side_effect=AssertionError("Known sizes are offline")):
            large = food_lookup.lookup_foods("I had 2 large carrots")
            self.assertEqual(large["suggested_servings"], 2)
            self.assertEqual(len(large["products"]), 1)
            self.assertEqual(large["products"][0]["serving_g"], 72)
            self.assertTrue(large["products"][0]["portion_countable"])
            cooked = food_lookup.lookup_foods("cooked carrots")["products"][0]
            self.assertEqual(cooked["serving_g"], 46)
            cup = next(p for p in cooked["portions"] if p["label"] == "1/2 cup slices")
            self.assertEqual(cup["grams"], 78)
            self.assertFalse(cup["countable"])
            rice = food_lookup.lookup_foods("I had 2 rice")["products"][0]
            self.assertFalse(rice["portion_countable"])

    def test_result_mutations_do_not_change_portion_or_nutrition_reference(self):
        first = food_lookup.lookup_foods("carrot")["products"][0]
        first["portions"][0]["grams"] = 999
        first["nutrition_per_100g"]["calories"] = 0
        second = food_lookup.lookup_foods("carrot")["products"][0]
        self.assertEqual(second["portions"][0]["grams"], 61)
        self.assertEqual(second["nutrition_per_100g"]["calories"], 41)

    def test_packaged_density_and_missing_weight_are_explicit(self):
        known = food_lookup.normalize_product(label_product())
        self.assertEqual(known["serving_g"], 22)
        self.assertEqual(known["nutrition_per_100g"]["calories"], 400)
        self.assertFalse(known["portion_estimated"])
        self.assertFalse(known["requires_weight"])
        unknown = food_lookup.normalize_product(label_product(
            serving_size="", serving_quantity=None, serving_quantity_unit="",
        ))
        self.assertTrue(unknown["requires_weight"])
        self.assertIsNone(unknown["serving_g"])
        self.assertEqual(unknown["portions"], [])
        self.assertEqual(unknown["nutrition_per_100g"]["calories"], 400)

    def test_volume_label_macros_remain_usable_without_assuming_mass(self):
        product = label_product(
            serving_size="1 can (250 ml)", serving_quantity=250, serving_quantity_unit="ml",
            product_quantity_unit="ml",
            nutriments={"energy-kcal_serving":115, "proteins_serving":0,
                        "carbohydrates_serving":27.5, "fat_serving":0},
        )
        result = food_lookup.normalize_product(product)
        self.assertEqual(result["basis"], "serving")
        self.assertEqual(result["calories"], 115)
        self.assertEqual(result["serving_label"], "1 can (250 ml)")
        self.assertIsNone(result["serving_g"])
        self.assertIsNone(result["nutrition_per_100g"])
        self.assertFalse(result["requires_weight"])


if __name__ == "__main__":
    unittest.main()
