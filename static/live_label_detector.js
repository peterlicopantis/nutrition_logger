/* Auto-capture the first panel with all four main nutrition values. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./nutrition_label.js"));
  } else root.LiveLabelDetector = factory(root.NutritionLabel);
})(typeof globalThis !== "undefined" ? globalThis : this, function (NutritionLabel) {
  "use strict";
  const minimumConfidence = 45;
  const labelKey = "nutrition-panel";
  function inspect(data) {
    const missing = {detected:false, key:null, parsed:null};
    if (!data || typeof data.text !== "string" || !Number.isFinite(data.confidence) ||
        data.confidence < minimumConfidence || data.confidence > 100) return missing;
    const text = NutritionLabel.readingText(data).normalize("NFKC")
      .replace(/\btota[il1]\b/gi, "total")
      .replace(/\bcalor[il1]es\b/gi, "calories")
      .replace(/\bpr[o0]te[il1]n\b/gi, "protein")
      .replace(/\bf[il1]b(?:er|re)\b/gi, "fiber");
    const heading = /\bnutrition\s*(?:facts|information)\b/i.test(text);
    const calories = /\b(?:calories|energy)\b/i.test(text);
    const fat = /\b(?:total\s+)?fat\b/i.test(text);
    const carbs = /\b(?:total\s+)?carbo[\s-]*hydrates?\b/i.test(text);
    const protein = /\bprotein\b/i.test(text);
    const fiber = /\b(?:dietary\s+)?fib(?:er|re)\b/i.test(text);
    const sodium = /\bsodium\b/i.test(text);
    const serving = /\bserv[il1]ng\s*s[il1]ze\b|\bper\s*100\s*(?:g|ml)\b/i.test(text);
    const rows = [fat, carbs, protein, fiber, sodium].filter(Boolean).length;
    // A heading plus several nutrition rows establishes a label even when tiny
    // digits/units cannot be read yet. A cropped heading needs stronger evidence.
    const panel = calories && ((heading && rows >= 2) ||
      (serving && fat && carbs && protein && (fiber || sodium)));
    if (!panel) return missing;
    return {detected:true, key:labelKey, parsed:NutritionLabel.parse(data)};
  }
  function create() {
    function reset() {}
    function observe(data) {
      const detection = inspect(data);
      const keys = ["calories", "protein", "carbs", "fat"];
      const missing = detection.parsed ?
        keys.filter(key => !Number.isFinite(detection.parsed[key])) : keys;
      return {...detection, ready:detection.detected && missing.length === 0, missing};
    }
    function matches(data, key) {
      // The final image is authoritative. Preview number/fiber/weight changes
      // must not reject a sharper image that still clearly shows a label.
      return key === labelKey && inspect(data).detected;
    }
    return Object.freeze({observe, reset, matches});
  }
  return Object.freeze({create});
});
