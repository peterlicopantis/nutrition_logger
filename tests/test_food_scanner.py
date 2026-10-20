"""Phone scanning uses local photo processing and the existing review editor."""
import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

import test_daily_foods as daily_tests

ROOT = Path(__file__).resolve().parents[1]


class _Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids[values["id"]] = (tag, values)


class FoodScannerPageTests(unittest.TestCase):
    setUp = daily_tests.DailyLoggingTests.setUp

    def test_phone_capture_controls_use_existing_unsaved_editor(self):
        response = self.client.get("/?day=2026-10-07")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        elements = _Elements()
        elements.feed(html)
        for field_id in ("barcodePhoto", "nutritionLabelPhoto"):
            tag, attrs = elements.ids[field_id]
            self.assertEqual(tag, "input")
            self.assertEqual(attrs["type"], "file")
            self.assertEqual(attrs["accept"], "image/*")
            self.assertEqual(attrs["capture"], "environment")
            self.assertNotIn("name", attrs, "photos must not be form-uploaded")
        for button_id in ("scanBarcodeButton", "scanLabelButton", "cancelFoodScan",
                          "photoBarcodeButton", "photoLabelButton", "captureFoodNow"):
            self.assertEqual(elements.ids[button_id][1]["type"], "button")
        self.assertIn(".phone-food-scan { display:none; }", html)
        self.assertIn(".phone-food-scan { display:block; }", html)
        self.assertIn('(max-width:900px) and (pointer:coarse)', html)
        video_tag, video_attrs = elements.ids["foodCameraVideo"]
        self.assertEqual(video_tag, "video")
        for attribute in ("autoplay", "muted", "playsinline"):
            self.assertIn(attribute, video_attrs)
        self.assertIn("hidden", elements.ids["foodLiveCamera"][1])
        self.assertIn("live_food_camera.js", html)
        self.assertIn("live_label_detector.js", html)
        self.assertIn("nutrition_label.js", html)
        self.assertIn("food_scanner.js", html)
        self.assertIn("dfGrams", elements.ids)
        self.assertIn("dfAmount", elements.ids)

    def test_scanner_and_every_pinned_vendor_asset_are_served_locally(self):
        manifest_path = ROOT / "static/vendor/food-scan/asset-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = ["food_scanner.js", "nutrition_label.js", "live_food_camera.js", "live_label_detector.js"] + [
            "vendor/food-scan/" + path for path in manifest["files"]
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get("/static/" + path)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.get_data())
                    self.assertNotIn("Location", response.headers)
                finally:
                    response.close()


HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const sources = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map(), documentEvents = new Map(), windowEvents = new Map();
const observed = new Map();
const nativeTimeout=globalThis.setTimeout,nativeClearTimeout=globalThis.clearTimeout;
const cameraTimers=new Map();let cameraTimerId=-1;
globalThis.setTimeout=(fn,ms)=>{
  if(ms===700){const id=cameraTimerId--;cameraTimers.set(id,fn);return id;}
  return nativeTimeout(fn,ms);
};
globalThis.clearTimeout=id=>{
  if(cameraTimers.has(id))cameraTimers.delete(id);else nativeClearTimeout(id);
};
class Element {
  constructor(id="") {
    this.id=id; this.listeners=new Map(); this.dataset={}; this.hidden=false;
    this.value=""; this.textContent=""; this.open=true; this.files=[];
    this.attrs={}; this.clicked=0; this.parentIds=[];
    this.classList={toggle(){}};
    this.srcObject=null;this.videoWidth=4000;this.videoHeight=3000;this.readyState=4;
    this.plays=0;this.pauses=0;
  }
  addEventListener(type,fn) {
    if(!this.listeners.has(type)) this.listeners.set(type,[]);
    this.listeners.get(type).push(fn);
  }
  removeEventListener(type,fn) {
    this.listeners.set(type,(this.listeners.get(type)||[]).filter(listener=>listener!==fn));
  }
  async play(){this.plays++;}
  pause(){this.pauses++;}
  async fire(type,target=this) {
    for(const fn of this.listeners.get(type)||[]) await fn({target});
  }
  click() { this.clicked++; for(const fn of this.listeners.get("click")||[]) fn({target:this}); }
  setAttribute(key,value) { this.attrs[key]=String(value); }
  focus() {}
  remove() {}
  matches(selector) {
    return selector.split(",").some(part=>{
      part=part.trim();
      return part==="#"+this.id || (part[0]==="." && String(this.className||"").split(" ").includes(part.slice(1)));
    });
  }
  closest(selector) {
    return selector.split(",").some(part=>{
      part=part.trim();
      return part==="#"+this.id || (part[0]==="#" && this.parentIds.includes(part.slice(1)));
    }) ? this : null;
  }
  set disabled(value) {
    this._disabled=Boolean(value);
    if(observed.has(this)) observed.get(this)();
  }
  get disabled() { return this._disabled||false; }
  getContext() {return {fillStyle:"",fillRect(){},drawImage(){},translate(){},rotate(){}};}
}
function get(id) {if(!elements.has(id)) elements.set(id,new Element(id)); return elements.get(id);}
const document={
  hidden:false,
  getElementById:get,
  createElement(tag){return new Element(tag);},
  head:{appendChild(){throw new Error("Unexpected remote or dynamic asset load in mocked scan");}},
  addEventListener(type,fn){
    if(!documentEvents.has(type)) documentEvents.set(type,[]);
    documentEvents.get(type).push(fn);
  },
  removeEventListener(type,fn){
    documentEvents.set(type,(documentEvents.get(type)||[]).filter(listener=>listener!==fn));
  }
};
function documentEvent(type,target) {
  for(const fn of Array.from(documentEvents.get(type)||[])) fn({target});
}
globalThis.document=document;
globalThis.window=globalThis;
globalThis.location={href:"http://melb.test:8501/?day=2026-10-07"};
globalThis.addEventListener=(type,fn)=>{
  if(!windowEvents.has(type))windowEvents.set(type,new Set());
  windowEvents.get(type).add(fn);
};
globalThis.removeEventListener=(type,fn)=>windowEvents.get(type)?.delete(fn);
function windowEvent(type){for(const fn of Array.from(windowEvents.get(type)||[]))fn();}
globalThis.isSecureContext=false;
const cameraRequests=[],cameraStreams=[];
let cameraDeferred=null;
function mediaStream(){
  const track=new Element("camera-track");track.stopped=0;track.stop=()=>track.stopped++;
  const other=new Element("other-track");other.stopped=0;other.stop=()=>other.stopped++;
  return {track,other,getTracks(){return [track,other];},getVideoTracks(){return [track];}};
}
Object.defineProperty(globalThis,"navigator",{configurable:true,value:{mediaDevices:{
  async getUserMedia(constraints){
    cameraRequests.push(constraints);
    if(cameraDeferred)return cameraDeferred.promise;
    const stream=mediaStream();cameraStreams.push(stream);return stream;
  }
}}});
globalThis.MutationObserver=class {
  constructor(fn){this.fn=fn;}
  observe(target){observed.set(target,this.fn);}
};
const createdPhotos=[], revokedPhotos=[];
URL.createObjectURL=file=>{const url="blob:photo-"+createdPhotos.length;createdPhotos.push({url,file});return url;};
URL.revokeObjectURL=url=>revokedPhotos.push(url);
globalThis.Image=class {
  constructor(){this.naturalWidth=4000;this.naturalHeight=3000;}
  async decode(){}
};
globalThis.fetch=()=>{throw new Error("Photo upload or unmocked external network attempted");};
var DAY_LOCKED=false,dayLockChanging=false,savingFood=false,lookupInputValue="";
const saveDayFood=get("saveDayFood"),foodQuery=get("foodQuery"),dayFoodForm=get("dayFoodForm"),fields={name:get("dfName")};
get("foodScanPanel").dataset.assets="/static/vendor/food-scan/";
get("dfName").parentIds=["dayFoodForm"];
const loaded=[], selected=[], requests=[], workerOptions=[],workers=[],recognitionInputs=[],ocrResponses=[];
let invalidations=0,workerCreates=0,workerTerminates=0,recognitions=0,barcodeDecodes=0;
let workerInitDeferred=null,activeRecognitions=0,maxRecognitions=0;
let ocrDeferred=null,lookupDeferred=null,barcodeValue="0038000000001",chosenMode=null;
let ocrText="Nutrition Facts\nServing size 1 bar (22 g)\nCalories 120\nTotal Carbohydrate 18 g\nProtein 6 g";
function invalidateLookup(){invalidations++;}
function loadManualFood(food){loaded.push({...food});}
function selectProduct(product,count){selected.push({product,count});}
function chooseMode(manual){chosenMode=manual;}
async function requestJson(url,options={}) {
  requests.push({url,options});
  return lookupDeferred ? lookupDeferred.promise : {products:[{name:"Matched food",serving_g:22}]};
}
globalThis.Tesseract={
  async createWorker(language,oem,options){
    workerCreates++;workerOptions.push({language,oem,...options});
    const created={recognitionCalls:0,terminations:0,
      async recognize(canvas,options,output){
        assert.equal(options.tessedit_pageseg_mode,"11");
        assert.deepEqual(output,{text:true,blocks:true});
        recognitions++;created.recognitionCalls++;recognitionInputs.push({width:canvas.width,height:canvas.height});
        assert.ok(canvas.width===1600||canvas.width===2400);
        assert.equal(canvas.height,canvas.width*3/4);
        activeRecognitions++;maxRecognitions=Math.max(maxRecognitions,activeRecognitions);
        try{return await (ocrResponses.length ? ocrResponses.shift() :
          ocrDeferred ? ocrDeferred.promise : {data:{text:ocrText,confidence:90}});}
        finally{activeRecognitions--;}
      },
      async terminate(){workerTerminates++;created.terminations++;}
    };
    workers.push(created);
    if(workerInitDeferred)await workerInitDeferred.promise;
    return created;
  }
};
globalThis.ZXingBrowser={BrowserMultiFormatReader:class {
  async decodeFromCanvas(){barcodeDecodes++;return {getText(){return barcodeValue;}};}
}};
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function tick(){return new Promise(resolve=>setTimeout(resolve,0));}
async function cameraFrame(){
  await until(()=>cameraTimers.size===1);
  const [id,fn]=cameraTimers.entries().next().value;cameraTimers.delete(id);fn();
  await tick();
}
function labelData(text=ocrText){return {data:{text,confidence:90}};}
function completeLabel(calories=120){return "Nutrition Facts\nServing size 1 bar (22 g)\nCalories "+calories+
  "\nTotal Fat 4 g\nTotal Carbohydrate 18 g\nProtein 6 g";}
