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

    def test_measured_recipe_is_eighty_spins_in_formula_and_dashboard(self):
        result = melb.salt_spins_for(melb.load_foods(), {"Regular food":1900}, [])
        self.assertEqual(result["grams"], 1900)
        self.assertEqual(result["spins"], 80)
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">80.0', html)
        self.assertIn('1 spin / 23.75 g', html)
        self.assertIn('"saltGramsPerSpin": 23.75', html)

    def test_new_locked_day_retains_calibration_after_future_adjustments(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        self.assertEqual(melb.locked_day_snapshot("2026-10-07")["salt_grams_per_spin"], 23.75)
        with patch.object(melb, "SALT_GRAMS_PER_SPIN", 30):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltSpins">80.0', html)
            self.assertIn('"saltGramsPerSpin": 23.75', html)
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
        self.assertIn('id="saltSpins">80.0', html)

    def test_shaker_measurement_and_half_measurement(self):
        calibration = {"salt_g_per_spin":4.5 / 60, "sodium_mg_per_spin":1769 / 60}
        self.assertEqual(melb.shaker_output_for(60, calibration), {"salt_g":4.5, "sodium_mg":1769})
        self.assertEqual(melb.shaker_output_for(30, calibration), {"salt_g":2.25, "sodium_mg":885})
        self.assertEqual(melb.shaker_output_for(80, calibration), {"salt_g":6, "sodium_mg":2359})
        self.assertEqual(melb.shaker_output_for(0, calibration), {"salt_g":0, "sodium_mg":0})

    def test_page_estimates_sixty_spins_and_uses_unrounded_spin_calculation(self):
        self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":1425})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSpins">60.0', html)
        self.assertIn('id="saltDispensed">4.50', html)
        self.assertIn('id="saltSodium">1,769', html)
        self.assertIn("added shaker salt only", html)
        # 100 g rounds to 4.2 spins, but output must use 100 / 23.75.
        self.client.post("/api/entry", json={
            "day":"2026-10-07", "food_name":"Regular food", "amount":100})
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltSodium">124', html)

    def test_locked_shaker_output_keeps_measured_dispensing_rates(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        saved = melb.locked_day_snapshot("2026-10-07")["shaker_calibration"]
        self.assertEqual(saved["salt_g_per_spin"], 4.5 / 60)
        self.assertEqual(saved["sodium_mg_per_spin"], 1769 / 60)
        with patch.object(melb, "SHAKER_SALT_G_PER_SPIN", .1), \
             patch.object(melb, "SHAKER_SODIUM_MG_PER_SPIN", 40):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltDispensed">6.00', html)
            self.assertIn('id="saltSodium">2,359', html)
            self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":False})
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
            self.assertIn('id="saltDispensed">8.00', html)
            self.assertIn('id="saltSodium">3,200', html)

    def test_older_snapshot_gets_initial_output_estimates_without_rewriting_snapshot(self):
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        snapshot = melb.locked_day_snapshot("2026-10-07")
        del snapshot["shaker_calibration"]
        with melb.db() as conn:
            conn.execute("UPDATE day_locks SET snapshot_json=? WHERE day=?",
                         (json.dumps(snapshot), "2026-10-07"))
        with patch.object(melb, "SHAKER_SALT_G_PER_SPIN", .1):
            html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="saltDispensed">6.00', html)
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
