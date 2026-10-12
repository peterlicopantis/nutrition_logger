"""Exercise the dashboard's real save handlers with mobile event sequences."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to check browser event handlers")
class DashboardAutosaveTests(unittest.TestCase):
    def test_mobile_input_release_suspend_and_retry_sequences(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "dashboard.js").read_text(encoding="utf-8")
        handlers = source[source.index("const amountControls = new Map();"):
                          source.index('document.querySelectorAll(".amount-control").forEach')]
        harness = r"""
const assert = require("node:assert/strict");
const DAY = "2026-10-07";
let DAY_LOCKED = false, dayLockChanging = false;
const document = new EventTarget();
const window = new EventTarget();
window.location = {reload() { throw new Error("Unexpected reload"); }};
function n(value) { return Number(value) || 0; }
function rounded(value, places) { return Number(value.toFixed(places)); }
function renderTotals() {}
function renderFoodPreview() {}
class Field extends EventTarget {
  constructor(value, isFood=false) {
    super();
    this.value = String(value);
    this.dataset = {};
    this.disabled = false;
    this.readOnly = false;
    this.classList = {contains: name => isFood && name === "food-input", toggle() {}};
    this.style = {setProperty() {}};
  }
  setAttribute() {}
  setCustomValidity(value) { this.validation = value; }
  reportValidity() {}
  blur() { this.dispatchEvent(new Event("blur")); }
}
const statusEl = new Field("");
const stored = new Map(), requests = [];
let failNext = false, networkDelay = 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function fetch(url, options) {
  assert.equal(url, "/api/entry");
  assert.equal(options.keepalive, true);
  const payload = JSON.parse(options.body);
  requests.push(payload);
  await delay(networkDelay);
  if (failNext) { failNext = false; return {ok:false, status:500}; }
  stored.set(payload.food_name, payload.amount);
  return {ok:true, status:200};
}
function control(name="Food", isFood=true) {
  const exact = new Field(0, isFood), slider = new Field(0);
  slider.max = "1000";
  exact.dataset.name = name;
  const wrapper = {
    dataset:{unit:"g", max:"1000", step:"10"},
    querySelector(selector) {
      return {".amount-value":exact, ".amount-range":slider, ".range-limit":{}}[selector];
    }
  };
  attachAmountSlider(wrapper);
  return {exact, slider};
}
function edit(field, value) {
  field.value = String(value);
  field.dispatchEvent(new Event("input"));
}
"""
        cases = r"""
(async () => {
  // No change or blur event: iPhone keyboard edits must still reach the server.
  const typed = control("Typed");
  edit(typed.exact, "12.");
  await delay(320);
  assert.equal(stored.get("Typed"), 12);
  assert.equal(typed.exact.value, "12.", "autosave must preserve an unfinished decimal");
  edit(typed.exact, "12.5");
  await delay(320);
  assert.equal(stored.get("Typed"), 12.5);
  const beforeBlur = requests.length;
  typed.exact.blur();
  await delay(20);
  assert.equal(requests.length, beforeBlur, "blur must not duplicate a successful autosave");

  // Safari-style input-only range movement, including several rapid changes.
  const slider = control("Slider");
  edit(slider.slider, 101);
  edit(slider.slider, 119);
  edit(slider.slider, 137);
  await delay(320);
  assert.equal(stored.get("Slider"), 140);
  assert.equal(requests.filter(r => r.food_name === "Slider").length, 1);

  // Touch release saves immediately; duplicate release events remain one request.
  const release = control("Release");
  edit(release.slider, 250);
  for (const event of ["touchend", "pointerup", "change", "blur"]) {
    release.slider.dispatchEvent(new Event(event));
  }
  await delay(20);
  assert.equal(stored.get("Release"), 250);
  await delay(300);
  assert.equal(requests.filter(r => r.food_name === "Release").length, 1);

  // Tab suspension must flush a draft before the debounce expires.
  const hidden = control("Hidden");
  edit(hidden.exact, "33.5");
  document.visibilityState = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  await delay(20);
  assert.equal(stored.get("Hidden"), 33.5);

  // Locking flushes drafts before disabling editing or waiting for queued saves.
  const lock = control("Before lock");
  edit(lock.slider, 290);
  flushAmountSaves();
  dayLockChanging = true;
  await saveChains.get(lock.exact);
  assert.equal(stored.get("Before lock"), 290);
  dayLockChanging = false;

  // Slow requests for one food are serialized so the final release wins.
  const racing = control("Rapid");
  networkDelay = 80;
  edit(racing.slider, 100);
  racing.slider.dispatchEvent(new Event("touchend"));
  edit(racing.slider, 200);
  racing.slider.dispatchEvent(new Event("touchend"));
  await saveChains.get(racing.exact);
  assert.equal(stored.get("Rapid"), 200);
  assert.deepEqual(requests.filter(r => r.food_name === "Rapid").map(r => r.amount), [100, 200]);
  networkDelay = 0;

  // Same-value retry must still work after a failed save.
  const retry = control("Retry");
  failNext = true;
  edit(retry.slider, 60);
  retry.slider.dispatchEvent(new Event("touchend"));
  await saveChains.get(retry.exact);
  assert.equal(saveErrors.has(retry.exact), true);
  retry.exact.blur();
  await saveChains.get(retry.exact);
  assert.equal(stored.get("Retry"), 60);
  assert.equal(saveErrors.has(retry.exact), false);

  // Invalid input cancels a pending valid draft; locked rows never save.
  const invalid = control("Invalid");
  edit(invalid.exact, 30);
  edit(invalid.exact, "-");
  await delay(320);
  assert.equal(stored.has("Invalid"), false);
  const locked = control("Locked");
  DAY_LOCKED = true;
  locked.slider.disabled = locked.exact.disabled = true;
  edit(locked.slider, 300);
  locked.slider.dispatchEvent(new Event("touchend"));
  await delay(320);
  assert.equal(stored.has("Locked"), false);
  DAY_LOCKED = false;

  // The temporary serving editor must not create a saved-library entry.
  const temporary = control("Temporary", false);
  edit(temporary.slider, 20);
  await delay(320);
  assert.equal(stored.has("Temporary"), false);
  assert.equal(pendingSaves, 0);
  console.log("Mobile autosave event sequences passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([shutil.which("node")], input=harness + handlers + cases,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