async function until(test){
  for(let count=0;count<100;count++){if(test())return;await tick();}
  assert.fail("Mock scanner did not reach expected phase");
}
function file(name="photo.jpg"){return {name,type:"image/jpeg",size:1234};}
async function photo(id){
  get(id).files=[file()];
  return get(id).fire("change");
}
vm.runInThisContext(sources.parser,{filename:"nutrition_label.js"});
globalThis.NutritionLabel=module.exports;
vm.runInThisContext("(function(){const module=undefined,require=undefined;"+sources.detector+"\n})();",{filename:"live_label_detector.js"});
vm.runInThisContext(sources.camera,{filename:"live_food_camera.js"});
vm.runInThisContext(sources.scanner,{filename:"food_scanner.js"});
"""

@unittest.skipUnless(shutil.which("node"), "Node.js is needed for scanner behavior checks")
class FoodScannerBehaviorTests(unittest.TestCase):
    def run_scan(self, assertions):
        source = {
            "parser": (ROOT / "static/nutrition_label.js").read_text(encoding="utf-8"),
            "scanner": (ROOT / "static/food_scanner.js").read_text(encoding="utf-8"),
            "camera": (ROOT / "static/live_food_camera.js").read_text(encoding="utf-8"),
            "detector": (ROOT / "static/live_label_detector.js").read_text(encoding="utf-8"),
        }
        program = HARNESS + "\n(async()=>{\n" + assertions + r"""
