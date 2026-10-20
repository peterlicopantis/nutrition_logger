"""Seasoning grams follow the live shaker sodium target without changing logs."""
import shutil
import subprocess
import unittest
from pathlib import Path
import app as melb
import test_daily_foods as daily_tests


class SeasoningCalculatorTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def test_panel_starts_collapsed_and_remains_available_on_locked_days(self):
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="seasoningToggle" type="button" aria-expanded="false"', html)
        self.assertIn('id="seasoningPanel" aria-label="Seasoning sodium calculator" hidden', html)
        self.client.post("/api/day-lock", json={"day":"2026-10-07", "locked":True})
        snapshot = melb.locked_day_snapshot("2026-10-07")
        html = self.client.get("/?day=2026-10-07").get_data(as_text=True)
        self.assertIn('id="seasoningServing" type="number"', html)
        self.assertNotIn('id="seasoningServing" disabled', html)
        self.assertEqual(melb.locked_day_snapshot("2026-10-07"), snapshot)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for live calculator checks")
    def test_seasoning_uses_serving_mass_updates_with_food_and_rejects_zero_sodium(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "dashboard.js").read_text(encoding="utf-8")
        functions = source[source.index("function isRiceForSpins"):source.index("function renderTotals")]
        harness = r"""
const assert=require("node:assert/strict");
const SALT_CATEGORY="Dawg Bowl"; let SALT_GRAMS_PER_SPIN=23.75;
const SHAKER_CALIBRATION={salt_g_per_spin:4.5/60,sodium_mg_per_spin:1769/60};
function n(value){return Number(value)||0;}
function rounded(value,places=2){const p=10**places;return Math.round((value+Number.EPSILON)*p)/p;}
const included={dataset:{amount:1900,saltExtra:0},closest(selector){
  return {dataset:selector===".section"?{category:"Dawg Bowl"}:{unit:"g"}};
}};
const inputs=[included],dayFoods=[];
const elements={seasoningServing:{value:"1"},seasoningSodium:{value:"241"}};
const document={getElementById(id){return elements[id] ||= {};}};
"""
        assertions = r"""
renderSaltSpins();
assert.equal(elements.seasoningResult.textContent,"Use ~9.79 g of seasoning to match ~2,359 mg sodium.");
assert.equal(seasoningGramsFor(1769,1,241),1769/241);
assert.equal(seasoningGramsFor(1769,2,241),1769/241*2);
elements.seasoningServing.value="2";
renderSeasoningCalculator();
assert.match(elements.seasoningResult.textContent,/Use ~19.57 g/);
elements.seasoningServing.value="1";
included.dataset.amount=1425;
renderSaltSpins();
assert.equal(elements.seasoningResult.textContent,"Use ~7.34 g of seasoning to match ~1,769 mg sodium.");
// Use the full calculated target, rather than reparsing rounded displayed mg.
included.dataset.amount=100;
elements.seasoningSodium.value="1";
renderSaltSpins();
assert.match(elements.seasoningResult.textContent,/Use ~124.14 g/);
included.dataset.amount=0;
renderSaltSpins();
assert.match(elements.seasoningResult.textContent,/Use ~0.00 g/);
for(const invalid of [0,-1,NaN,Infinity]) {
  assert.equal(seasoningGramsFor(1769,1,invalid),null);
  assert.equal(seasoningGramsFor(1769,invalid,241),null);
}
assert.equal(seasoningGramsFor(Infinity,1,241),null);
elements.seasoningSodium.value="0";renderSeasoningCalculator();
assert.match(elements.seasoningResult.textContent,/greater than zero/);
elements.seasoningSodium.value="";renderSeasoningCalculator();
assert.match(elements.seasoningResult.textContent,/Enter a serving size/);
elements.seasoningServing.value="0,5";
elements.seasoningSodium.value="241";
renderSeasoningCalculator(1769);
assert.match(elements.seasoningResult.textContent,/Use ~3.67 g/);
"""
        # The new recipe rate is sent by the server to the same live calculator.
        assertions += "\nSALT_GRAMS_PER_SPIN=" + repr(melb.SALT_GRAMS_PER_SPIN) + ";"
        assertions += r"""
included.dataset.amount=1874;
elements.seasoningServing.value="1";
elements.seasoningSodium.value="241";
renderSaltSpins();
assert.equal(elements.seasoningResult.textContent,"Use ~11.10 g of seasoning to match ~2,676 mg sodium.");
assert.equal(Number(elements.saltSpins.textContent),90.8);
"""
        result = subprocess.run([shutil.which("node")], input=harness+functions+assertions,
                                text=True, encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
