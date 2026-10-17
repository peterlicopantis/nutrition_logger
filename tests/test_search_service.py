"""Search service failover and explicit search-index nutrition bases."""
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import food_lookup as lookup
import test_daily_foods as daily_tests


class SearchServiceTests(unittest.TestCase):
    def setUp(self):
        lookup._cache.clear()
        lookup._search_requests.clear()
        lookup._product_requests.clear()
        lookup._inflight.clear()

    def response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def busy(self, status=503):
        return HTTPError("https://example.invalid", status, "Busy", {}, None)

    def test_primary_search_uses_hits_and_brand_lists_without_legacy_call(self):
        hit = daily_tests.label_product(product_name="Mega Snack", brands=["Mega", "Example"])
        with patch.object(lookup, "urlopen", return_value=self.response({"hits": [hit]})) as opened:
            result = lookup.lookup_foods("mega snack")
        self.assertEqual(opened.call_count, 1)
        url = urlparse(opened.call_args.args[0].full_url)
        self.assertEqual(url.netloc, "search.openfoodfacts.org")
        self.assertEqual(parse_qs(url.query)["q"], ["mega snack"])
        self.assertEqual(result["products"][0]["brand"], "Mega, Example")

    def test_failed_primary_automatically_falls_back_within_one_lookup(self):
        product = daily_tests.label_product(product_name="Mega Snack")
        with patch.object(lookup, "urlopen", side_effect=[
                self.busy(), self.busy(), self.response({"products": [product]})]) as opened:
            with patch.object(lookup.time, "sleep"):
                result = lookup.lookup_foods("mega snack")
        self.assertEqual(opened.call_count, 3)
        self.assertIn("search.openfoodfacts.org", opened.call_args_list[0].args[0].full_url)
        self.assertIn("/cgi/search.pl?", opened.call_args_list[2].args[0].full_url)
        self.assertEqual(result["products"][0]["name"], "Mega Snack")

    def test_rate_limit_is_not_bypassed_by_fallback(self):
        with patch.object(lookup, "urlopen", side_effect=self.busy(429)) as opened:
            with self.assertRaises(lookup.FoodLookupError):
                lookup.lookup_foods("mega snack")
        self.assertEqual(opened.call_count, 1)

    def test_empty_valid_results_do_not_retry_or_fall_back(self):
        with patch.object(lookup, "urlopen", return_value=self.response({"hits": []})) as opened:
            result = lookup.lookup_foods("missing snack")
        self.assertEqual(result["products"], [])
        self.assertEqual(opened.call_count, 1)

    def test_timeout_budget_is_shared_by_retries_and_fallback(self):
        current = [0.0]
        def fail(request, timeout):
            current[0] += timeout
            raise TimeoutError("Provider timed out")
        def pause(seconds):
            current[0] += seconds
        with patch.object(lookup.time, "monotonic", side_effect=lambda: current[0]), \
             patch.object(lookup.time, "sleep", side_effect=pause), \
             patch.object(lookup, "urlopen", side_effect=fail) as opened:
            with self.assertRaises(lookup.FoodLookupError):
                lookup.lookup_foods("mega snack")
        self.assertLessEqual(current[0], lookup.REQUEST_BUDGET)
        self.assertLess(opened.call_args.kwargs["timeout"], lookup.REQUEST_TIMEOUT)

    def test_search_index_liquid_uses_volume_reference_and_no_salt_mass(self):
        hit = daily_tests.label_product(product_name="Drink", brands=["Example"],
                serving_size="", serving_quantity=None, serving_quantity_unit="",
                quantity="12 fl oz", categories_tags=["en:beverages"])
        product = lookup._normalize_search_hit(hit)
        self.assertEqual(product["serving_label"], "100 ml")
        self.assertIsNone(product["serving_g"])
        self.assertIsNone(product["nutrition_per_100g"])
        self.assertEqual(product["calories"], 400)
        self.assertEqual(product["basis"], "serving")
        self.assertFalse(product["portions"])

    def test_search_index_solid_without_serving_requires_actual_grams(self):
        hit = daily_tests.label_product(product_name="Snack", brands=["Example"],
                serving_size="", serving_quantity=None, serving_quantity_unit="", quantity="500 g")
        product = lookup._normalize_search_hit(hit)
        self.assertEqual(product["basis"], "100g")
        self.assertTrue(product["requires_weight"])
        self.assertIsNone(product["serving_g"])

    def test_real_label_serving_is_preserved_for_liquids(self):
        hit = daily_tests.label_product(product_name="Drink", serving_size="1 can (250 ml)",
                serving_quantity=250, serving_quantity_unit="ml", product_quantity_unit="ml",
                nutriments={"energy-kcal_serving":115, "proteins_serving":0,
                            "carbohydrates_serving":27.5, "fat_serving":0})
        product = lookup._normalize_search_hit(hit)
        self.assertEqual(product["calories"], 115)
        self.assertEqual(product["serving_label"], "1 can (250 ml)")
        self.assertIsNone(product["serving_g"])

    def test_staging_search_never_contacts_production(self):
        with patch.dict(lookup.os.environ, {"MELB_FOOD_LOOKUP_STAGING":"1"}):
            with patch.object(lookup, "urlopen", return_value=self.response({"products": []})) as opened:
                lookup.lookup_foods("mega snack")
        self.assertEqual(urlparse(opened.call_args.args[0].full_url).netloc, "world.openfoodfacts.net")

    def test_query_punctuation_is_not_interpreted_as_search_operators(self):
        with patch.object(lookup, "urlopen", return_value=self.response({"hits": []})) as opened:
            lookup.lookup_foods("cereal + (nuts): [1 TO 2]")
        query = parse_qs(urlparse(opened.call_args.args[0].full_url).query)["q"][0]
        self.assertEqual(query, "cereal nuts 1 to 2")

    def test_explicit_current_mass_basis_is_not_replaced_by_volume_inference(self):
        nutrients = {key: {"value": value} for key, value in {
            "energy-kcal":400, "proteins":4, "carbohydrates":80, "fat":8}.items()}
        hit = daily_tests.label_product(serving_size="", serving_quantity=None,
                serving_quantity_unit="", quantity="500 ml", nutrition={
                    "aggregated_set":{"preparation":"as_sold", "per":"100g", "nutrients":nutrients}})
        product = lookup._normalize_search_hit(hit)
        self.assertEqual(product["basis"], "100g")
        self.assertEqual(product["calories"], 400)

    def test_powder_in_beverage_category_keeps_its_explicit_mass_basis(self):
        hit = daily_tests.label_product(product_name="Drink powder", quantity="500 g",
                serving_size="", serving_quantity=None, serving_quantity_unit="",
                categories_tags=["en:beverages"])
        product = lookup._normalize_search_hit(hit)
        self.assertEqual(product["basis"], "100g")
        self.assertEqual(product["serving_label"], "100 g")