windowEvent("pagehide");
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which("node"), "-e", program],
                                input=json.dumps(source), text=True, capture_output=True,
                                timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_label_populates_review_with_unknown_values_blank_and_local_paths(self):
        self.run_scan(r"""
get("nutritionLabelPhoto").value="old-photo";
get("scanLabelButton").click();
assert.equal(get("nutritionLabelPhoto").clicked,1);
assert.equal(get("nutritionLabelPhoto").value,"");
assert.equal(get("scanLabelButton").disabled,false,"canceling native camera must not leave scan busy");
await photo("nutritionLabelPhoto");
assert.equal(loaded.length,1);
assert.equal(loaded[0].name,"");
assert.equal(loaded[0].serving_g,22);
assert.equal(loaded[0].calories,120);
assert.equal(loaded[0].carbs,18);
assert.equal(loaded[0].protein,6);
assert.equal(loaded[0].fat,null,"unread fat must stay blank instead of becoming zero");
assert.equal(loaded[0].fiber,null);
assert.equal(loaded[0].source_url,"");
assert.equal(requests.length,0,"label photos must not leave the browser");
assert.equal(get("foodScanText").hidden,false);
assert.match(get("dayFoodEditorHeading").textContent,/Review/);
for(const path of ["workerPath","corePath","langPath"])
  assert.equal(new URL(workerOptions[0][path]).origin,"http://melb.test:8501");
assert.equal(workerOptions[0].workerBlobURL,false);
assert.equal(workerOptions[0].legacyCore,false);
assert.equal(workerOptions[0].legacyLang,false);
await photo("nutritionLabelPhoto");
assert.equal(workerCreates,1,"sequential photos reuse one OCR worker");
assert.equal(loaded.length,2);
assert.deepEqual(revokedPhotos,createdPhotos.map(item=>item.url));
""")

    def test_late_label_result_cannot_replace_a_new_manual_draft(self):
        self.run_scan(r"""
ocrDeferred=deferred();
const pending=photo("nutritionLabelPhoto");
await until(()=>recognitions===1);
assert.equal(get("scanLabelButton").disabled,true);
fields.name.value="My later manual draft";
documentEvent("input",fields.name);
assert.equal(get("cancelFoodScan").hidden,true);
ocrDeferred.resolve({data:{text:ocrText}});
await pending;
assert.equal(loaded.length,0);
assert.equal(fields.name.value,"My later manual draft");
assert.equal(workerTerminates,1);
assert.equal(get("scanLabelButton").disabled,false);
assert.deepEqual(revokedPhotos,createdPhotos.map(item=>item.url));
""")

    def test_barcode_uses_only_digit_get_query_and_preserves_leading_zero(self):
        self.run_scan(r"""
await photo("barcodePhoto");
assert.equal(requests.length,1);
assert.equal(requests[0].url,"/api/food-lookup?q=0038000000001");
assert.equal(requests[0].options.body,undefined,"no photo data may be sent");
assert.equal(selected.length,1);
assert.equal(selected[0].product.name,"Matched food");
assert.equal(selected[0].count,1);
assert.equal(chosenMode,false,"barcode results must leave manual mode");
assert.equal(foodQuery.value,"0038000000001");
barcodeValue="https://example.com/0038000000001";
await photo("barcodePhoto");
assert.equal(requests.length,1,"decoded QR URLs must not be followed or searched");
assert.equal(selected.length,1);
assert.match(get("foodScanStatus").textContent,/Couldn't read a product barcode/);
assert.deepEqual(revokedPhotos,createdPhotos.map(item=>item.url));
""")

    def test_late_barcode_lookup_cannot_override_a_new_editor(self):
        self.run_scan(r"""
lookupDeferred=deferred();
const pending=photo("barcodePhoto");
await until(()=>requests.length===1);
const signal=requests[0].options.signal;
documentEvent("click",get("manualMode"));
assert.equal(signal.aborted,true);
lookupDeferred.resolve({products:[{name:"Too late"}]});
await pending;
assert.equal(selected.length,0);
assert.equal(loaded.length,0);
assert.equal(get("scanBarcodeButton").disabled,false);
""")

    def test_locked_days_and_pending_saves_block_capture(self):
        self.run_scan(r"""
DAY_LOCKED=true;
saveDayFood.disabled=true;
assert.equal(get("scanBarcodeButton").disabled,true);
assert.equal(get("scanLabelButton").disabled,true);
get("scanBarcodeButton").click();
await photo("barcodePhoto");
assert.equal(get("barcodePhoto").clicked,0);
assert.equal(requests.length,0);
DAY_LOCKED=false;savingFood=true;saveDayFood.disabled=true;
assert.equal(get("scanLabelButton").disabled,true);
await photo("nutritionLabelPhoto");
assert.equal(workerCreates,0);
savingFood=false;dayLockChanging=true;saveDayFood.disabled=true;
assert.equal(get("scanBarcodeButton").disabled,true);
dayLockChanging=false;saveDayFood.disabled=false;
assert.equal(get("scanLabelButton").disabled,false);
await photo("nutritionLabelPhoto");
assert.equal(loaded.length,1);
""")

    def test_change_slider_keys_and_search_clear_cancel_pending_scan(self):
        self.run_scan(r"""
const slider=get("dfAmountSlider");
slider.className="amount-range";slider.parentIds=["dayFoodForm"];
const actions=[
  ()=>documentEvent("change",fields.name),
  ()=>dayFoodForm.fire("keydown",slider),
  ()=>foodQuery.fire("search")
];
for(let index=0;index<actions.length;index++){
  ocrDeferred=deferred();
  const pending=photo("nutritionLabelPhoto");
  await until(()=>recognitions===index+1);
  documentEvent("visibilitychange",get("body"));
  assert.equal(get("cancelFoodScan").hidden,false,"native camera backgrounding alone must not cancel");
  await actions[index]();
  assert.equal(get("cancelFoodScan").hidden,true);
  ocrDeferred.resolve({data:{text:ocrText}});
  await pending;
  assert.equal(loaded.length,0,"a later control edit must win over stale OCR");
  assert.equal(get("scanLabelButton").disabled,false);
}
""")

    def test_live_barcode_auto_captures_and_opens_an_unsaved_product_draft(self):
        self.run_scan(r"""
isSecureContext=true;
get("scanBarcodeButton").click();
await until(()=>cameraTimers.size===1);
assert.equal(cameraRequests.length,1);
assert.equal(cameraRequests[0].audio,false);
assert.equal(cameraRequests[0].video.facingMode.ideal,"environment");
assert.equal(get("foodLiveCamera").hidden,false);
assert.equal(get("barcodePhoto").clicked,0,"live scanning must use the embedded preview");
await cameraFrame();
await until(()=>selected.length===1);
assert.equal(cameraStreams[0].track.stopped,1);
assert.equal(cameraStreams[0].other.stopped,1);
assert.equal(get("foodCameraVideo").srcObject,null);
assert.equal(get("foodLiveCamera").hidden,true);
assert.equal(get("scanBarcodeButton").disabled,false);
assert.equal(selected[0].product.name,"Matched food");
assert.equal(selected[0].count,1);
assert.equal(loaded.length,0);
assert.equal(requests.length,1);
assert.equal(requests[0].url,"/api/food-lookup?q=0038000000001");
assert.equal(requests[0].options.body,undefined);
assert.equal(requests[0].options.method,undefined,"capture must never save a food automatically");
assert.equal(createdPhotos.length,0,"live scanning does not invoke the native photo picker");
assert.equal(cameraTimers.size,0);
""")

    def test_live_label_captures_first_complete_read(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();
get("scanLabelButton").click();
await until(()=>workerCreates===1);
assert.equal(recognitions,0,"the reader should prepare while the camera starts");
await cameraFrame();await until(()=>loaded.length===1);
assert.equal(recognitions,1,"reuse the first complete OCR result");
assert.deepEqual(recognitionInputs,[{width:2400,height:1800}],"read the captured full-resolution frame");
assert.equal(maxRecognitions,1);assert.equal(workerCreates,1);
assert.equal(cameraStreams[0].track.stopped,1);
assert.equal(get("foodCameraVideo").srcObject,null);assert.equal(get("foodLiveCamera").hidden,true);
assert.equal(loaded[0].serving_g,22);assert.equal(loaded[0].calories,120);
assert.equal(loaded[0].protein,6);assert.equal(loaded[0].carbs,18);assert.equal(loaded[0].fat,4);
assert.equal(loaded[0].fiber,null);assert.equal(loaded[0].source_url,"");assert.equal(loaded[0].name,"");
assert.equal(requests.length,0);assert.equal(get("foodScanText").hidden,false);
assert.equal(get("scanLabelButton").disabled,false);
""")

    def test_partial_read_waits_for_all_four_macros(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();
const preview="Nutrition Facts\nServing size unreadable\nCalories 120\nTotal Fat ? g\nTotal Carbohydrate unreadable\nProtein unreadable";
ocrResponses.push({data:{text:preview,confidence:52}});
get("scanLabelButton").click();await cameraFrame();
await until(()=>cameraTimers.size===1);
assert.equal(loaded.length,0);assert.equal(cameraStreams[0].track.stopped,0);
await cameraFrame();await until(()=>loaded.length===1);
assert.equal(recognitions,2);assert.equal(loaded[0].calories,120);
assert.equal(loaded[0].protein,6);assert.equal(loaded[0].serving_g,22);
assert.equal(cameraStreams[0].track.stopped,1);assert.equal(requests.length,0);
""")

    def test_good_read_stops_before_a_later_blurred_frame(self):
        self.run_scan(r"""
isSecureContext=true;
ocrResponses.push(labelData(completeLabel()),labelData("blurred package"));
get("scanLabelButton").click();await cameraFrame();await until(()=>loaded.length===1);
assert.equal(recognitions,1);assert.equal(ocrResponses.length,1);
assert.equal(loaded[0].calories,120);assert.equal(cameraStreams[0].track.stopped,1);
""")

    def test_complete_macros_capture_even_when_weight_and_fiber_are_unreadable(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel().replace("22 g","unreadable")+"\nDietary Fiber ?g";
get("scanLabelButton").click();await cameraFrame();await until(()=>loaded.length===1);
assert.equal(recognitions,1);assert.equal(loaded[0].serving_g,null);assert.equal(loaded[0].fiber,null);
assert.equal(loaded[0].calories,120);assert.equal(loaded[0].protein,6);
assert.equal(loaded[0].carbs,18);assert.equal(loaded[0].fat,4);
assert.equal(requests.length,0,"capture fills the editor; logging still uses Save");
""")

    def test_pending_live_label_cancel_stops_tracks_and_cannot_overwrite_new_text(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();ocrDeferred=deferred();
get("scanLabelButton").click();await cameraFrame();
assert.equal(recognitions,1);
fields.name.value="New manual draft";documentEvent("input",fields.name);
assert.equal(cameraStreams[0].track.stopped,1);
assert.equal(get("foodCameraVideo").srcObject,null);
assert.equal(get("foodLiveCamera").hidden,true);
assert.equal(workerTerminates,1);
ocrDeferred.resolve(labelData());await tick();
assert.equal(loaded.length,0);assert.equal(selected.length,0);
assert.equal(fields.name.value,"New manual draft");
assert.equal(get("scanLabelButton").disabled,false);
assert.equal(cameraTimers.size,0);
""")

    def test_live_manual_shutter_stops_camera_and_waits_for_pending_preview_ocr(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();ocrDeferred=deferred();
const pendingPreview=ocrDeferred;
get("scanLabelButton").click();await cameraFrame();
assert.equal(recognitions,1);assert.equal(activeRecognitions,1);
get("captureFoodNow").click();
assert.equal(cameraStreams[0].track.stopped,1,"manual capture must release the camera immediately");
assert.equal(get("foodCameraVideo").srcObject,null);
assert.equal(loaded.length,0);assert.equal(recognitions,1);
ocrDeferred=null;pendingPreview.resolve(labelData());
await until(()=>loaded.length===1);
assert.equal(maxRecognitions,1);assert.equal(recognitions,2);
assert.deepEqual(recognitionInputs,[{width:2400,height:1800},{width:2400,height:1800}]);
assert.equal(loaded[0].serving_g,22);assert.equal(get("foodLiveCamera").hidden,true);
assert.equal(get("scanLabelButton").disabled,false);
assert.equal(requests.length,0);
""")

    def test_cancel_during_worker_initialization_terminates_stale_worker_only(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();workerInitDeferred=deferred();
const staleInitialization=workerInitDeferred;
get("scanLabelButton").click();await cameraFrame();
await until(()=>workerCreates===1);
assert.equal(recognitions,0);
get("cancelFoodScan").click();assert.equal(cameraStreams[0].track.stopped,1);
workerInitDeferred=null;
get("scanLabelButton").click();await cameraFrame();
assert.equal(workerCreates,2);assert.equal(recognitions,1);
staleInitialization.resolve();await tick();
assert.equal(workers[0].terminations,1,"a late canceled initialization must release its own worker");
assert.equal(workers[0].recognitionCalls,0);
assert.equal(workers[1].terminations,0,"the current worker must remain available");
await until(()=>loaded.length===1);
assert.equal(workers[1].recognitionCalls,1);
assert.equal(loaded[0].serving_g,22);assert.equal(workerCreates,2);
assert.equal(cameraStreams[1].track.stopped,1);
assert.equal(workers[1].terminations,0);
""")

    def test_https_unavailable_main_buttons_and_explicit_photo_buttons_use_camera_picker(self):
        self.run_scan(r"""
assert.equal(isSecureContext,false);
get("scanBarcodeButton").click();get("scanLabelButton").click();
assert.equal(get("barcodePhoto").clicked,1);assert.equal(get("nutritionLabelPhoto").clicked,1);
assert.equal(cameraRequests.length,0);
assert.match(get("foodScanStatus").textContent,/HTTPS address.*photo capture/);
isSecureContext=true;
get("photoBarcodeButton").click();get("photoLabelButton").click();
assert.equal(get("barcodePhoto").clicked,2);assert.equal(get("nutritionLabelPhoto").clicked,2);
assert.equal(cameraRequests.length,0,"explicit photo buttons should always open the native picker");
assert.equal(get("cancelFoodScan").hidden,true);
""")

    def test_hidden_page_cancels_live_but_keeps_native_photo_processing(self):
        self.run_scan(r"""
isSecureContext=true;ocrText=completeLabel();ocrDeferred=deferred();
get("scanLabelButton").click();await cameraFrame();
document.hidden=true;documentEvent("visibilitychange",get("body"));
assert.equal(cameraStreams[0].track.stopped,1);
assert.equal(get("foodLiveCamera").hidden,true);
assert.equal(get("cancelFoodScan").hidden,true);
ocrDeferred.resolve(labelData());await tick();assert.equal(loaded.length,0);
document.hidden=false;ocrDeferred=deferred();
const nativePhoto=photo("nutritionLabelPhoto");await until(()=>recognitions===2);
document.hidden=true;documentEvent("visibilitychange",get("body"));
assert.equal(get("cancelFoodScan").hidden,false,"native camera backgrounding must not cancel its image scan");
ocrDeferred.resolve(labelData());await nativePhoto;
assert.equal(loaded.length,1);
""")
