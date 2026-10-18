"""Search selection copies per-100g macros and scales the logged portion."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
import app as melb
import food_lookup
import test_daily_foods as daily_tests


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for editor selection checks")
class FoodSelectionTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def test_selection_fills_macros_scales_weight_and_saves_only_selected_day(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "dashboard.js").read_text(encoding="utf-8")
        reset = source[source.index("function resetEditor()"):source.index("function chooseMode")]
        editor = source[source.index("function numericField"):source.index("function renderLookupResults")]
        reference = food_lookup.normalize_product(daily_tests.label_product(
            product_name="Rice Cake Bites", brands="Drizzilicious", serving_size="",
            serving_quantity=None, serving_quantity_unit="",
            nutriments={"energy-kcal_100g":429, "proteins_100g":4.76,
                        "carbohydrates_100g":71.4, "fat_100g":14.3, "fiber_100g":0}))
        known = food_lookup.normalize_product(daily_tests.label_product())
        carrot = food_lookup.lookup_foods("carrot")["products"][0]
        liquid = food_lookup._normalize_search_hit(daily_tests.label_product(
            serving_size="", serving_quantity=None, serving_quantity_unit="",
            quantity="250 ml", categories_tags=["en:beverages"]))
        fixtures = json.dumps({"reference":reference, "known":known, "carrot":carrot, "liquid":liquid})
        harness = r"""
const assert = require("node:assert/strict");
const DAY_LOCKED=false, dayLockChanging=false;
let portionState=null, selectedSource=null, savingFood=false;
const nutrientKeys=["calories","protein","carbs","fat","fiber"];
class Field extends EventTarget {
  constructor(value="") {super();this.value=value;this.children=[];this.readOnly=false;this.hidden=false;this.required=false;}
  get value() {return this._value;}
  set value(value) {this._value=String(value);}
  replaceChildren() {this.children=[];this.value="";}
  appendChild(child) {this.children.push(child);}
  setCustomValidity(value) {this.validityMessage=value;}
  focus() {}
}
const fields=Object.fromEntries(["name","serving_label","servings",...nutrientKeys].map(key=>[key,new Field()]));
const gramInput=new Field(), portionSelect=new Field(), elements={};
const dayFoodForm=new Field();
dayFoodForm.reset=()=>{
  Object.values(fields).forEach(field=>field.value="");
  fields.servings.value="1";fields.serving_label.value="1 serving";gramInput.value="";
};
const document={getElementById(id) {return elements[id] ||= new Field();},createElement() {return new Field();}};
const amountControls=new Map([[fields.servings,{sync(){},slider:new Field()}]]);
function n(value) {return Number(value)||0;}
function rounded(value,d=2) {const p=10**d;return Math.round((value+Number.EPSILON)*p)/p;}
function parseAmount(value) {return String(value).trim() && Number.isFinite(Number(value)) && Number(value)>=0 ? Number(value) : null;}
function trustedSource(value) {return value;}
function addSourceLink() {}
function setFoodStatus() {}
"""
        assertions = r"""
selectProduct(fixtures.reference,3);
assert.equal(fields.name.value,"Rice Cake Bites \u2014 Drizzilicious");
assert.equal(gramInput.value,"100");
assert.equal(portionSelect.value,"reference-100g");
assert.equal(fields.serving_label.value,"100 g (reference amount)");
assert.equal(fields.servings.value,"1","an unspecified item must not inherit a count");
for(const key of nutrientKeys) assert.equal(Number(fields[key].value),fixtures.reference[key]);
assert.equal(fields.calories.readOnly,false);
assert.equal(document.getElementById("basisWarning").hidden,false);
assert.equal(hasValidMacros(readFoodValues()),true);

gramInput.value="28";gramInput.dispatchEvent(new Event("input"));
assert.equal(Number(fields.calories.value),120.12);
assert.equal(Number(fields.protein.value),1.3328);
assert.equal(Number(fields.carbs.value),19.992);
assert.equal(Number(fields.fat.value),4.004);
assert.equal(Number(fields.fiber.value),0);
fields.servings.value="2";
const payload=readFoodValues();
assert.equal(payload.serving_g,28);
assert.equal(payload.servings,2);

// A manual correction must remain the density for later gram adjustments.
fields.calories.value="140";fields.calories.dispatchEvent(new Event("input"));
gramInput.value="56";gramInput.dispatchEvent(new Event("input"));
assert.equal(Number(fields.calories.value),280);
gramInput.value="";gramInput.dispatchEvent(new Event("input"));
assert.equal(hasValidMacros(readFoodValues()),false);

selectProduct(fixtures.known,1);
assert.equal(gramInput.value,"22");
assert.equal(Number(fields.calories.value),88);
assert.equal(fields.fiber.value,"","unknown fiber must not inherit a previous zero");
selectProduct(fixtures.carrot,2);
assert.equal(gramInput.value,"61");
assert.equal(fields.servings.value,"2");
assert.equal(Number(fields.calories.value),25.01);
selectProduct(fixtures.liquid,1);
assert.equal(portionState,null,"100 ml must not become 100 g");
assert.equal(fields.serving_label.value,"100 ml");
assert.equal(document.getElementById("portionControls").hidden,true);
assert.equal(Number(fields.calories.value),400);
assert.equal(readFoodValues().serving_g,null);
console.log(JSON.stringify(payload));
"""
        result = subprocess.run([shutil.which("node")],
                                input=harness + "\nconst fixtures=" + fixtures + ";\n" + reset + editor + assertions,
                                text=True, encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        response = self.client.post("/api/day-food", json={"day":"2026-10-07", **payload})
        self.assertEqual(response.status_code, 200)
        entry = response.json["entry"]
        self.assertEqual(entry["name"], "Rice Cake Bites \u2014 Drizzilicious")
        self.assertEqual(entry["serving_g"], 28)
        self.assertEqual(entry["calories"], 120.12)
        self.assertEqual(response.json["totals"]["calories"], 240.24)
        self.assertEqual(melb.load_day_foods("2026-10-06"), [])
