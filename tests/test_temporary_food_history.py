"""Temporary food edits and custom history use isolated per-test databases."""
import unittest

import app as melb
import test_daily_foods as daily_tests


class TemporaryFoodHistoryTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp
    add = daily_tests.DailyLoggingTests.add

    def history(self, query=""):
        return self.client.get("/api/day-food-history", query_string={"q": query})

    def edit(self, entry, **overrides):
        payload = {key: entry[key] for key in (
            "day", "name", "serving_label", "servings", "serving_g", "calories",
            "protein", "carbs", "fat", "fiber", "source_url")}
        payload.update(overrides)
        return self.client.patch(f"/api/day-food/{entry['id']}", json=payload)

    def test_edit_updates_one_entry_in_place_and_recalculates_totals(self):
        first = self.add(serving_g=22).json["entry"]
        other_day = self.add(day="2026-10-07").json["entry"]
        result = self.edit(first, name="Corrected snack", servings=3, serving_g=30,
                           serving_label="1 portion (30 g)", calories=110, protein=4,
                           carbs=12, fat=3, fiber=2)
        self.assertEqual(result.status_code, 200)
        entry = result.json["entry"]
        self.assertEqual(entry["id"], first["id"])
        self.assertEqual(entry["created_at"], first["created_at"])
        self.assertEqual(entry["name"], "Corrected snack")
        self.assertEqual(entry["serving_g"], 30)
        self.assertEqual(result.json["totals"]["calories"], 330)
        self.assertEqual(result.json["totals"]["protein"], 12)
        self.assertEqual(result.json["totals"]["fiber"], 6)
        self.assertEqual(melb.load_day_foods(other_day["day"]), [other_day])
        self.assertEqual(self.foods_path.read_bytes(), self.food_bytes)

    def test_edit_preserves_salt_configuration_unless_explicitly_changed(self):
        entry = self.add(name="Rice", serving_g=22, salt_extra_weight_factor=2).json["entry"]
        self.client.patch(f"/api/day-food/{entry['id']}/salt", json={
            "day": entry["day"], "include_in_spins": True})
        updated = self.edit(entry, name="Renamed rice", serving_g=30).json["entry"]
        self.assertEqual(updated["include_in_spins"], 1)
        self.assertEqual(updated["salt_extra_weight_factor"], 2)
        changed = self.edit(updated, include_in_spins=False,
                            salt_extra_weight_factor=0, serving_g=None).json["entry"]
        self.assertEqual(changed["include_in_spins"], 0)
        self.assertEqual(changed["salt_extra_weight_factor"], 0)
        self.assertIsNone(changed["serving_g"])

    def test_invalid_or_wrong_day_edits_leave_log_and_history_unchanged(self):
        entry = self.add(serving_g=22).json["entry"]
        before = self.history().json["entries"]
        invalid = [
            {"servings": 0}, {"calories": -1}, {"serving_g": 0},
            {"protein": float("nan")}, {"source_url": "https://evil.example"},
            {"include_in_spins": "true"}, {"salt_extra_weight_factor": 101},
            {"include_in_spins": True, "serving_g": None},
        ]
        for values in invalid:
            with self.subTest(values=values):
                self.assertEqual(self.edit(entry, **values).status_code, 400)
        self.assertEqual(self.edit(entry, day="2026-10-07").status_code, 404)
        self.assertEqual(self.edit(entry, day="invalid").status_code, 400)
        self.assertEqual(self.client.patch(f"/api/day-food/{entry['id']}", json=[]).status_code, 400)
        self.assertEqual(melb.load_day_foods(entry["day"]), [entry])
        self.assertEqual(self.history().json["entries"], before)

    def test_locked_day_edits_reject_and_history_removal_keeps_snapshot(self):
        entry = self.add(serving_g=22).json["entry"]
        self.client.post("/api/day-lock", json={"day": entry["day"], "locked": True})
        snapshot = melb.locked_day_snapshot(entry["day"])
        self.assertEqual(self.edit(entry, calories=400).status_code, 423)
        history_id = self.history().json["entries"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/day-food-history/{history_id}").status_code, 200)
        self.assertEqual(melb.locked_day_snapshot(entry["day"]), snapshot)
        self.assertEqual(melb.load_day_foods(entry["day"]), [entry])
        self.client.post("/api/day-lock", json={"day": entry["day"], "locked": False})
        self.assertEqual(self.edit(entry, calories=400).status_code, 200)

    def test_manual_history_uses_latest_values_deduplicates_and_searches(self):
        original = self.add(name="My   Custom Bowl", serving_g=84, servings=5).json["entry"]
        history_id = self.history().json["entries"][0]["id"]
        self.add(name="Different food", serving_g=50)
        self.add(name="my custom bowl", serving_g=92, servings=2, calories=120, fiber=3)
        entries = self.history().json["entries"]
        self.assertEqual(len(entries), 2)
        latest = entries[0]
        self.assertEqual(latest["id"], history_id)
        self.assertEqual(latest["name"], "my custom bowl")
        self.assertEqual(latest["serving_g"], 92)
        self.assertEqual(latest["calories"], 120)
        self.assertEqual(latest["fiber"], 3)
        self.assertEqual(latest["servings"], 1)
        self.assertEqual(latest["source_url"], "")
        self.assertNotIn("include_in_spins", latest)
        self.assertNotIn("salt_extra_weight_factor", latest)
        self.assertEqual(self.history("  CUSTOM   BOWL ").json["entries"], [latest])
        self.assertEqual(self.history("not here").json["entries"], [])
        self.assertEqual(self.history("%_").json["entries"], [])
        self.assertEqual(self.history("x" * 251).status_code, 400)
        self.assertEqual(melb.load_day_foods(original["day"])[0], original)

    def test_edit_refreshes_history_without_rewriting_existing_daily_copies(self):
        entry = self.add(name="Custom snack", serving_g=84).json["entry"]
        another = self.add(name="Custom snack", day="2026-10-07", calories=125).json["entry"]
        result = self.edit(entry, calories=150, serving_g=90)
        self.assertEqual(result.status_code, 200)
        history = self.history().json["entries"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["calories"], 150)
        self.assertEqual(history[0]["serving_g"], 90)
        self.assertEqual(melb.load_day_foods(another["day"]), [another])

    def test_lookup_foods_never_enter_custom_history_even_when_edited(self):
        entry = self.add(source_url="https://world.openfoodfacts.org/product/0038000000001").json["entry"]
        self.assertEqual(self.history().json["entries"], [])
        self.assertEqual(self.edit(entry, calories=150).status_code, 200)
        self.assertEqual(self.history().json["entries"], [])
        payload = {key: entry[key] for key in (
            "day", "name", "serving_label", "servings", "calories", "protein", "carbs", "fat")}
        self.assertEqual(self.client.patch(f"/api/day-food/{entry['id']}", json=payload).status_code, 200)
        self.assertEqual(self.history().json["entries"], [])

    def test_falsey_malformed_source_urls_cannot_reclassify_lookup_food(self):
        entry = self.add(source_url="https://world.openfoodfacts.org/product/0038000000001").json["entry"]
        for value in (False, 0, [], {}):
            with self.subTest(source_url=value):
                self.assertEqual(self.add(source_url=value).status_code, 400)
                self.assertEqual(self.edit(entry, source_url=value).status_code, 400)
        self.assertEqual(melb.load_day_foods(entry["day"]), [entry])
        self.assertEqual(self.history().json["entries"], [])
        self.assertEqual(self.add(source_url=None).status_code, 200)

    def test_history_deletion_is_persistent_but_daily_food_and_reuse_are_independent(self):
        entry = self.add(serving_g=22).json["entry"]
        history_id = self.history().json["entries"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/day-food-history/{history_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/day-food-history/{history_id}").status_code, 404)
        melb.init_db()
        melb.init_db()
        self.assertEqual(self.history().json["entries"], [])
        self.assertEqual(melb.load_day_foods(entry["day"]), [entry])
        self.add(serving_g=22)
        remembered = self.history().json["entries"][0]
        self.assertEqual(remembered["servings"], 1)
        reused = {key: remembered[key] for key in (
            "name", "serving_label", "serving_g", "servings", "calories", "protein",
            "carbs", "fat", "fiber", "source_url")}
        reused["day"] = "2026-10-07"
        result = self.client.post("/api/day-food", json=reused)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["entry"]["serving_g"], 22)
        self.assertEqual(result.json["entry"]["servings"], 1)
        self.assertEqual(result.json["entry"]["include_in_spins"], 0)

    def test_null_grams_on_creation_still_infers_label_but_edit_can_clear_mass(self):
        entry = self.add(serving_label="1 bar (22 g)", serving_g=None).json["entry"]
        self.assertEqual(entry["serving_g"], 22)
        self.assertEqual(self.history().json["entries"][0]["serving_g"], 22)
        updated = self.edit(entry, serving_g=None).json["entry"]
        self.assertIsNone(updated["serving_g"])
        self.assertIsNone(self.history().json["entries"][0]["serving_g"])
        included = self.add(serving_label="1 bar (22 g)", serving_g=None,
                            include_in_spins=True).json["entry"]
        self.assertEqual(included["serving_g"], 22)
        self.assertEqual(included["include_in_spins"], 1)
        self.assertEqual(self.edit(included, serving_g=None).status_code, 400)

    def test_manual_grams_are_stored_independently_from_label_and_serving_count(self):
        entry = self.add(serving_label="1 serving", serving_g=84, servings=5.35).json["entry"]
        self.assertEqual(entry["serving_g"], 84)
        self.assertEqual(entry["servings"], 5.35)
        history = self.history().json["entries"][0]
        self.assertEqual(history["serving_g"], 84)
        self.assertEqual(history["servings"], 1)
        self.assertIsNone(history["fiber"])

    def test_removing_a_log_and_resetting_a_day_do_not_clear_custom_history(self):
        first = self.add(name="First food").json["entry"]
        self.add(name="Second food")
        history = self.history().json["entries"]
        self.client.delete(f"/api/day-food/{first['id']}", json={"day": first["day"]})
        self.assertEqual(self.history().json["entries"], history)
        self.client.post("/reset", data={"day": first["day"]})
        self.assertEqual(melb.load_day_foods(first["day"]), [])
        self.assertEqual(self.history().json["entries"], history)

    def test_history_migration_backfills_latest_manual_food_only_once(self):
        first = self.add(name="Legacy snack", serving_g=40, calories=100).json["entry"]
        self.add(name=" legacy  SNACK ", serving_g=50, calories=150)
        self.add(name="Lookup snack", source_url="https://world.openfoodfacts.org/product/0038000000001")
        logs = melb.load_day_foods(first["day"])
        with melb.db() as conn:
            conn.execute("DROP TABLE day_food_history")
        melb.init_db()
        history = self.history().json["entries"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["calories"], 150)
        self.assertEqual(history[0]["serving_g"], 50)
        self.assertEqual(history[0]["servings"], 1)
        self.assertEqual(melb.load_day_foods(first["day"]), logs)
        self.client.delete(f"/api/day-food-history/{history[0]['id']}")
        melb.init_db()
        self.assertEqual(self.history().json["entries"], [])
        self.assertEqual(melb.load_day_foods(first["day"]), logs)


if __name__ == "__main__":
    unittest.main()
