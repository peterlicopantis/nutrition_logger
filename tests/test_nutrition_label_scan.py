"""Conservative OCR text extraction; images are never needed for these checks."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to check the nutrition-label parser")
class NutritionLabelScanTests(unittest.TestCase):
    parser_path = Path(__file__).resolve().parents[1] / "static" / "nutrition_label.js"

    def parse(self, text):
        script = "const p=require(process.argv[1]);let t='';process.stdin.setEncoding('utf8');process.stdin.on('data',v=>t+=v);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(p.parse(JSON.parse(t)))));"
        result = subprocess.run([shutil.which("node"), "-e", script, str(self.parser_path)],
                                input=json.dumps(text), text=True, capture_output=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def assert_macros(self, parsed, *, calories, protein, carbs, fat, fiber):
        self.assertEqual({key:parsed[key] for key in ("calories", "protein", "carbs", "fat", "fiber")},
                         dict(calories=calories, protein=protein, carbs=carbs, fat=fat, fiber=fiber))

    def test_us_label_uses_serving_weight_and_not_daily_values_or_subtypes(self):
        parsed = self.parse("""Nutrition Facts
6 servings per container
Serving size 1 cup (84 g)
Amount per serving
Calories 120
Total Fat 4g 5%
Saturated Fat 1g 5%
Trans Fat 0g
Cholesterol 40mg 13%
Sodium 300mg 13%
Total Carbohydrate 2g 1%
Dietary Fiber 0g 0%
Total Sugars 1g
Includes 0g Added Sugars 0%
Protein 18g 36%
Calcium 20mg 2%
* Percent Daily Values are based on a 2,000 calorie diet.
Ingredients: milk, protein powder, 99 g other text""")
        self.assertEqual(parsed["serving_g"], 84)
        self.assertEqual(parsed["serving_label"], "1 cup (84 g)")
        self.assert_macros(parsed, calories=120, protein=18, carbs=2, fat=4, fiber=0)
        self.assertEqual(parsed["warnings"], [])

    def test_serving_description_can_wrap_or_use_fractional_cups(self):
        parsed = self.parse("""Serving size
2/3 cup (55g)
Calories 230
Total Fat
8g 10%
Total Carbohydrate 37 g 13%
Dietary Fiber 4 g 14%
Protein 3g""")
        self.assertEqual(parsed["serving_g"], 55)
        self.assert_macros(parsed, calories=230, protein=3, carbs=37, fat=8, fiber=4)

    def test_known_ocr_letter_typos_and_decimal_comma_are_conservative(self):
        parsed = self.parse("""Nutrition Facts
Serving S1ze 1 bar (28 g)
Calorles 120
TotaI Fat 4,5 g 6%
Total Carbo-hydrate 12 g 4%
Dletary Flber .5g 2%
Proteln 6g""")
        self.assertEqual(parsed["serving_g"], 28)
        self.assert_macros(parsed, calories=120, protein=6, carbs=12, fat=4.5, fiber=.5)
        self.assertIsNone(self.parse("Protein O g")["protein"], "an OCR letter must not be invented as zero")

    def test_missing_fiber_is_unknown_but_printed_zero_is_preserved(self):
        parsed = self.parse("Serving Size 1 egg (50g)\nCalories 70\nFat 5g\nCarbohydrate 0g\nProtein 6g")
        self.assert_macros(parsed, calories=70, protein=6, carbs=0, fat=5, fiber=None)
        self.assertTrue(any("fiber" in item for item in parsed["warnings"]))

    def test_simple_per_100g_basis_keeps_kcal_and_skips_saturated_fat(self):
        parsed = self.parse("""Nutrition Information
