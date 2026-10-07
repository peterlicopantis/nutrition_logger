"""Locked days retain a full snapshot and reject all day writes."""
import json
import unittest
import test_daily_foods as daily_tests
import app as melb

class DayLockTests(unittest.TestCase):
    setUp=daily_tests.DailyLoggingTests.setUp
    add=daily_tests.DailyLoggingTests.add

    def lock(self, day="2026-10-07", locked=True):
        return self.client.post("/api/day-lock",json={"day":day,"locked":locked})

    def entry(self,amount,day="2026-10-07"):
        return self.client.post("/api/entry",json={"day":day,"food_name":"Regular food","amount":amount})

    def test_locked_library_and_totals_ignore_same_day_setting_import_and_removal_changes(self):
        self.entry(3)
        self.add(day="2026-10-07",serving_g=22)
        before=melb.day_totals_for("2026-10-07")
        original=melb.library_state_for_day("2026-10-07")
        self.assertEqual(self.lock().status_code,200)
        changed=melb.load_foods()
        changed["Regular food"]["cal_per_g"]=100
        changed["Regular food"]["category"]="Elsewhere"
        melb.save_foods(changed)
        self.assertEqual(melb.day_totals_for("2026-10-07"),before)
        self.assertEqual(melb.library_state_for_day("2026-10-07")["foods"],original["foods"])
        self.client.post("/foods/remove",data={"name":"Regular food"})
        self.assertEqual(melb.day_totals_for("2026-10-07"),before)
        html=self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('data-name="Regular food"',html)
        self.assertIn("Unlock day",html)
        self.assertTrue(melb.locked_day_snapshot("2026-10-07"))

    def test_every_day_mutation_is_rejected_until_unlocked(self):
        self.entry(3)
        extra=self.add(day="2026-10-07",serving_g=22).json["entry"]
        self.lock()
        calls=[
            lambda:self.entry(0),
            lambda:self.add(day="2026-10-07"),
            lambda:self.client.patch(f"/api/day-food/{extra['id']}/salt",json={"day":"2026-10-07","include_in_spins":True}),
            lambda:self.client.delete(f"/api/day-food/{extra['id']}",json={"day":"2026-10-07"}),
            lambda:self.client.post("/reset",data={"day":"2026-10-07"}),
            lambda:self.client.post("/api/health-snapshot",json={"day":"2026-10-07","steps":100},headers={"X-MELB-Token":"test"}),
        ]
        for call in calls:
            response=call()
            self.assertEqual(response.status_code,423)
            self.assertIn("Unlock",response.json["error"])
        with melb.db() as conn:
            self.assertEqual(conn.execute("SELECT amount FROM daily_entries WHERE day='2026-10-07'").fetchone()["amount"],3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM day_foods WHERE day='2026-10-07'").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()[0],0)

    def test_unlock_reenables_editing_and_current_day_uses_live_definitions(self):
        self.entry(3)
        self.lock()
        foods=melb.load_foods()
        foods["Regular food"]["cal_per_g"]=20
        melb.save_foods(foods)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],30)
        self.assertEqual(self.lock(locked=False).status_code,200)
        self.assertIsNone(melb.locked_day_snapshot("2026-10-07"))
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],60)
        self.assertEqual(self.entry(4).json["totals"]["calories"],80)
        self.assertEqual(self.add(day="2026-10-07").status_code,200)

    def test_other_days_remain_editable_and_past_day_locks_are_independent(self):
        self.lock()
        self.assertEqual(self.entry(4,day="2026-10-08").status_code,200)
        self.assertEqual(self.add(day="2026-10-08").status_code,200)
        self.assertEqual(self.lock(day="2026-10-06").status_code,200)
        self.assertEqual(self.entry(4,day="2026-10-06").status_code,423)
        self.lock(day="2026-10-06",locked=False)
        self.assertEqual(self.entry(4,day="2026-10-06").status_code,200)
        self.assertIsNotNone(melb.locked_day_snapshot("2026-10-07"))

    def test_repeated_lock_does_not_recapture_changed_live_library(self):
        self.entry(3)
        self.lock()
        snapshot=melb.locked_day_snapshot("2026-10-07")
        melb.save_foods({})
        self.lock()
        self.assertEqual(melb.locked_day_snapshot("2026-10-07"),snapshot)
        with melb.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM day_locks").fetchone()[0],1)

    def test_locked_snapshot_survives_underlying_data_changes(self):
        self.entry(3)
        extra=self.add(day="2026-10-07",serving_g=22).json["entry"]
        self.client.post("/api/health-snapshot",json={"day":"2026-10-07","active_calories":100},headers={"X-MELB-Token":"test"})
        self.lock()
        before=melb.day_totals_for("2026-10-07")
        with melb.db() as conn:
            conn.execute("UPDATE daily_entries SET amount=999 WHERE day='2026-10-07'")
            conn.execute("UPDATE day_foods SET servings=999 WHERE id=?",(extra["id"],))
            conn.execute("UPDATE health_snapshots SET active_calories=999")
        self.assertEqual(melb.day_totals_for("2026-10-07"),before)
        self.assertEqual(melb.load_amounts("2026-10-07")["Regular food"],3)
        self.assertEqual(melb.load_day_foods("2026-10-07")[0]["servings"],2)
        self.assertEqual(melb.latest_health_snapshot("2026-10-07")["active_calories"],100)

    def test_checkbox_portion_changes_do_not_touch_locked_amount_until_unlock(self):
        foods=melb.load_foods()
        foods["Regular food"].update(input_mode="checkbox",checkbox_amount=50)
        melb.save_foods(foods)
        self.entry(50)
        self.lock()
        self.client.post("/foods/advanced",data={"name":"Regular food","input_mode":"checkbox",
            "checkbox_amount":100,"salt_extra_weight_factor":0})
        self.assertEqual(melb.load_amounts("2026-10-07")["Regular food"],50)
        with melb.db() as conn:
            self.assertEqual(conn.execute("SELECT amount FROM daily_entries").fetchone()[0],50)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],500)
        self.lock(locked=False)
        self.assertEqual(melb.load_amounts("2026-10-07")["Regular food"],100)
        self.assertEqual(melb.day_totals_for("2026-10-07")["calories"],1000)

    def test_invalid_lock_requests_and_unauthorized_health_requests_do_not_change_state(self):
        for payload in [None,{},{"day":"bad","locked":True},{"day":"2026-10-07","locked":"true"}]:
            response=self.client.post("/api/day-lock",json=payload)
            self.assertEqual(response.status_code,400)
        self.assertIsNone(melb.locked_day_snapshot("2026-10-07"))
        self.lock()
        self.assertEqual(self.client.post("/api/health-snapshot",json={"day":"2026-10-07","steps":1}).status_code,401)
