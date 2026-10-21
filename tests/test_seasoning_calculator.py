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


    def test_rice_setting_is_saved_per_day_and_reset_restores_unsalted(self):
        day = "2026-10-07"
        self.assertFalse(melb.day_rice_salted(day))
        response = self.client.patch("/api/day-salt",json={"day":day,"rice_salted":True})
        self.assertEqual(response.status_code,200)
        self.assertTrue(melb.day_rice_salted(day))
        self.assertFalse(melb.day_rice_salted("2026-10-06"))
        html = self.client.get("/?day="+day).get_data(as_text=True)
        self.assertIn('"riceSalted": true',html)
        self.client.post("/reset",data={"day":day})
        self.assertFalse(melb.day_rice_salted(day))

    def test_rice_setting_is_locked_and_older_locked_days_remain_unsalted(self):
        import json
        day = "2026-10-07"
        self.client.patch("/api/day-salt",json={"day":day,"rice_salted":True})
        self.client.post("/api/day-lock",json={"day":day,"locked":True})
        snapshot = melb.locked_day_snapshot(day)
        self.assertIs(snapshot["rice_salted"],True)
        response = self.client.patch("/api/day-salt",json={"day":day,"rice_salted":False})
        self.assertEqual(response.status_code,423)
        with melb.db() as conn:
            conn.execute("UPDATE day_salt_settings SET rice_salted=0 WHERE day=?",(day,))
        self.assertTrue(melb.day_rice_salted(day))
        del snapshot["rice_salted"]
        with melb.db() as conn:
            conn.execute("UPDATE day_locks SET snapshot_json=? WHERE day=?",(json.dumps(snapshot),day))
        self.assertFalse(melb.day_rice_salted(day))
        self.client.post("/api/day-lock",json={"day":day,"locked":False})
        self.assertEqual(self.client.patch("/api/day-salt",json={"day":day,"rice_salted":True}).status_code,200)

    def test_rice_setting_rejects_invalid_payloads(self):
        for value in (None,"true",1,[],{}):
            self.assertEqual(self.client.patch("/api/day-salt",json={"day":"2026-10-07","rice_salted":value}).status_code,400)
        for payload in ({},{"day":"bad","rice_salted":True},[]):
            self.assertEqual(self.client.patch("/api/day-salt",json=payload).status_code,400)
        self.assertFalse(melb.day_rice_salted("2026-10-07"))

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for rice split checks")
    def test_rice_split_and_seasoning_preserve_the_unsalted_total(self):
        source=(Path(__file__).resolve().parents[1]/"static/dashboard.js").read_text()
        functions=source[source.index("function isRiceForSpins"):source.index("function renderTotals")]
        harness=r"""
const assert=require("node:assert/strict");
const SALT_CATEGORY="Dawg Bowl";let SALT_GRAMS_PER_SPIN=23.75;
const SHAKER_CALIBRATION={salt_g_per_spin:4.5/60,sodium_mg_per_spin:1769/60};
function n(v){return Number(v)||0;}
function rounded(v,p=2){return Math.round((v+Number.EPSILON)*10**p)/10**p;}
function food(name,amount,category="Dawg Bowl",factor=0){
 return {dataset:{name,amount,saltExtra:factor},closest(selector){
  return {dataset:selector===".section"?{category}:{unit:"g"}};
 }};
}
const rice=food("Enriched Rice",185,"Dawg Bowl",1.5),bowl=food("Chicken",1000);
const inputs=[rice,bowl,food("Rice",1000,"Cream",1.5)],dayFoods=[],elements={};
const document={getElementById(id){return elements[id]||={};}};
elements.seasoningServing={value:"1"};elements.seasoningSodium={value:"241"};
elements.riceSalted={checked:false};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,String(a)+" != "+String(b));
"""
        assertions=r"""
renderSaltSpins();near(computeSaltSpins().grams,1462.5);
const original=elements.seasoningResult.textContent;
elements.riceSalted.checked=true;renderSaltSpins();
let plan=saltedRicePlan();
near(plan.riceSaltG,3);near(plan.riceSpins,40);
near(plan.riceSodiumMg,1769/4.5*3);
near(plan.bowlSaltG,1462.5/23.75*.075-3);
near(plan.riceSaltG+plan.bowlSaltG,computeSaltSpins().saltDispensed);
near(plan.riceSodiumMg+plan.bowlSodiumMg,computeSaltSpins().sodiumMg);
assert.match(elements.riceSaltAmount.textContent,/3.00 g salt/);
assert.match(elements.bowlSaltAmount.textContent,/1.62 g salt/);
assert.equal(elements.unsaltedSaltSummary.hidden,true);
elements.riceSeasoningServing.value="1";elements.riceSeasoningSodium.value="241";
renderSeasoningCalculator();
assert.match(elements.riceSeasoningResult.textContent,/Use ~4.89 g/);
assert.match(elements.bowlSeasoningResult.textContent,/Enter a serving size/);
elements.bowlSeasoningServing.value="2";elements.bowlSeasoningSodium.value="100";
renderSeasoningCalculator();
assert.match(elements.bowlSeasoningResult.textContent,/Use ~12.72 g/);
assert.match(elements.riceSeasoningResult.textContent,/Use ~4.89 g/);
elements.riceSeasoningSodium.value="";renderSeasoningCalculator();
assert.match(elements.riceSeasoningResult.textContent,/Enter a serving size/);
assert.match(elements.bowlSeasoningResult.textContent,/Use ~12.72 g/);
elements.riceSeasoningSodium.value="0";renderSeasoningCalculator();
assert.match(elements.riceSeasoningResult.textContent,/greater than zero/);
assert.equal(elements.seasoningToggle.hidden,true);
dayFoods.push({name:"Rice",serving_g:185,servings:1,include_in_spins:true,salt_extra_weight_factor:2},
 {name:"Rice",serving_g:185,servings:10,include_in_spins:false});
plan=saltedRicePlan();near(plan.riceSaltG,6);
near(plan.riceSaltG+plan.bowlSaltG,computeSaltSpins().saltDispensed);
dayFoods.push({name:"Carrot",serving_g:100,servings:1,include_in_spins:true,salt_extra_weight_factor:.5});
near(saltedRicePlan().riceSpins+saltedRicePlan().bowlSpins,computeSaltSpins().spins);
dayFoods.length=0;
elements.riceSalted.checked=false;renderSaltSpins();
assert.equal(elements.seasoningResult.textContent,original);
assert.equal(elements.riceSaltBreakdown.hidden,true);
rice.dataset.amount=0;near(saltedRicePlan().riceSaltG,0);
rice.dataset.amount=185;bowl.dataset.amount=0;near(saltedRicePlan().bowlSaltG,0);
near(saltedRicePlan().riceSaltG,computeSaltSpins().saltDispensed);
assert.equal(saltedRicePlan().riceLimited,true);
elements.riceSalted.checked=true;renderSaltSpins();
assert.match(elements.riceSaltAllocationNote.textContent,/limited/);
assert.equal(elements.riceSaltAllocationNote.hidden,false);
rice.dataset.amount=0;near(saltedRicePlan().bowlSaltG,0);
// Reproduce the screenshot using the actual calibrated recipe rate.
SALT_GRAMS_PER_SPIN=SCREENSHOT_GRAMS_PER_SPIN;
rice.dataset.amount=400;bowl.dataset.amount=859.4;
plan=saltedRicePlan();
near(plan.riceSaltG,400*3/185);
near(plan.riceSaltG+plan.bowlSaltG,computeSaltSpins().saltDispensed);
near(plan.riceSodiumMg+plan.bowlSodiumMg,computeSaltSpins().sodiumMg);
renderSaltSpins();
near(parseFloat(elements.riceSaltAmount.textContent)+parseFloat(elements.bowlSaltAmount.textContent),
     rounded(computeSaltSpins().saltDispensed,2));
const labelGrams=4,labelSodium=241;
near(seasoningGramsFor(plan.riceSodiumMg,labelGrams,labelSodium)+
     seasoningGramsFor(plan.bowlSodiumMg,labelGrams,labelSodium),
     seasoningGramsFor(computeSaltSpins().sodiumMg,labelGrams,labelSodium));
// Match the real older HTML: missing controls return null, not stub objects.
rice.dataset.amount=185;bowl.dataset.amount=1000;
elements.riceSalted.checked=true;
const originalGet=document.getElementById.bind(document);
document.getElementById=id=>/^(rice|bowl)Seasoning/.test(id)||id==="dashboardActions"?null:originalGet(id);
renderSaltSpins();
assert.equal(elements.seasoningToggle.hidden,false);
assert.match(elements.seasoningResult.textContent,/Rice: Use/);
assert.match(elements.seasoningResult.textContent,/Rest of bowl: Use/);
assert.match(elements.seasoningResult.textContent,/4.89 g/);
"""
        result=subprocess.run([shutil.which("node")],input=harness+functions+assertions.replace("SCREENSHOT_GRAMS_PER_SPIN",repr(melb.SALT_GRAMS_PER_SPIN)),
                              text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for variable ratio checks")
    def test_variable_ratios_are_independent_and_total_salt_and_seasonings_agree(self):
        source=(Path(__file__).resolve().parents[1]/"static/dashboard.js").read_text()
        functions=source[source.index("function isRiceForSpins"):source.index("function renderTotals")]
        harness=r"""
const assert=require("node:assert/strict");
const SALT_CATEGORY="Dawg Bowl",SALT_GRAMS_PER_SPIN=20.65;
const SHAKER_CALIBRATION={salt_g_per_spin:.075,sodium_mg_per_spin:1769/60};
function n(v){return Number(v)||0;}
function rounded(v,p=2){return Math.round((v+Number.EPSILON)*10**p)/10**p;}
function food(name,amount,factor=0,category="Dawg Bowl"){
 return {dataset:{name,amount,saltExtra:factor},closest(selector){return {dataset:selector===".section"?{category}:{unit:"g"}}}};
}
const rice=food("Enriched Rice",185,1.5),meal=food("Chicken",500,3);
const inputs=[rice,meal,food("Rice",1000,0,"Cream")],dayFoods=[],elements={};
const document={getElementById(id){return elements[id]||={};}};
elements.riceRatioInput={value:"3"};elements.mealRatioInput={value:".5"};
elements.saltVariableMode={checked:false};elements.riceSalted={checked:false};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,String(a)+" != "+String(b));
"""
        assertions=r"""
const shared=computeSaltSpins();
renderSaltSpins();assert.equal(elements.saltCombinedTotal.hidden,true);
elements.saltVariableMode.checked=true;renderSaltSpins();
let plan=variableSaltPlan();
near(plan.riceSaltG,3);near(plan.bowlSaltG,2.5);near(plan.totalSaltG,5.5);
near(plan.totalSodiumMg,5.5*1769/4.5);
const shownRice=Number(elements.riceSaltDetails.textContent.match(/([0-9,]+) mg sodium/)[1].replaceAll(",",""));
const shownMeal=Number(elements.bowlSaltDetails.textContent.match(/([0-9,]+) mg sodium/)[1].replaceAll(",",""));
near(shownRice+shownMeal,Math.round(plan.totalSodiumMg));
assert.equal(elements.saltRatioControls.hidden,true);
assert.equal(elements.riceSaltToggle.hidden,true);
assert.equal(elements.riceSaltBreakdown.hidden,false);
assert.match(elements.saltCombinedTotal.textContent,/5.50 g/);
// Rice has its own ratio and is never capped to a shared total.
elements.riceRatioInput.value="6";renderSaltSpins();
near(variableSaltPlan().riceSaltG,6);near(variableSaltPlan().bowlSaltG,2.5);
elements.mealRatioInput.value="1";renderSaltSpins();
near(variableSaltPlan().riceSaltG,6);near(variableSaltPlan().bowlSaltG,5);
near(variableSaltPlan().totalSaltG,11);
// Use different labels without sharing inputs between portions.
elements.riceSeasoningServing.value="1";elements.riceSeasoningSodium.value="241";
elements.bowlSeasoningServing.value="2";elements.bowlSeasoningSodium.value="100";
renderSeasoningCalculator();
assert.match(elements.riceSeasoningResult.textContent,/Use ~9.79 g/);
assert.match(elements.bowlSeasoningResult.textContent,/Use ~39.31 g/);
// Checked temporary foods count at actual mass, with no extra-weight multiplier.
dayFoods.push({name:"Rice",serving_g:185,servings:1,include_in_spins:true,salt_extra_weight_factor:9},
 {name:"Carrot",serving_g:100,servings:2,include_in_spins:true,salt_extra_weight_factor:20},
 {name:"Rice",serving_g:185,servings:10,include_in_spins:false});
plan=variableSaltPlan();near(plan.riceGrams,370);near(plan.mealGrams,700);
near(plan.riceSaltG,12);near(plan.bowlSaltG,7);
dayFoods.length=0;
elements.saltVariableMode.checked=false;renderSaltSpins();
near(computeSaltSpins().saltDispensed,shared.saltDispensed);
assert.equal(elements.saltRatioControls.hidden,false);
assert.equal(elements.saltCombinedTotal.hidden,true);
elements.saltVariableMode.checked=true;
elements.riceRatioInput.value="0";elements.mealRatioInput.value="0";
near(variableSaltPlan().totalSaltG,0);near(variableSaltPlan().totalSodiumMg,0);
rice.dataset.amount=0;meal.dataset.amount=0;
near(variableSaltPlan().riceSaltG,0);near(variableSaltPlan().bowlSaltG,0);
"""
        result=subprocess.run([shutil.which("node")],input=harness+functions+assertions,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for reset interaction checks")
    def test_reset_waits_for_pending_save_and_restores_all_ratios(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "dashboard.js").read_text(encoding="utf-8")
        handlers = source[source.index("function syncSaltBoxUI()"):source.index("// This is an independent calculator")]
        harness = r"""
const assert=require("node:assert/strict");
const elements=new Map();
function element(id){
 if(!elements.has(id)) elements.set(id,{id,disabled:false,value:"9",dataset:{},
  addEventListener(type,fn){this[type]=fn;},setCustomValidity(){},textContent:""});
 return elements.get(id);
}
const document={getElementById:element};
let DAY_LOCKED=false,dayLockChanging=false,resettingSaltRatios=false,pendingSaves=1;
let confirmedSaltPercent=.9,SALT_GRAMS_PER_SPIN=1;
const DAY="2026-10-07",SHAKER_CALIBRATION={salt_g_per_spin:.075};
const variableControlIds=["saltVariableMode","riceRatioInput","riceRatioSlider","mealRatioInput","mealRatioSlider"];
let confirmedVariableSettings={salt_mode:"variable",rice_salt_per_185:9,meal_salt_percent:1};
let finishPrior;
let riceSavePromise=new Promise(resolve=>{finishPrior=resolve;});
const saveErrors=new Set();let requests=0;
function syncSaltChoiceSelection(){}
function showSaveStatus(){syncSaltBoxUI();}
function applyDayEditingState(){
 for(const id of ["riceSalted","saltPercentInput",...variableControlIds]) element(id).disabled=resettingSaltRatios;
 syncSaltBoxUI();
}
function syncVariableSettings(settings){
 element("riceRatioInput").value=String(settings.rice_salt_per_185);
 element("mealRatioInput").value=String(settings.meal_salt_percent);
}
function renderSaltSpins(){}
async function requestJson(url,options){
 requests++;
 assert.deepEqual(JSON.parse(options.body),{day:DAY,reset_ratios:true});
 return {salt_percent:.4,salt_mode:"variable",rice_salt_per_185:3,meal_salt_percent:.5};
}
""" + handlers + r"""
(async()=>{
 assert.equal(element("resetSaltRatios").disabled,false);
 element("resetSaltRatios").click();
 assert.equal(resettingSaltRatios,true);
 assert.equal(element("resetSaltRatios").disabled,true);
 assert.equal(element("riceRatioInput").disabled,true);
 assert.equal(requests,0);
 pendingSaves--;finishPrior();
 await riceSavePromise;
 assert.equal(requests,1);
 assert.equal(confirmedSaltPercent,.4);
 assert.equal(element("riceRatioInput").value,"3");
 assert.equal(element("mealRatioInput").value,"0.5");
 assert.equal(confirmedVariableSettings.salt_mode,"variable");
 assert.equal(pendingSaves,0);
 assert.equal(element("resetSaltRatios").disabled,false);
 DAY_LOCKED=true;syncSaltBoxUI();
 assert.equal(element("resetSaltRatios").disabled,true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run(["node","-e",harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
