"""Category management and daily library history use isolated data."""
import io
import json
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from unittest.mock import patch
import test_daily_foods as daily_tests
import app as melb

def clock(day):
    value=date.fromisoformat(day)
    class FrozenDate(date):
        @classmethod
        def today(cls): return value
    return patch.object(melb,"date",FrozenDate)

class CategoryHistoryTests(unittest.TestCase):
    setUp=daily_tests.DailyLoggingTests.setUp

    def meta(self, category="Meal", calories=10, factor=0):
        return {"category":category,"cal_per_g":calories,"protein_per_g":1,
                "carbs_per_g":2,"fat_per_g":.5,"fiber_per_g":.2,
                "salt_extra_weight_factor":factor}

    def seed_legacy(self, foods):
        self.foods_path.write_text(json.dumps(foods),encoding="utf-8")
        self.foods_path.with_name("categories.json").write_text(json.dumps(["Dawg Bowl"]),encoding="utf-8")
        with melb.db() as conn: conn.execute("DELETE FROM food_library_versions")
        melb.initialize_library_history()

    def import_library(self, payload, mode="replace"):
        response=self.client.post("/foods/import",data={"mode":mode,"backup":(io.BytesIO(json.dumps(payload).encode()),"backup.json")},
                                  content_type="multipart/form-data")
        response.request.environ["wsgi.input"].close()
        return response

    def test_empty_library_always_has_dawg_bowl_on_dashboard_and_new_food_form(self):
        melb.save_foods({},categories=[])
        self.assertEqual(melb.load_categories(),["Dawg Bowl"])
        for day in ["2026-10-07","2026-10-06"]:
            html=self.client.get("/?day="+day).get_data(as_text=True)
            self.assertIn('data-category="Dawg Bowl"',html)
            if day == "2026-10-07":
                self.assertIn("No foods here yet",html)
        self.assertIn("<option>Dawg Bowl</option>",self.client.get("/foods").get_data(as_text=True))
        self.assertEqual(self.import_library({}).status_code,200)
        self.assertEqual(melb.load_categories(),["Dawg Bowl"])

    def test_current_meal_foods_stay_in_meal_and_only_dawg_bowl_counts(self):
        self.seed_legacy({"Original":self.meta()})
        self.assertEqual(melb.load_foods()["Original"]["category"],"Meal")
        self.client.post("/api/entry",json={"day":"2026-10-07","food_name":"Original","amount":58})
        current=melb.library_state_for_day("2026-10-07")
        self.assertEqual(current["salt_category"],"Dawg Bowl")
        self.assertEqual(melb.salt_spins_for(current["foods"],{"Original":58},[])["grams"],0)
        self.client.post("/foods/move",data={"name":"Original","category":"Dawg Bowl"})
        self.assertEqual(melb.load_foods()["Original"]["category"],"Dawg Bowl")
        self.assertEqual(melb.salt_spins_for(melb.load_foods(),{"Original":58},[])["spins"],2)

    def test_new_food_can_create_category_and_moving_can_create_category(self):
        payload={"name":"New food","category":"Dawg Bowl","new_category":"Breakfast",
                 "serving_g":100,"calories":100,"protein":1,"carbs":20,"fat":2,"fiber":3}
        self.assertEqual(self.client.post("/foods",data=payload).status_code,200)
        self.assertEqual(melb.load_foods()["New food"]["category"],"Breakfast")
        self.assertIn("Breakfast",melb.load_categories())
        response=self.client.post("/foods/move",data={"name":"New food","category":"Dawg Bowl","new_category":"Snacks"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(melb.load_foods()["New food"]["category"],"Snacks")
        self.assertTrue({"Dawg Bowl","Breakfast","Snacks"}.issubset(melb.load_categories()))

    def test_moving_today_preserves_yesterday_category_nutrition_amount_and_salt_rule(self):
        self.seed_legacy({"Original":self.meta("Meal",10,1.5)})
        self.client.post("/api/entry",json={"day":"2026-10-06","food_name":"Original","amount":58})
        before=melb.library_state_for_day("2026-10-06")
        totals=melb.day_totals_for("2026-10-06")
        salt=melb.salt_spins_for(before["foods"],{"Original":58},[],before["salt_category"])
        self.client.post("/foods/move",data={"name":"Original","category":"Dawg Bowl"})
        self.client.post("/foods/advanced",data={"name":"Original","salt_extra_weight_factor":0})
        after=melb.library_state_for_day("2026-10-06")
        self.assertEqual(after,before)
        self.assertEqual(melb.day_totals_for("2026-10-06"),totals)
        self.assertEqual(melb.salt_spins_for(after["foods"],{"Original":58},[],after["salt_category"]),salt)
        self.assertEqual(salt["spins"],5)
        self.assertEqual(melb.load_foods()["Original"]["category"],"Dawg Bowl")
        self.assertEqual(melb.load_foods()["Original"]["salt_extra_weight_factor"],0)

    def test_import_and_remove_today_leave_yesterday_sliders_and_totals_unchanged(self):
        self.seed_legacy({"Old food":self.meta("Meal",10)})
        self.client.post("/api/entry",json={"day":"2026-10-06","food_name":"Old food","amount":3})
        self.assertEqual(self.import_library({"New food":self.meta("Dawg Bowl",20)}).status_code,200)
        past=self.client.get("/?day=2026-10-06").get_data(as_text=True)
        today=self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('data-name="Old food"',past)
        self.assertNotIn('data-name="New food"',past)
        self.assertIn('data-name="New food"',today)
        self.assertNotIn('data-name="Old food"',today)
        self.assertEqual(melb.day_totals_for("2026-10-06")["calories"],30)
        update=self.client.post("/api/entry",json={"day":"2026-10-06","food_name":"Old food","amount":4})
        self.assertEqual(update.status_code,200)
        self.assertEqual(update.json["totals"]["calories"],40)
        invalid=self.client.post("/api/entry",json={"day":"2026-10-06","food_name":"New food","amount":4})
        self.assertEqual(invalid.status_code,404)
        self.client.post("/foods/remove",data={"name":"New food"})
        self.assertEqual(melb.day_totals_for("2026-10-06")["calories"],40)

    def test_next_day_changes_preserve_the_previous_days_final_library(self):
        melb.save_foods({"Rice":self.meta("Dawg Bowl",1,1.5)},categories=["Empty custom"])
        self.client.post("/api/entry",json={"day":"2026-10-07","food_name":"Rice","amount":200})
        before=melb.library_state_for_day("2026-10-07")
        with clock("2026-10-08"):
            self.client.post("/foods/move",data={"name":"Rice","new_category":"Dinner"})
            changed=melb.load_foods()
            changed["Rice"]["cal_per_g"]=9
            melb.save_foods(changed)
            self.assertEqual(melb.library_state_for_day("2026-10-07")["foods"],before["foods"])
            self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],200)
            self.assertEqual(melb.load_foods_for_day("2026-10-08")["Rice"]["cal_per_g"],9)
            self.assertEqual(melb.load_foods_for_day("2026-10-08")["Rice"]["category"],"Dinner")

    def test_category_export_import_preserves_empty_custom_categories(self):
        melb.save_foods({"One":self.meta("Custom")},categories=["Dawg Bowl","Custom","Empty custom"])
        backup=self.client.get("/foods/export").json
        self.assertIn("Empty custom",backup["categories"])
        melb.save_foods({},categories=[])
        self.assertEqual(self.import_library(backup).status_code,200)
        self.assertEqual(melb.load_categories(),backup["categories"])
        self.assertEqual(melb.load_foods()["One"]["category"],"Custom")

    def test_case_variants_do_not_duplicate_dawg_bowl_and_invalid_names_do_not_write(self):
        melb.save_foods({"One":self.meta("Dawg Bowl")})
        self.assertEqual(self.client.post("/foods/move",data={"name":"One","new_category":"dawg bowl"}).status_code,200)
        self.assertEqual(melb.load_categories().count("Dawg Bowl"),1)
        before=self.foods_path.read_bytes()
        for category in ["", "x"*51, "Bad\ncategory"]:
            response=self.client.post("/foods/move",data={"name":"One","category":category})
            self.assertEqual(response.status_code,400)
            self.assertEqual(self.foods_path.read_bytes(),before)

    def test_remove_empty_category_preserves_past_days_and_locked_snapshots(self):
        melb.save_foods(melb.load_foods(),categories=["Dawg Bowl","Empty category"])
        with clock("2026-10-08"):
            self.client.post("/api/day-lock",json={"day":"2026-10-08","locked":True})
            response=self.client.post("/foods/category/remove",data={"category":"Empty category"})
            self.assertEqual(response.status_code,200)
            self.assertNotIn("Empty category",melb.load_categories())
            self.assertIn("Empty category",melb.library_state_for_day("2026-10-07")["categories"])
            self.assertIn("Empty category",melb.library_state_for_day("2026-10-08")["categories"])
            self.assertEqual(len(list((self.foods_path.parent/"food_backups").glob("*.json"))),1)

    def test_only_empty_nonpermanent_categories_can_be_removed(self):
        melb.save_foods({"One":self.meta("Populated")},categories=["Empty"])
        self.assertEqual(self.client.post("/foods/category/remove",data={"category":"Dawg Bowl"}).status_code,400)
        self.assertEqual(self.client.post("/foods/category/remove",data={"category":"Populated"}).status_code,400)
        self.assertEqual(self.client.post("/foods/category/remove",data={"category":"Missing"}).status_code,404)
        html=self.client.get("/foods").get_data(as_text=True)
        self.assertEqual(html.count('class="remove-library-category"'),1)
        self.assertEqual(self.client.post("/foods/category/remove",data={"category":"Empty"}).status_code,200)
        self.assertNotIn("Empty",melb.load_categories())
        self.assertIn("Dawg Bowl",melb.load_categories())

    def test_upgrade_backs_up_existing_database_without_altering_entries(self):
        with melb.db() as conn:
            conn.execute("DROP TABLE food_library_versions")
            conn.execute("INSERT INTO daily_entries VALUES (?,?,?,?)",("2026-10-06","Regular food",5,"before"))
        melb.init_db()
        backups=list((self.foods_path.parent/"database_backups").glob("*.db"))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as original:
            self.assertEqual(original.execute("SELECT amount FROM daily_entries WHERE day='2026-10-06'").fetchone()[0],5)
            self.assertIsNone(original.execute("SELECT name FROM sqlite_master WHERE name='food_library_versions'").fetchone())
        self.assertEqual(melb.load_amounts("2026-10-06")["Regular food"],5)
        melb.init_db()
        self.assertEqual(len(list((self.foods_path.parent/"database_backups").glob("*.db"))),1)
