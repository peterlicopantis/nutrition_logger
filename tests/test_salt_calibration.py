"""Measured shaker calibration is shared by the page and retained by locks."""
import json
import shutil
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
import app as melb
import test_daily_foods as daily_tests


class SaltCalibrationTests(unittest.TestCase):
    def setUp(self):
        daily_tests.DailyLoggingTests.setUp(self)
        response = self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":1900})
        self.assertEqual(response.status_code, 200)

    def test_recipe_uses_preferred_seasoning_adjustment_in_formula_and_dashboard(self):
        result = melb.salt_spins_for(melb.load_foods(), {"Regular food":1900}, [])
        self.assertEqual(result["grams"], 1900)
        self.assertEqual(result["spins"], 92.0)
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">92.0', html)
        self.assertIn('1 spin / 20.65 g', html)
        self.assertIn('"saltGramsPerSpin": ' + str(melb.SALT_GRAMS_PER_SPIN), html)

    def test_new_locked_day_retains_calibration_after_future_adjustments(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        saved_rate = melb.SALT_GRAMS_PER_SPIN
        self.assertEqual(melb.locked_day_snapshot("2026-10-07")["salt_grams_per_spin"], saved_rate)
        with patch.object(melb, "SALT_GRAMS_PER_SPIN", 30):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltSpins">92.0', html)
            self.assertIn('"saltGramsPerSpin": ' + str(saved_rate), html)
            self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":False})
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltSpins">63.3', html)

    def test_existing_locked_day_keeps_original_twenty_nine_gram_rate(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        snapshot = melb.locked_day_snapshot("2026-10-07")
        del snapshot["salt_grams_per_spin"]
        with melb.db() as conn:
            conn.execute("UPDATE day_locks SET snapshot_json=? WHERE day=?",
                         (json.dumps(snapshot), "2026-10-07"))
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">65.5', html)
        self.assertIn('"saltGramsPerSpin": 29', html)
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":False})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">92.0', html)

    def test_shaker_measurement_and_half_measurement(self):
        calibration = {"salt_g_per_spin":4.5 / 60, "sodium_mg_per_spin":1769 / 60}
        self.assertEqual(melb.shaker_output_for(60, calibration), {"salt_g":4.5, "sodium_mg":1769})
        self.assertEqual(melb.shaker_output_for(30, calibration), {"salt_g":2.25, "sodium_mg":885})
        self.assertEqual(melb.shaker_output_for(80, calibration), {"salt_g":6, "sodium_mg":2359})
        self.assertEqual(melb.shaker_output_for(0, calibration), {"salt_g":0, "sodium_mg":0})

    def test_page_estimates_sixty_spins_and_uses_unrounded_spin_calculation(self):
        self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":60 * melb.SALT_GRAMS_PER_SPIN})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">60.0', html)
        self.assertIn('id="saltDispensed">4.50', html)
        self.assertIn('id="saltSodium">1,769', html)
        self.assertIn("added shaker salt only", html)
        # Use the full spin calculation, rather than the rounded displayed count.
        self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":100})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSodium">143', html)

    def test_locked_shaker_output_keeps_measured_dispensing_rates(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        saved = melb.locked_day_snapshot("2026-10-07")["shaker_calibration"]
        self.assertEqual(saved["salt_g_per_spin"], 4.5 / 60)
        self.assertEqual(saved["sodium_mg_per_spin"], 1769 / 60)
        with patch.object(melb, "SHAKER_SALT_G_PER_SPIN", .1), \
             patch.object(melb, "SHAKER_SODIUM_MG_PER_SPIN", 40):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltDispensed">6.90', html)
            self.assertIn('id="saltSodium">2,713', html)
            self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":False})
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltDispensed">9.20', html)
            self.assertIn('id="saltSodium">3,681', html)

    def test_older_snapshot_gets_initial_output_estimates_without_rewriting_snapshot(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        snapshot = melb.locked_day_snapshot("2026-10-07")
        del snapshot["shaker_calibration"]
        with melb.db() as conn:
            conn.execute("UPDATE day_locks SET snapshot_json=? WHERE day=?",
                         (json.dumps(snapshot), "2026-10-07"))
        with patch.object(melb, "SHAKER_SALT_G_PER_SPIN", .1):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltDispensed">6.90', html)
        self.assertNotIn("shaker_calibration", melb.locked_day_snapshot("2026-10-07"))

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for live calculator checks")
    def test_live_calculator_uses_measured_output_for_weight_and_salt_check_changes(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "dashboard.js").read_text(encoding="utf-8")
        functions = source[source.index("function isRiceForSpins"):source.index("function renderTotals")]
        harness = r"""
const assert = require("node:assert/strict");
const SALT_CATEGORY = "Dawg Bowl", SALT_GRAMS_PER_SPIN = 23.75;
const SHAKER_CALIBRATION = {salt_g_per_spin:4.5/60, sodium_mg_per_spin:1769/60};
function n(value) {return Number(value) || 0;}
function rounded(value, places=2) {const scale=10**places;return Math.round((value+Number.EPSILON)*scale)/scale;}
function food(amount, category, extra=0) {
  return {dataset:{amount, saltExtra:extra},closest(selector) {
    return {dataset:selector===".section" ? {category} : {unit:"g"}};
  }};
}
const included=food(380, "Dawg Bowl", 1.5);
const inputs=[included, food(10000, "Cream")];
const extra={name:"Carrot",serving_g:237.5,servings:2,include_in_spins:false};
const dayFoods=[extra], elements={};
const document={getElementById(id) {return elements[id] ||= {};}};
"""
        assertions = r"""
renderSaltSpins();
assert.equal(Number(elements.saltSpins.textContent),40);
assert.equal(elements.saltDispensed.textContent,"3.00");
assert.equal(elements.saltSodium.textContent,"1,179");
extra.include_in_spins=true;
renderSaltSpins();
assert.equal(Number(elements.saltSpins.textContent),60);
assert.equal(elements.saltDispensed.textContent,"4.50");
assert.equal(elements.saltSodium.textContent,"1,769");
included.dataset.amount=0; extra.include_in_spins=false;
renderSaltSpins();
assert.equal(elements.saltDispensed.textContent,"0.00");
assert.equal(elements.saltSodium.textContent,"0");
"""
        result = subprocess.run([shutil.which("node")], input=harness + functions + assertions,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_previous_locked_recipe_keeps_its_prior_recipe_rate(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        snapshot = melb.locked_day_snapshot("2026-10-07")
        snapshot["salt_grams_per_spin"] = 23.75
        with melb.db() as conn:
            conn.execute("UPDATE day_locks SET snapshot_json=? WHERE day=?",
                         (json.dumps(snapshot), "2026-10-07"))
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">80.0', html)
        self.assertIn('id="saltSodium">2,359', html)
        self.assertEqual(melb.locked_day_snapshot("2026-10-07"),snapshot)

    def test_screenshot_recipe_now_matches_preferred_eleven_point_one_grams(self):
        self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":1874})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">90.8', html)
        self.assertIn('id="saltSodium">2,676', html)
        grams = 1874 / melb.SALT_GRAMS_PER_SPIN * melb.SHAKER_SODIUM_MG_PER_SPIN / 241
        self.assertEqual(round(grams,2),11.10)
        self.assertEqual(melb.shaker_output_for(60,{
            "salt_g_per_spin":melb.SHAKER_SALT_G_PER_SPIN,
            "sodium_mg_per_spin":melb.SHAKER_SODIUM_MG_PER_SPIN}),
            {"salt_g":4.5,"sodium_mg":1769})


    def test_daily_percentage_changes_salt_but_not_macros_and_preserves_rice_setting(self):
        day="2026-10-07"
        self.client.post("/api/entry",json={"day":day,"food_name":"Regular food","amount":1000})
        macros=melb.day_totals_for(day)
        self.assertEqual(self.client.patch("/api/day-salt",json={"day":day,"salt_percent":.5}).status_code,200)
        html=self.client.get("/?day="+day).get_data(as_text=True)
        self.assertIn('1 spin / 15 g',html)
        self.assertIn('id="saltDispensed">5.00',html)
        self.assertEqual(melb.day_salt_percentage(day),.5)
        self.client.patch("/api/day-salt",json={"day":day,"rice_salted":True})
        self.assertEqual(melb.day_salt_percentage(day),.5)
        self.client.patch("/api/day-salt",json={"day":day,"salt_percent":.6})
        self.assertTrue(melb.day_rice_salted(day))
        self.assertEqual(melb.day_totals_for(day),macros)

    def test_future_default_does_not_change_today_past_days_or_pinned_future_day(self):
        self.client.post("/settings",data={"shortcut_name":"Test","default_salt_percent":".5"})
        self.assertIsNone(melb.day_salt_percentage("2026-10-06"))
        self.assertIsNone(melb.day_salt_percentage("2026-10-07"))
        self.assertEqual(melb.day_salt_percentage("2026-10-08"),.5)
        self.client.post("/settings",data={"shortcut_name":"Test","default_salt_percent":".6"})
        self.assertEqual(melb.day_salt_percentage("2026-10-08"),.5)
        self.assertEqual(melb.day_salt_percentage("2026-10-09"),.6)
        self.client.patch("/api/day-salt",json={"day":"2026-10-10","salt_percent":.7})
        self.assertEqual(melb.day_salt_percentage("2026-10-10"),.7)

    def test_percentage_is_frozen_when_locked_and_remains_after_unlock(self):
        day="2026-10-07"
        self.client.patch("/api/day-salt",json={"day":day,"salt_percent":.5})
        self.client.post("/api/day-lock",json={"day":day,"locked":True})
        snapshot=melb.locked_day_snapshot(day)
        self.assertEqual(snapshot["salt_grams_per_spin"],15)
        self.assertEqual(self.client.patch("/api/day-salt",json={"day":day,"salt_percent":.8}).status_code,423)
        self.client.post("/settings",data={"shortcut_name":"Test","default_salt_percent":".8"})
        self.assertEqual(melb.locked_day_snapshot(day),snapshot)
        self.assertIn('1 spin / 15 g',self.client.get("/?day="+day).get_data(as_text=True))
        self.client.post("/api/day-lock",json={"day":day,"locked":False})
        self.assertEqual(melb.day_salt_percentage(day),.5)

    def test_percentage_validation_rejects_invalid_requests_and_settings(self):
        for value in (0,-1,2.01,None,True,"","NaN","Infinity","no"):
            with self.subTest(value=value):
                self.assertEqual(self.client.patch("/api/day-salt",json={"day":"2026-10-07","salt_percent":value}).status_code,400)
        self.client.post("/settings",data={"shortcut_name":"Changed","default_salt_percent":"NaN"})
        self.assertEqual(melb.load_config()["shortcut_name"],"Test")
        self.assertIsNone(melb.default_salt_percentage("2026-10-08"))

    def test_schema_upgrade_preserves_existing_rice_preference(self):
        with melb.db() as conn:
            conn.execute("DROP TABLE day_salt_settings")
            conn.execute("CREATE TABLE day_salt_settings(day TEXT PRIMARY KEY,rice_salted INTEGER NOT NULL DEFAULT 0)")
            conn.execute("INSERT INTO day_salt_settings VALUES ('2026-10-07',1)")
        melb.init_db()
        self.assertTrue(melb.day_rice_salted("2026-10-07"))
        self.assertIsNone(melb.day_salt_percentage("2026-10-07"))
