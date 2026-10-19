"""Original label values, editable nutrition, backups and historical protection."""
import copy
import io
import json
import unittest
from html.parser import HTMLParser
import app as melb
import food_library as library
import test_daily_foods as daily_tests
from test_category_history import clock


class NutritionLabelTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def realgood(self):
        label = library.ORIGINAL_SERVINGS["realgood costco"]
        return {"category":"Dawg Bowl", "salt_extra_weight_factor":0,
                **{coefficient:label[nutrient]/label["grams"]
                   for nutrient, coefficient in library.LABEL_NUTRIENTS.items()}}

    def post_label(self, name="Regular food", **changes):
        payload = {"name":name, "serving_g":112, "calories":120,
                   "protein":21, "carbs":4, "fat":5, "fiber":0}
        payload.update(changes)
        return self.client.post("/foods/nutrition",data=payload)

    def test_realgood_original_values_are_recovered_without_changing_coefficients(self):
        food = self.realgood()
        before = copy.deepcopy(food)
        serving = library.label_serving_for("realgood costco", food)
        self.assertEqual({key:serving[key] for key in ["grams","calories","protein","carbs","fat","fiber"]},
                         {"grams":112,"calories":120,"protein":21,"carbs":4,"fat":5,"fiber":0})
        self.assertEqual(serving["source"],"notebook")
        self.assertEqual(serving["original_ratios"]["calories"],{"amount":120,"grams":112})
        self.assertEqual(food,before)
        food["cal_per_g"] = 2
        self.assertEqual(library.label_serving_for("realgood costco",food)["source"],"reference")
        self.assertEqual(library.label_serving_for("realgood costco",food)["calories"],200)

    def test_all_recovered_servings_and_ratios_are_consistent(self):
        for name,label in library.ORIGINAL_SERVINGS.items():
            with self.subTest(name=name):
                meta = {coefficient:label[nutrient]/label["grams"]
                        for nutrient,coefficient in library.LABEL_NUTRIENTS.items()}
                self.assertEqual(library.validate_label_serving(label,meta,name),label)
        rice = library.ORIGINAL_SERVINGS["Enriched Rice"]
        self.assertEqual(rice["grams"],45)
        self.assertEqual(rice["original_ratios"]["fiber"],{"amount":2.5,"grams":240})
        self.assertEqual(rice["fiber"],2.5/240*45)

    def test_new_food_retains_entered_label_and_fallback_is_honestly_marked(self):
        created = self.client.post("/foods",data={
            "name":"New label", "category":"Dawg Bowl", "serving_g":112,
            "calories":140, "protein":19, "carbs":0, "fat":7, "fiber":0})
        self.assertEqual(created.status_code,200)
        meta = melb.load_foods()["New label"]
        self.assertEqual(meta["label_serving"]["grams"],112)
        self.assertEqual(meta["label_serving"]["calories"],140)
        self.assertEqual(meta["cal_per_g"],140/112)
        unknown = library.label_serving_for("Regular food",melb.load_foods()["Regular food"])
        self.assertEqual(unknown["grams"],100)
        self.assertEqual(unknown["source"],"reference")
        known = library.label_serving_for("Legacy portion",{**self.realgood(),"checkbox_amount":112})
        self.assertEqual(known["source"],"saved_portion")
        self.assertEqual(known["grams"],112)
        self.assertEqual(known["calories"],120)

    def test_saved_food_editor_prefills_recovered_label_values(self):
        melb.save_foods({"realgood costco":self.realgood()})
        html = self.client.get("/foods").get_data(as_text=True)
        class FormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.active=False
                self.values={}
            def handle_starttag(self,tag,attrs):
                data=dict(attrs)
                if tag=="form":
                    self.active=data.get("class")=="edit-food-nutrition" and data.get("data-food")=="realgood costco"
                    if self.active:self.action=data["action"]
                if self.active and tag=="input":self.values[data["name"]]=data.get("value")
            def handle_endtag(self,tag):
                if tag=="form":self.active=False
        parser=FormParser()
        parser.feed(html)
        self.assertEqual(parser.action,"/foods/nutrition")
        self.assertEqual(parser.values,{"name":"realgood costco","serving_g":"112","calories":"120",
                                       "protein":"21","carbs":"4","fat":"5","fiber":"0"})
        self.assertIn("Original notebook ratios",html)
        self.assertNotIn("kcal/100g",html)

    def test_editing_preserves_food_order_settings_and_locked_nutrition(self):
        foods=melb.load_foods()
        foods["Regular food"].update(input_mode="checkbox",checkbox_amount=50,
                                     salt_extra_weight_factor=1.5,source={"note":"Keep me"},
                                     soluble_frac=.2,insoluble_frac=.8)
        foods["Second"]=self.realgood()
        melb.save_foods(foods)
        self.client.post("/api/entry",json={"day":"2026-10-07","food_name":"Regular food","amount":50})
        self.client.post("/api/day-lock",json={"day":"2026-10-07","locked":True})
        frozen=melb.locked_day_snapshot("2026-10-07")
        original_totals=melb.day_totals_for("2026-10-07")
        response=self.post_label()
        self.assertEqual(response.status_code,200)
        current=melb.load_foods()
        self.assertEqual(list(current),list(foods))
        for key in ("category","input_mode","checkbox_amount","salt_extra_weight_factor",
                    "source","soluble_frac","insoluble_frac"):
            self.assertEqual(current["Regular food"][key],foods["Regular food"][key])
        self.assertEqual(current["Regular food"]["cal_per_g"],120/112)
        self.assertEqual(current["Regular food"]["label_serving"]["calories"],120)
        self.assertEqual(melb.locked_day_snapshot("2026-10-07"),frozen)
        self.assertEqual(melb.day_totals_for("2026-10-07"),original_totals)
        self.assertEqual(len(list((self.foods_path.parent/"food_backups").glob("*.json"))),1)

    def test_nutrition_edit_on_next_day_preserves_past_values(self):
        self.client.post("/api/entry",json={"day":"2026-10-07","food_name":"Regular food","amount":112})
        before=melb.day_totals_for("2026-10-07")
        with clock("2026-10-08"):
            self.assertEqual(self.post_label().status_code,200)
            self.assertEqual(melb.day_totals_for("2026-10-07"),before)
            self.assertEqual(melb.load_foods_for_day("2026-10-08")["Regular food"]["cal_per_g"],120/112)

    def test_export_import_carries_recovered_labels_without_notebook_dependency(self):
        melb.save_foods({"realgood costco":self.realgood()})
        response=self.client.get("/foods/export")
        payload=response.json
        response.close()
        self.assertEqual(payload["foods"]["realgood costco"]["label_serving"]["grams"],112)
        melb.save_foods({})
        response=self.client.post("/foods/import",data={
            "mode":"replace","backup":(io.BytesIO(json.dumps(payload).encode()),"backup.json")},
            content_type="multipart/form-data")
        response.request.environ["wsgi.input"].close()
        self.assertEqual(response.status_code,200)
        meta=melb.load_foods()["realgood costco"]
        self.assertEqual(meta["label_serving"]["calories"],120)
        self.assertEqual(meta["cal_per_g"],120/112)

    def test_invalid_edits_and_conflicting_import_metadata_are_rejected(self):
        before=self.foods_path.read_bytes()
        for changes in ({"serving_g":0},{"calories":-1},{"protein":"nan"},{"fat":"inf"},{"fiber":"x"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post_label(**changes).status_code,400)
                self.assertEqual(self.foods_path.read_bytes(),before)
        self.assertEqual(self.post_label(name="Missing").status_code,404)
        meta=self.realgood()
        meta["label_serving"]={**library.ORIGINAL_SERVINGS["realgood costco"],"calories":999}
        with self.assertRaises(ValueError):library.validate_foods({"realgood costco":meta})
        self.assertFalse((self.foods_path.parent/"food_backups").exists())

    def test_export_of_large_valid_checkbox_portion_does_not_invent_invalid_label(self):
        meta={**melb.load_foods()["Regular food"],
              "input_mode":"checkbox", "checkbox_amount":1_000_000}
        melb.save_foods({"Large portion":meta})
        response=self.client.get("/foods/export")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["foods"]["Large portion"]["checkbox_amount"],1_000_000)
        self.assertNotIn("label_serving",response.json["foods"]["Large portion"])
        response.close()
