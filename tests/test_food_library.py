"""Food-library backup workflows use isolated files and databases."""
import io
import json
import unittest
from pathlib import Path
import test_daily_foods as daily_tests
import app as melb

class FoodLibraryTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def imported(self, data, mode="merge", selected=None):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        fields={"mode":mode,"backup":(io.BytesIO(raw),"backup.json")}
        if selected is not None:
            fields.update(selection_present="1", selected_food=selected)
        response = self.client.post("/foods/import",
            data=fields,
            content_type="multipart/form-data")
        response.request.environ["wsgi.input"].close()
        return response

    def test_preview_validates_without_changing_library_or_creating_backup(self):
        before=self.foods_path.read_bytes()
        foods={"Regular food":self.food(),"Enriched Rice":self.food(salt_extra_weight_factor=1.5)}
        response=self.client.post("/foods/import/preview",
            data={"backup":(io.BytesIO(json.dumps(foods).encode()),"backup.json")},
            content_type="multipart/form-data")
        self.assertEqual(response.status_code,200)
        self.assertEqual([food["name"] for food in response.json["foods"]],list(foods))
        self.assertTrue(response.json["foods"][0]["exists"])
        self.assertFalse(response.json["foods"][1]["exists"])
        self.assertEqual(response.json["foods"][1]["salt_extra_weight_factor"],1.5)
        self.assertEqual(self.foods_path.read_bytes(),before)
        self.assertFalse((self.foods_path.parent/"food_backups").exists())
        response.request.environ["wsgi.input"].close()
        invalid=self.client.post("/foods/import/preview",
            data={"backup":(io.BytesIO(b"invalid"),"backup.json")},
            content_type="multipart/form-data")
        self.assertEqual(invalid.status_code,400)
        self.assertFalse(invalid.json["ok"])
        invalid.request.environ["wsgi.input"].close()

    def test_selected_merge_imports_only_checked_foods_and_settings(self):
        foods={"Enriched Rice":self.food(salt_extra_weight_factor=1.5),
               "Skipped":self.food(), "Regular food":self.food(cal_per_g=7)}
        response=self.imported(foods,selected=["Enriched Rice"])
        self.assertEqual(response.status_code,200)
        current=melb.load_foods()
        self.assertEqual(set(current),{"Enriched Rice","Regular food"})
        self.assertEqual(current["Regular food"]["cal_per_g"],10)
        self.assertEqual(current["Enriched Rice"]["salt_extra_weight_factor"],1.5)
        self.assertEqual(len(list((self.foods_path.parent/"food_backups").glob("*.json"))),1)

    def test_selected_replace_keeps_only_selection_and_all_can_be_selected(self):
        foods={"One":self.food(),"Two":self.food()}
        self.assertEqual(self.imported(foods,"replace",selected=["Two"]).status_code,200)
        self.assertEqual(set(melb.load_foods()),{"Two"})
        self.assertEqual(self.imported(foods,"replace",selected=list(foods)).status_code,200)
        self.assertEqual(set(melb.load_foods()),set(foods))

    def test_empty_or_unknown_selection_does_not_change_or_back_up_library(self):
        before=self.foods_path.read_bytes()
        for selected in [[],["Unknown"]]:
            self.assertEqual(self.imported({"One":self.food()},"replace",selected=selected).status_code,400)
            self.assertEqual(self.foods_path.read_bytes(),before)
            self.assertFalse((self.foods_path.parent/"food_backups").exists())

    def test_add_food_form_always_targets_creation_after_other_food_actions(self):
        from html.parser import HTMLParser
        class FormParser(HTMLParser):
            action = None
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "form" and attrs.get("id") == "addFoodForm":
                    self.action = attrs.get("action")
        responses = [
            self.client.post("/foods/advanced", data={"name":"Regular food","salt_extra_weight_factor":"0"}),
            self.client.post("/foods/move", data={"name":"Regular food","category":"Dawg Bowl"}),
            self.client.post("/foods/remove", data={"name":"Missing food"}),
        ]
        for response in responses:
            parser = FormParser()
            parser.feed(response.get_data(as_text=True))
            self.assertEqual(parser.action, "/foods")
        created = self.client.post(parser.action, data={
            "name":"Slider form regression", "category":"Dawg Bowl", "input_mode":"slider",
            "serving_g":50, "calories":70, "protein":6, "carbs":0, "fat":5, "fiber":0,
        })
        self.assertEqual(created.status_code,200)
        food = melb.load_foods()["Slider form regression"]
        self.assertEqual(food["category"],"Dawg Bowl")
        self.assertEqual(food["input_mode"],"slider")
        self.assertEqual(food["cal_per_g"],1.4)
        self.assertEqual(food["protein_per_g"],0.12)
        self.assertEqual(food["fat_per_g"],0.1)

    def food(self, **overrides):
        meta={"cal_per_g":1,"protein_per_g":.1,"carbs_per_g":.2,"fat_per_g":.05,
              "fiber_per_g":.01,"soluble_frac":.1,"insoluble_frac":.9,
              "category":"Dawg Bowl","salt_extra_weight_factor":0}
        meta.update(overrides)
        return meta

    def test_export_import_roundtrip_preserves_settings_and_metadata(self):
        current={"Enriched Rice":self.food(salt_extra_weight_factor=1.5, source={"note":"Label"}),
                 "Other":self.food(category="Cream")}
        melb.save_foods(current)
        response=self.client.get("/foods/export")
        self.assertEqual(response.status_code,200)
        self.assertIn("attachment;",response.headers["Content-Disposition"])
        self.assertEqual(response.json["format"],"melb-food-library")
        self.assertEqual(response.json["version"],1)
        self.assertEqual(response.json["foods"],current)
        melb.save_foods({"Temporary":self.food()})
        self.assertEqual(self.imported(response.json,"replace").status_code,200)
        self.assertEqual(melb.load_foods(),current)
        backups=list((self.foods_path.parent/"food_backups").glob("*.json"))
        self.assertEqual(len(backups),1)
        self.assertEqual(json.loads(backups[0].read_text())["foods"],{"Temporary":self.food()})
        download=self.client.get("/foods/backups/"+backups[0].name)
        self.assertEqual(download.status_code,200)
        self.assertEqual(download.json["foods"],{"Temporary":self.food()})
        download.close()

    def test_legacy_import_defaults_rice_but_preserves_explicit_zero(self):
        legacy=self.food()
        legacy.pop("salt_extra_weight_factor")
        self.assertEqual(self.imported({"Enriched Rice":legacy}).status_code,200)
        self.assertEqual(melb.load_foods()["Enriched Rice"]["salt_extra_weight_factor"],1.5)
        disabled=self.food(salt_extra_weight_factor=0)
        self.assertEqual(self.imported({"Enriched Rice":disabled}).status_code,200)
        self.assertEqual(melb.load_foods()["Enriched Rice"]["salt_extra_weight_factor"],0)

    def test_merge_updates_named_foods_without_removing_other_foods(self):
        self.assertEqual(self.imported({"New":self.food(), "Regular food":self.food(cal_per_g=7)}).status_code,200)
        foods=melb.load_foods()
        self.assertEqual(set(foods),{"New","Regular food"})
        self.assertEqual(foods["Regular food"]["cal_per_g"],7)
        self.assertEqual(self.imported({"Only":self.food()},"replace").status_code,200)
        self.assertEqual(set(melb.load_foods()),{"Only"})

    def test_invalid_import_is_atomic_and_creates_no_backup(self):
        invalid=[b"not json",b'{"A":{"cal_per_g":NaN}}',[],
                 {"Bad":self.food(category="")},
                 {"Bad":self.food(salt_extra_weight_factor=-1)},
                 {"Bad":self.food(protein_per_g=True)},
                 {"Bad":self.food(cal_per_g=10**400)},
                 {"Bad":self.food(soluble_frac=2)},
                 {"Bad":self.food(fiber_per_g=None)},
                 {"format":"melb-food-library","version":2,"foods":{}},
                 {" good ":self.food()}]
        for data in invalid:
            with self.subTest(data=str(data)[:80]):
                before=self.foods_path.read_bytes()
                self.assertEqual(self.imported(data,"replace").status_code,400)
                self.assertEqual(self.foods_path.read_bytes(),before)
                self.assertFalse((self.foods_path.parent/"food_backups").exists())
        self.assertEqual(self.imported({},"invalid-mode").status_code,400)
        self.assertEqual(self.client.post("/foods/import",data={"mode":"merge"}).status_code,400)
        self.assertEqual(self.imported(b" "*1_000_001).status_code,400)

    def test_remove_library_food_preserves_daily_logs_and_can_restore(self):
        self.client.post("/api/entry",json={"day":"2026-10-07","food_name":"Regular food","amount":29})
        exported=self.client.get("/foods/export").json
        response=self.client.post("/foods/remove",data={"name":"Regular food"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(melb.load_foods(),{})
        self.assertEqual(melb.load_amounts("2026-10-07")["Regular food"],29)
        self.assertEqual(self.client.post("/foods/remove",data={"name":"Regular food"}).status_code,404)
        self.assertEqual(self.imported(exported).status_code,200)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],290)

    def test_advanced_factor_drives_calculation_badge_and_backup(self):
        before=melb.load_foods()["Regular food"].copy()
        response=self.client.post("/foods/advanced",data={"name":"Regular food","salt_extra_weight_factor":"2"})
        self.assertEqual(response.status_code,200)
        after=melb.load_foods()["Regular food"]
        self.assertEqual(after["salt_extra_weight_factor"],2)
        for key in ["cal_per_g","protein_per_g","carbs_per_g","fat_per_g","fiber_per_g"]:
            self.assertEqual(after[key],before[key])
        result=melb.salt_spins_for(melb.load_foods(),{"Regular food":29},[])
        self.assertEqual(result["grams"],87)
        self.assertEqual(result["spins"],3)
        self.assertEqual(self.client.get("/foods/export").json["foods"]["Regular food"]["salt_extra_weight_factor"],2)
        self.assertIn("3.0&times; salt weight",response.get_data(as_text=True))
        self.assertIn("3.0&times; salt weight",self.client.get("/?day=2026-10-07").get_data(as_text=True))
        self.assertEqual(len(list((self.foods_path.parent/"food_backups").glob("*.json"))),1)

    def test_invalid_advanced_changes_leave_library_unchanged(self):
        before=self.foods_path.read_bytes()
        for factor in ["", "-1", "nan", "inf", "101", "text"]:
            self.assertEqual(self.client.post("/foods/advanced",data={"name":"Regular food","salt_extra_weight_factor":factor}).status_code,400)
            self.assertEqual(self.foods_path.read_bytes(),before)
        self.assertEqual(self.client.post("/foods/advanced",data={"name":"Missing","salt_extra_weight_factor":"1"}).status_code,404)
        self.assertFalse((self.foods_path.parent/"food_backups").exists())

    def test_other_category_factor_does_not_affect_salt_and_rice_can_be_disabled(self):
        foods={"Enriched Rice":self.food(salt_extra_weight_factor=0),
               "Other":self.food(category="Cream",salt_extra_weight_factor=50)}
        self.assertEqual(melb.salt_spins_for(foods,{"Enriched Rice":200,"Other":500},[])["grams"],200)

    def test_temporary_foods_keep_their_own_salt_factor_snapshot(self):
        response=self.client.post("/api/day-food",json={"day":"2026-10-07","name":"Rice, white, cooked",
            "serving_label":"100 g","serving_g":100,"servings":2,"calories":130,"protein":2.69,
            "carbs":28.17,"fat":.28,"fiber":.4,"source_url":""})
        self.assertEqual(response.status_code,200)
        entry=response.json["entry"]
        self.assertEqual(entry["salt_extra_weight_factor"],1.5)
        self.client.patch(f"/api/day-food/{entry['id']}/salt",json={"day":"2026-10-07","include_in_spins":True})
        entry=melb.load_day_foods("2026-10-07")[0]
        self.assertEqual(melb.salt_spins_for({}, {}, [entry])["grams"],500)
        self.assertEqual(melb.load_day_foods("2026-10-06"),[])

    def test_food_controls_and_backup_paths_are_safe(self):
        name="<script>alert(1)</script>"
        melb.save_foods({name:self.food()})
        html=self.client.get("/foods").get_data(as_text=True)
        self.assertIn("Export all foods",html)
        self.assertIn("Advanced settings",html)
        self.assertIn("/foods/remove",html)
        self.assertNotIn(name,html)
        self.assertEqual(self.client.get("/foods/backups/foods.json").status_code,404)
        self.assertEqual(self.client.get("/foods/backups/..%2Ffoods.json").status_code,404)
