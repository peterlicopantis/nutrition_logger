"""Fixed-portion checkbox foods retain their settings and day history."""
import io
import json
import unittest
from unittest.mock import patch
from datetime import date
import test_daily_foods as daily_tests
import app as melb

def clock(day):
    value=date.fromisoformat(day)
    class FrozenDate(date):
        @classmethod
        def today(cls):return value
    return patch.object(melb,"date",FrozenDate)

class CheckboxFoodTests(unittest.TestCase):
    setUp=daily_tests.DailyLoggingTests.setUp

    def create(self, name="Checkbox food", mode="checkbox"):
        return self.client.post("/foods",data={"name":name,"category":"Dawg Bowl","input_mode":mode,
            "serving_g":50,"calories":120,"protein":8,"carbs":15,"fat":3,"fiber":2})

    def entry(self,name,amount,day="2026-10-07"):
        return self.client.post("/api/entry",json={"day":day,"food_name":name,"amount":amount})

    def test_creation_configures_one_checked_serving_and_renders_no_slider(self):
        self.assertEqual(self.create().status_code,200)
        meta=melb.load_foods()["Checkbox food"]
        self.assertEqual(meta["input_mode"],"checkbox")
        self.assertEqual(meta["checkbox_amount"],50)
        html=self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn("food-checkbox",html)
        self.assertIn('data-checkbox-amount="50.0"',html)
        self.assertEqual(html.count('type="range"'),2) # regular food and temporary servings
        self.assertIn("one check = 50.0",self.client.get("/foods").get_data(as_text=True))

    def test_check_adds_exact_configured_macros_and_uncheck_removes_them(self):
        self.create()
        selected=self.entry("Checkbox food",50)
        self.assertEqual(selected.status_code,200)
        totals=selected.json["totals"]
        self.assertEqual({key:totals[key] for key in ["calories","protein","carbs","fat","fiber"]},
                         {"calories":120,"protein":8,"carbs":15,"fat":3,"fiber":2})
        self.assertEqual(melb.load_amounts("2026-10-07")["Checkbox food"],50)
        salt=melb.salt_spins_for(melb.load_foods(),melb.load_amounts("2026-10-07"),[])
        self.assertEqual(salt["grams"],50)
        self.assertEqual(self.entry("Checkbox food",0).json["totals"]["calories"],0)
        self.assertNotIn("Checkbox food",melb.load_amounts("2026-10-07"))

    def test_api_rejects_fractional_or_multiple_checked_portions(self):
        self.create()
        for amount in [1,25,49.9,100]:
            self.assertEqual(self.entry("Checkbox food",amount).status_code,400)
        self.assertEqual(melb.load_amounts("2026-10-07"),{})

    def test_advanced_setting_converts_today_only_and_preserves_old_control(self):
        self.entry("Regular food",200,day="2026-10-06")
        self.entry("Regular food",200)
        response=self.client.post("/foods/advanced",data={"name":"Regular food",
            "salt_extra_weight_factor":0,"input_mode":"checkbox","checkbox_amount":25})
        self.assertEqual(response.status_code,200)
        self.assertEqual(melb.load_amounts("2026-10-07")["Regular food"],25)
        self.assertEqual(melb.load_amounts("2026-10-06")["Regular food"],200)
        self.assertEqual(melb.day_totals_for("2026-10-06")["calories"],2000)
        old=melb.load_foods_for_day("2026-10-06")["Regular food"]
        self.assertEqual(old.get("input_mode","slider"),"slider")
        old_html=self.client.get("/?day=2026-10-06").get_data(as_text=True)
        self.assertNotIn("food-input food-checkbox",old_html)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],250)

    def test_changing_checked_portion_next_day_preserves_previous_portion_and_macros(self):
        self.create()
        self.entry("Checkbox food",50)
        with clock("2026-10-08"):
            self.entry("Checkbox food",50,day="2026-10-08")
            response=self.client.post("/foods/advanced",data={"name":"Checkbox food",
                "salt_extra_weight_factor":0,"input_mode":"checkbox","checkbox_amount":100})
            self.assertEqual(response.status_code,200)
            self.assertEqual(melb.load_amounts("2026-10-08")["Checkbox food"],100)
            self.assertEqual(melb.load_amounts("2026-10-07")["Checkbox food"],50)
            self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],120)
            self.assertEqual(melb.day_totals_for("2026-10-08")["calories"],240)
            self.assertEqual(melb.load_foods_for_day("2026-10-07")["Checkbox food"]["checkbox_amount"],50)

    def test_export_import_restores_checkbox_mode_portion_and_macros(self):
        self.create()
        exported=self.client.get("/foods/export").json
        melb.save_foods({})
        response=self.client.post("/foods/import",data={"mode":"replace",
            "backup":(io.BytesIO(json.dumps(exported).encode()),"backup.json")},content_type="multipart/form-data")
        response.request.environ["wsgi.input"].close()
        self.assertEqual(response.status_code,200)
        self.assertEqual(melb.load_foods()["Checkbox food"]["input_mode"],"checkbox")
        self.assertEqual(melb.load_foods()["Checkbox food"]["checkbox_amount"],50)
        self.assertEqual(self.entry("Checkbox food",50).json["totals"]["calories"],120)

    def test_bad_checkbox_configuration_does_not_modify_library(self):
        self.create()
        before=self.foods_path.read_bytes()
        for mode,amount in [("unknown","50"),("checkbox","0"),("checkbox","-1"),("checkbox","nan"),("checkbox","inf"),("checkbox","1000001")]:
            response=self.client.post("/foods/advanced",data={"name":"Checkbox food",
                "salt_extra_weight_factor":0,"input_mode":mode,"checkbox_amount":amount})
            self.assertEqual(response.status_code,400)
            self.assertEqual(self.foods_path.read_bytes(),before)
        self.assertEqual(self.create("Invalid food","unknown").status_code,200)
        self.assertNotIn("Invalid food",melb.load_foods())

    def test_rice_checkbox_uses_mass_once_and_extra_factor_only_for_salt(self):
        self.create("Rice")
        selected=self.entry("Rice",50)
        self.assertEqual(selected.json["totals"]["calories"],120)
        self.assertEqual(melb.salt_spins_for(melb.load_foods(),melb.load_amounts("2026-10-07"),[])["grams"],125)
