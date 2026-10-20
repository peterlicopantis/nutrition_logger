"""Live labels open for review on the first useful OCR reading."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for live label checks")
class LiveLabelDetectorTests(unittest.TestCase):
    def run_detector(self, assertions):
        program = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
const root = process.argv[1];
const Detector = require(path.join(root, "static/live_label_detector.js"));
const detector = Detector.create();
const label = "Nutrition Facts\nServing size 1 cup (84 g)\nCalories 120\nTotal Fat 4g\nTotal Carbohydrate 2g\nProtein 18g";
function frame(text=label, confidence=90) { return {text,confidence}; }
""" + assertions
        result = subprocess.run([shutil.which("node"), "-e", program, str(ROOT)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_first_complete_read_captures_without_second_match(self):
        self.run_detector(r"""
const result=detector.observe(frame());
assert.equal(result.ready,true);
assert.equal(result.parsed.calories,120);
detector.reset();assert.equal(detector.observe(frame()).ready,true);
""")

    def test_each_main_macro_is_required_and_frames_are_not_combined(self):
        self.run_detector(r"""
for(const row of ["Calories 120","Total Fat 4g","Total Carbohydrate 2g","Protein 18g"]){
 const result=detector.observe(frame(label.replace(row,"")));
 assert.equal(result.ready,false);
 assert.ok(result.missing.length>0);
}
assert.equal(detector.observe(frame()).ready,true);
""")

    def test_unknown_weight_and_fiber_do_not_block_main_macros(self):
        self.run_detector(r"""
for(const text of [
 label.replace("84 g","219"),
 label.replace("Serving size 1 cup (84 g)",""),
 label+"\nDietary Fiber unreadable",
 label.replace("Serving size 1 cup (84 g)","Per 100 ml")
]){
 assert.equal(detector.observe(frame(text)).ready,true);
}
const result=detector.observe(frame(label.replace("84 g","219")));
assert.equal(result.parsed.serving_g,null);
""")

    def test_zero_values_count_as_readable(self):
        self.run_detector(r"""
const zero=label.replace("4g","0g").replace("2g","0g").replace("18g","0g").replace("Calories 120","Calories 0");
const result=detector.observe(frame(zero));
assert.equal(result.ready,true);
for(const key of ["calories","protein","carbs","fat"])assert.equal(result.parsed[key],0);
""")

    def test_ambiguous_columns_and_unrelated_text_do_not_capture(self):
        self.run_detector(r"""
for(const text of [
 "A package","Nutrition Facts","Calories 120 Protein 18g Fat 4g Carbohydrate 2g",
 label.replace("Calories 120","Per 100g Per serving\nCalories 120 240")
])assert.equal(detector.observe(frame(text)).ready,false);
""")

    def test_confidence_floor_rejects_garbage_without_requiring_perfect_text(self):
        self.run_detector(r"""
for(const confidence of [undefined,null,"90",NaN,Infinity,-1,0,44,101])
 assert.equal(detector.observe({text:label,confidence}).ready,false);
assert.equal(detector.observe(frame(label,45)).ready,true);
""")

    def test_browser_global_works_without_node_globals(self):
        self.run_detector(r"""
const context={};
vm.runInNewContext(fs.readFileSync(path.join(root,"static/nutrition_label.js"),"utf8"),context);
vm.runInNewContext(fs.readFileSync(path.join(root,"static/live_label_detector.js"),"utf8"),context);
const browser=context.LiveLabelDetector.create();
assert.equal(browser.observe(frame()).ready,true);
""")

if __name__ == "__main__":
    unittest.main()