Serving size 1 pot (170 g)
Per 100g
Energy 840 kJ / 200 kcal
Fat 8g
of which saturates 2g
Carbohydrate 20g
of which sugars 4g
Fibre 3g
Protein 12g
Salt 0.5g""")
        self.assertEqual(parsed["serving_g"], 100)
        self.assertIn("100 g", parsed["serving_label"])
        self.assert_macros(parsed, calories=200, protein=12, carbs=20, fat=8, fiber=3)
        self.assertTrue(any("per 100 g" in item for item in parsed["warnings"]))

    def test_kilojoules_and_percentages_do_not_become_calories_or_macro_grams(self):
        parsed = self.parse("Energy 840 kJ\nTotal Fat 10%\nProtein 12%\nCarbohydrate 20%\nDietary Fiber <1 g")
        self.assert_macros(parsed, calories=None, protein=None, carbs=None, fat=None, fiber=None)
        self.assertIsNone(self.parse("Calories 6%\nFat 2g")["calories"])
        self.assertIsNone(self.parse("Calories 840kJ")["calories"])

    def test_per_100ml_does_not_fabricate_mass(self):
        parsed = self.parse("Per 100 ml\nEnergy 200 kJ / 48 kcal\nFat 0g\nCarbohydrate 12g\nProtein 0g")
        self.assertIsNone(parsed["serving_g"])
        self.assertEqual(parsed["serving_label"], "100 ml (nutrition label basis)")
        self.assert_macros(parsed, calories=48, protein=0, carbs=12, fat=0, fiber=None)
        self.assertTrue(any("volume" in item for item in parsed["warnings"]))

    def test_explicit_multiple_bases_are_not_mixed(self):
        for header in ("Per 100 g    Per portion", "Amount per serving   Per container", "Per serving\nPer 100g"):
            with self.subTest(header=header):
                parsed = self.parse("Serving size 1 bar (28g)\n" + header + "\nCalories 400 112\nTotal Fat 12g 3.4g\nProtein 15g 4.2g")
                self.assert_macros(parsed, calories=None, protein=None, carbs=None, fat=None, fiber=None)
                self.assertEqual(parsed["serving_g"], 28)
                self.assertTrue(any("multiple nutrition columns" in item for item in parsed["warnings"]))

    def test_unmarked_multiple_values_and_conflicting_repeated_rows_stay_unknown(self):
        parsed = self.parse("Calories 120 240\nTotal Fat 4g 8g\nProtein 6g\nProtein 12g\nCarbohydrate 5g")
        self.assert_macros(parsed, calories=None, protein=None, carbs=5, fat=None, fiber=None)
        self.assertTrue(parsed["warnings"])

    def test_calories_from_fat_are_ignored_and_energy_duplicates_must_agree(self):
        parsed = self.parse("Calories 120\nCalories from Fat 40\nFat 4.5 g\nProtein 10g")
        self.assertEqual(parsed["calories"], 120)
        parsed = self.parse("Calories 120\nEnergy 500 kJ / 120 kcal")
        self.assertEqual(parsed["calories"], 120)
        self.assertIsNone(self.parse("Calories 120\nEnergy 600 kJ / 140 kcal")["calories"])

    def test_ambiguous_weight_and_impossible_macro_are_not_accepted(self):
        for serving in ("1 scoop (50-60g)", "1 pack (84g) or 2 cups (168g)"):
            with self.subTest(serving=serving):
                self.assertIsNone(self.parse("Serving Size " + serving)["serving_g"])
        parsed = self.parse("Serving size 1 bar (28g)\nTotal Fat 400g\nProtein 6g")
        self.assertIsNone(parsed["fat"])
        self.assertEqual(parsed["protein"], 6)

    def test_non_label_text_does_not_invent_food_name_or_nutrition(self):
        parsed = self.parse("A photo of a carrot and a barcode.")
        self.assert_macros(parsed, calories=None, protein=None, carbs=None, fat=None, fiber=None)
        self.assertIsNone(parsed["serving_g"])
        self.assertIsNone(parsed["serving_label"])
        self.assertTrue(parsed["warnings"])

    def test_flattened_ocr_still_detects_per_100g_after_container_count(self):
        parsed = self.parse("Nutrition Facts 6 servings per container Serving size 1 bar (28g) Per 100g Calories 400 Total Fat 12g Protein 15g")
        self.assertEqual(parsed["serving_g"], 100)
        self.assertEqual(parsed["calories"], 400)
        self.assertEqual(parsed["fat"], 12)

    def test_negative_fractional_and_ambiguous_separator_values_stay_blank(self):
        self.assertIsNone(self.parse("Serving size -84g")["serving_g"])
        self.assertIsNone(self.parse("Protein -4g")["protein"])
        self.assertIsNone(self.parse("Protein 1/2g")["protein"])
        self.assertIsNone(self.parse("Calories 1,200")["calories"])
        self.assertIsNone(self.parse("Calories 120kcal 240")["calories"])
        parsed = self.parse("Energy 840kJ 200kcal 10%")
        self.assertEqual(parsed["calories"], 200)

    def test_compact_label_real_ocr_words_rejoin_calories_and_read_printed_zeros(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "compact_label_ocr.json").read_text())
        for reading in fixture["cases"]:
            with self.subTest(scale=reading["scale"], psm=reading["psm"]):
                parsed = self.parse(reading)
                self.assert_macros(parsed, calories=60, protein=0, carbs=17, fat=0, fiber=0)
                self.assertEqual(parsed["serving_g"], 21 if reading["scale"] == 3 else None)

    def test_small_raster_label_recovers_macros_without_inventing_serving_weight(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" / "compact_label_raster_ocr.json").read_text())
        parsed = self.parse(fixture["cases"][0])
        self.assert_macros(parsed, calories=60, protein=0, carbs=17, fat=0, fiber=0)
        self.assertIsNone(parsed["serving_g"])

    def test_zero_unit_ocr_and_daily_value_heading_after_calories(self):
        parsed = self.parse("Serving size 1 Tbsp. (21g)\nCalories\n60\n% Daily Value*\nTotal Fat Og 0%\nTotal Carbohydrate 17g 6%\nDietary Fiber Og 0%\nProtein Og\n* The % Daily Value tells you\ncalories 3 are used")
        self.assertEqual(parsed["serving_g"], 21)
        self.assert_macros(parsed, calories=60, protein=0, carbs=17, fat=0, fiber=0)

    def test_implausible_spoon_weight_is_flagged_instead_of_guessing_digits(self):
        parsed = self.parse("Serving size 1 Tbsp. (219g)\nCalories 60")
        self.assertIsNone(parsed["serving_g"])
        self.assertNotIn("219", parsed["serving_label"])
        self.assertTrue(any("spoon size" in warning for warning in parsed["warnings"]))

    def test_browser_global_exports_the_same_parser_without_node_globals(self):
        script = "const fs=require('node:fs'),vm=require('node:vm');const context={};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);const p=context.NutritionLabel.parse('Serving size 1 bar (28g)\\nCalories 120');if(p.serving_g!==28||p.calories!==120)process.exit(1);"
        subprocess.run([shutil.which("node"), "-e", script, str(self.parser_path)],
                       text=True, capture_output=True, check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
