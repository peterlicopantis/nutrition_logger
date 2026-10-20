/* Parse OCR text conservatively. Every populated value still needs label review. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NutritionLabel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const nutrientNames = {calories:"calories", protein:"protein", carbs:"carbohydrates", fat:"fat", fiber:"fiber"};
  const numberPattern = "(?:\\d+(?:[.,]\\d+)?|[.,]\\d+)";
  function number(value) {
    if (/^\d+,\d{3}$/.test(value)) return null; // A decimal comma and a thousands separator are ambiguous.
    const result = Number(value.replace(",", "."));
    return Number.isFinite(result) && result >= 0 ? result : null;
  }

  // OCR blocks follow reading order, which can put a large right-aligned
  // calorie value in a separate block. Reconstruct physical rows from words.
  function readingText(reading) {
    if (typeof reading === "string") return reading;
    const words = reading?.words || (reading?.blocks || []).flatMap(block =>
      (block.paragraphs || []).flatMap(paragraph =>
        (paragraph.lines || []).flatMap(line => line.words || [])));
    const valid = words.filter(word => word.text && word.bbox &&
      ["x0","x1","y0","y1"].every(key => Number.isFinite(word.bbox[key])) &&
      word.bbox.x1 > word.bbox.x0 && word.bbox.y1 > word.bbox.y0);
    if (valid.length < 4) return reading?.text || "";
    const rows = [];
    for (const word of [...valid].sort((a,b) => a.bbox.y0-b.bbox.y0)) {
      const b = word.bbox, height = b.y1-b.y0;
      const row = rows.find(row =>
        Math.min(row.y1,b.y1)-Math.max(row.y0,b.y0) >= .45*Math.min(row.y1-row.y0,height) &&
        Math.abs(row.y1-b.y1) <= .65*Math.max(row.y1-row.y0,height));
      if (row) {
        row.words.push(word);
        row.y0=Math.min(row.y0,b.y0); row.y1=Math.max(row.y1,b.y1);
      } else rows.push({y0:b.y0,y1:b.y1,words:[word]});
    }
    return rows.sort((a,b)=>a.y0-b.y0).map(row =>
      row.words.sort((a,b)=>a.bbox.x0-b.bbox.x0).map(word=>word.text).join(" ")).join("\n");
  }

  function tidy(text) {
    return String(text || "").normalize("NFKC").replace(/\r\n?/g, "\n")
      .replace(/[\u2010-\u2015]/g, "-").replace(/[\u00a0\t]/g, " ")
      .replace(/\btota[il1]\b/gi, "total")
      .replace(/\bcalor[il1]es\b/gi, "calories")
      .replace(/\bpr[o0]te[il1]n\b/gi, "protein")
      .replace(/\bd[il1]etary\b/gi, "dietary")
      .replace(/\bf[il1]b(?:er|re)\b/gi, "fiber")
      .replace(/\bserv[il1]ng\s*s[il1]ze\b/gi, "serving size")
      .replace(/\bcarbo[\s\n-]*hydrates?\b/gi, "carbohydrate")

      .replace(/\b(fat|protein|carbohydrates?|fib(?:er|re))(?=\d|Og\b)/gi, "$1 ")
      // An attached unit distinguishes the common printed-zero OCR error.
      .replace(/\b((?:total\s+)?fat|protein|(?:total\s+)?carbohydrates?|(?:dietary\s+)?fib(?:er|re))\s+Og\b/gi, "$1 0g")
      .replace(/[ ]{2,}/g, " ").trim();
  }
  function parse(text) {
    const result = {serving_g:null, serving_label:null, calories:null, protein:null, carbs:null, fat:null, fiber:null, warnings:[]};
    const warn = value => {if (!result.warnings.includes(value)) result.warnings.push(value);};
    let source = tidy(readingText(text));
    // Ingredient lists and manufacturer prose are not nutrition table rows.
    const factsStart = source.search(/\bnutrition\s+(?:facts|information)\b/i);
    if (factsStart >= 0) source = source.slice(factsStart);
    source = source.split(/\n\s*(?:ingredients?\b|allergen\s+information\b|contains\s*:)/i)[0];
    source = source.split(/\n\s*\*?\s*(?:the\s+%\s*daily\s+value|percent\s+daily\s+values|one\s+serving\s+adds)\b/i)[0];
    const serving = /\bserving\s*size\b\s*:?\s*([^\n]+)/i.exec(source);
    if (serving) {
      const description = serving[1].split(/\b(?:amount\s+per|calories|energy|total\s+fat|protein|%\s*daily)\b/i)[0].trim();
      result.serving_label = description.slice(0, 120) || null;
      const grams = [...description.matchAll(new RegExp("(" + numberPattern + ")\\s*(?:g|grams?)\\b", "gi"))];
      if (grams.length === 1) {
        const prefix = description.slice(0, grams[0].index);
        const weight = number(grams[0][1]);
        if (!/(?:[\d.,]\s*[-/]|[-\u2212])\s*$/.test(prefix) && weight > 0 && weight <= 1000000) result.serving_g = weight;
      }
      const spoon = /(?:^|\s)(\d+(?:\.\d+)?)\s*(tbsp\.?|tablespoons?|tsp\.?|teaspoons?)\b/i.exec(description);
      if (spoon && result.serving_g !== null &&
          result.serving_g > Number(spoon[1]) * (/^(?:tbsp|tablespoon)/i.test(spoon[2]) ? 100 : 50)) {
        result.serving_g = null;
        result.serving_label = description.replace(/\([^)]*\)/g, "").trim() || null;
        warn("The serving weight looks inconsistent with the spoon size; check the printed grams.");
      }
      if (grams.length > 1) warn("The serving weight is ambiguous; enter grams per serving yourself.");
    }

    const headerSource = source.replace(/\b(?:\d+(?:[.,]\d+)?\s+serving|servings)\s+per\s+(?:container|pack(?:age)?)\b/gi, "");
    const per100g = /\bper\s*100\s*(?:g|grams?)\b/i.test(headerSource);
    const per100ml = /\bper\s*100\s*(?:ml|millilit(?:er|re)s?)\b/i.test(headerSource);
    const perPortion = /\bper\s+(?:serving|portion|container|pack(?:age)?)\b/i.test(headerSource);
    const hasServingAndContainer = /\bper\s+(?:serving|portion)\b/i.test(headerSource) && /\bper\s+(?:container|pack(?:age)?)\b/i.test(headerSource);
    const columnHeader = /\b(?:per\s+)?100\s*g\b\s*[|/,:;-]?\s*(?:per\s+)?(?:portion|serving)\b|\b(?:per\s+)?(?:portion|serving)\b\s*[|/,:;-]?\s*(?:per\s+)?100\s*g\b/i.test(headerSource);
    const ambiguousColumns = (per100g && perPortion) || (per100g && per100ml) || hasServingAndContainer || columnHeader;
    if (ambiguousColumns) {
      warn("This label appears to have multiple nutrition columns. Enter the macros from one column yourself.");
      return result;
    }
    if (per100g) {
      result.serving_g = 100;
      result.serving_label = "100 g (nutrition label basis)";
      warn("Nutrition was read per 100 g. Set the grams eaten after checking the label.");
    } else if (per100ml) {
      result.serving_g = null;
      result.serving_label = "100 ml (nutrition label basis)";
      warn("The label is per 100 ml; a liquid volume cannot be treated as grams.");
    }

    // Also recognize ignored rows so their numbers cannot leak into a macro row.
    const labels = /\b(calories\s+from\s+fat|calories|energy|total\s+fat|saturated\s+fat|saturates|trans\s+fat|polyunsaturated\s+fat|monounsaturated\s+fat|fat|total\s+carbohydrates?|carbohydrates?|dietary\s+fib(?:er|re)|fib(?:er|re)|protein|sodium|salt|cholesterol|total\s+sugars?|added\s+sugars?|sugars?|includes|vitamin\s+[a-z0-9]+|calcium|iron|potassium)\b/gi;
    const rows = [...source.matchAll(labels)];
    const candidates = Object.fromEntries(Object.keys(nutrientNames).map(key => [key, []]));
    for (let index = 0; index < rows.length; index++) {
      const label = rows[index][1].toLowerCase().replace(/\s+/g, " ");
      let key = null;
      if (label === "calories" || label === "energy") key = "calories";
      else if (label === "total fat" || label === "fat") key = "fat";
      else if (/^(?:total )?carbohydrates?$/.test(label)) key = "carbs";
      else if (/^(?:dietary )?fib(?:er|re)$/.test(label)) key = "fiber";
      else if (label === "protein") key = "protein";
      if (!key) continue;
      const end = index + 1 < rows.length ? rows[index + 1].index : source.length;
      let valueText = source.slice(rows[index].index + rows[index][0].length, end).trim().replace(/^[:|]\s*/, "");
      // A percentage, a less-than value, or prose cannot establish a precise macro.
      if (!new RegExp("^" + numberPattern).test(valueText)) continue;
      let value = null;
      let uncertain = false;
      if (key === "calories") {
        const kcal = [...valueText.matchAll(new RegExp("(" + numberPattern + ")\\s*kcal\\b", "gi"))];
        if (kcal.length === 1) {
          value = number(kcal[0][1]);
          const remaining = valueText.replace(new RegExp(numberPattern + "\\s*(?:kcal\\b|kj\\b|%)", "gi"), "");
          uncertain = new RegExp(numberPattern).test(remaining);
        }
        else if (kcal.length > 1) uncertain = true;
        else if (label === "calories" && !/k[jl]\b/i.test(valueText)) {
          const first = new RegExp("^(" + numberPattern + ")(?![\\d.,])[ \\t]*(?:cal(?:ories)?\\b)?", "i").exec(valueText);
          if (first && !/^[ \t]*%/.test(valueText.slice(first[0].length))) {
            value = number(first[1]);
            const remainder = valueText.slice(first[0].length).split(/\n\s*[^\d]/)[0];
            const other = [...remainder.matchAll(new RegExp("(" + numberPattern + ")\\s*(%)?", "g"))].filter(match => !match[2]);
            uncertain = other.length > 0;
          }
        }
      } else {
        const grams = [...valueText.matchAll(new RegExp("(" + numberPattern + ")\\s*(g|grams?)\\b", "gi"))];
        const milligrams = new RegExp("^" + numberPattern + "\\s*mg\\b", "i").test(valueText);
        if (grams.length === 1 && grams[0].index === 0 && !milligrams) value = number(grams[0][1]);
        else if (grams.length > 1) uncertain = true;
      }
      if (uncertain) {
        candidates[key].push(null);
        warn("More than one " + nutrientNames[key] + " value was found. Enter that value yourself.");
      } else if (value !== null) {
        const max = key === "calories" ? 100000 : 10000;
        const massConflict = key !== "calories" && result.serving_g !== null && value > result.serving_g * 1.05 + 1;
        if (value <= max && !massConflict) candidates[key].push(value);
        else {
          candidates[key].push(null);
          warn("The " + nutrientNames[key] + " value looks inconsistent; check it against the label.");
        }
      }
    }
    for (const key of Object.keys(nutrientNames)) {
      const values = candidates[key];
      if (values.length && !values.includes(null) && values.every(value => value === values[0])) result[key] = values[0];
      else if (values.length > 1) warn("Conflicting " + nutrientNames[key] + " values were found. Enter that value yourself.");
    }
    const missing = Object.keys(nutrientNames).filter(key => result[key] === null).map(key => nutrientNames[key]);
    if (missing.length) warn("Could not confidently read: " + missing.join(", ") + ".");
    if (result.serving_g === null && !per100ml) warn("No reliable serving weight in grams was found. Enter it if you know it.");
    return result;
  }
  return Object.freeze({parse, readingText});
});
