const dashboardConfig = JSON.parse(document.getElementById("dashboardConfig").dataset.config);
const DAY = dashboardConfig.day;
const DAY_LOCKED = Boolean(dashboardConfig.dayLocked);
let dayLockChanging = false;
const SALT_CATEGORY = dashboardConfig.saltCategory || "Dawg Bowl";
const desktopLayout = window.matchMedia("(min-width:1024px)");
const phoneLayout = window.matchMedia("(max-width:600px), (max-width:900px) and (pointer:coarse)");
const compactPanels = [document.getElementById("dayFoodPanel"), document.getElementById("healthPanel")].filter(Boolean);
function setPanelLayout() {
  compactPanels.forEach(panel => {
    if (!panel.contains(document.activeElement)) panel.open = !(desktopLayout.matches || phoneLayout.matches);
  });
}
const foodSections = [...document.querySelectorAll("#foodSections > .section")];
const groupButtons = [...document.querySelectorAll(".mobile-group-tab")];
function setCategoryColumns() {
  document.getElementById("foodSections").style.gridTemplateColumns = desktopLayout.matches ?
    "repeat("+Math.min(5, Math.max(1, foodSections.length))+", minmax(0, 1fr))" : "";
}
setCategoryColumns();
desktopLayout.addEventListener("change", setCategoryColumns);

const mobileSummary = document.getElementById("mobileSummary");
let selectedCategory = foodSections[0]?.dataset.category;
function syncMobileCategories(preserveFocus=false) {
  const focused = document.activeElement?.closest(".section");
  if (preserveFocus && phoneLayout.matches && foodSections.includes(focused)) selectedCategory = focused.dataset.category;
  foodSections.forEach(section => section.classList.toggle("mobile-category-inactive", section.dataset.category !== selectedCategory));
  groupButtons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.category === selectedCategory)));
}
function measureMobileSummary() {
  document.body.style.setProperty("--mobile-summary-height", Math.ceil(mobileSummary.getBoundingClientRect().height)+"px");
}
function updatePhoneTyping() {
  document.body.classList.toggle("mobile-typing", phoneLayout.matches &&
    Boolean(document.activeElement?.matches("input:not([type=range]), textarea")));
}
groupButtons.forEach(button => button.addEventListener("click", () => {
  if (phoneLayout.matches && document.activeElement?.matches("input, textarea")) document.activeElement.blur();
  selectedCategory = button.dataset.category;
  syncMobileCategories();
  if (phoneLayout.matches) document.getElementById("foodSections").scrollIntoView({block:"start"});
}));
setPanelLayout();
syncMobileCategories();
measureMobileSummary();
desktopLayout.addEventListener("change", setPanelLayout);
phoneLayout.addEventListener("change", () => {
  setPanelLayout();
  syncMobileCategories(true);
  updatePhoneTyping();
  requestAnimationFrame(measureMobileSummary);
});
if (typeof ResizeObserver === "function") new ResizeObserver(measureMobileSummary).observe(mobileSummary);
document.addEventListener("focusin", () => {
  const focused = document.activeElement?.closest(".section");
  if (foodSections.includes(focused)) {
    selectedCategory = focused.dataset.category;
    syncMobileCategories();
  }
  updatePhoneTyping();
});
document.addEventListener("focusout", () => setTimeout(updatePhoneTyping, 0));
const SHORTCUT = dashboardConfig.shortcutName;
const HEALTH_BURN = dashboardConfig.healthBurn;
const inputs = [...document.querySelectorAll(".food-input")];
const statusEl = document.getElementById("saveStatus");
let dayFoods = dashboardConfig.dayFoods;
let dayFoodTotals = dashboardConfig.dayFoodTotals;
const nutrientKeys = ["calories", "protein", "carbs", "fat", "fiber"];

function n(v) {
  const x = parseFloat(v);
  return Number.isFinite(x) ? x : 0;
}
function rounded(x, d=2) {
  const p = Math.pow(10,d);
  return Math.round((x + Number.EPSILON) * p) / p;
}
function computeDayFoodTotals() {
  const t = {calories:0, protein:0, carbs:0, fat:0, fiber:0, calc_calories:0};
  for (const food of dayFoods) {
    const servings = n(food.servings);
    nutrientKeys.forEach(key => t[key] += servings * n(food[key]));
    t.calc_calories += servings * (4*n(food.protein) + 4*n(food.carbs) + 9*n(food.fat));
  }
  return t;
}
function computeTotals() {
  const t = {calories:0, protein:0, carbs:0, fat:0, fiber:0, calc_calories:0};
  Object.keys(t).forEach(key => t[key] = n(dayFoodTotals[key]));
  for (const el of inputs) {
    const a = n(el.dataset.amount);
    const p = n(el.dataset.protein), c = n(el.dataset.carbs), f = n(el.dataset.fat);
    t.calories += a*n(el.dataset.cal);
    t.protein += a*p;
    t.carbs += a*c;
    t.fat += a*f;
    t.fiber += a*n(el.dataset.fiber);
    t.calc_calories += a*(p*4+c*4+f*9);
  }
  Object.keys(t).forEach(k => t[k] = rounded(t[k]));
  return t;
}
function isRiceForSpins(name) {
  const key = String(name || "").trim().toLowerCase();
  return ["enriched rice", "rice", "white rice", "brown rice", "cooked rice",
    "cooked white rice", "cooked brown rice"].includes(key) || key.startsWith("rice,");
}
function computeSaltSpins() {
  let grams = 0, riceBonus = 0;
  for (const input of inputs) {
    if (input.closest(".section")?.dataset.category === SALT_CATEGORY &&
        input.closest(".foodrow")?.dataset.unit === "g") {
      const mass = n(input.dataset.amount);
      grams += mass;
      riceBonus += mass * n(input.dataset.saltExtra);
    }
  }
  for (const food of dayFoods) {
    if (food.include_in_spins && Number(food.serving_g) > 0) {
      const mass = Number(food.serving_g) * n(food.servings);
      grams += mass;
      const factor = food.salt_extra_weight_factor ??
        (isRiceForSpins(food.name) ? 1.5 : 0);
      riceBonus += mass * n(factor);
    }
  }
  grams += riceBonus;
  return {grams, spins:grams / 29, riceBonus};
}
function renderSaltSpins() {
  const result = computeSaltSpins();
  document.getElementById("saltSpins").textContent = rounded(result.spins, 1);
  document.getElementById("saltMealGrams").textContent = rounded(result.grams, 1);
  document.getElementById("saltRiceBonus").textContent = rounded(result.riceBonus, 1);
}

function renderTotals() {
  renderSaltSpins();
  const t = computeTotals();
  document.getElementById("mCalories").textContent = Math.round(t.calories);
  document.getElementById("mProtein").textContent = t.protein.toFixed(1)+"g";
  document.getElementById("mCarbs").textContent = t.carbs.toFixed(1)+"g";
  document.getElementById("mFat").textContent = t.fat.toFixed(1)+"g";
  document.getElementById("mFiber").textContent = t.fiber.toFixed(1)+"g";
  document.getElementById("mCalc").textContent = Math.round(t.calc_calories);
  const energyBalance = document.getElementById("healthEnergyBalance");
  if (energyBalance && HEALTH_BURN !== null) energyBalance.textContent = rounded(t.calories - HEALTH_BURN);
  document.getElementById("fiberNotice").hidden = !dayFoods.some(food => food.fiber == null);
}
const amountControls = new Map();
function parseAmount(value, allowEmpty=false) {
  const text = String(value).trim().replace(",", ".");
  if (!text) return allowEmpty ? 0 : null;
  const amount = Number(text);
  return Number.isFinite(amount) && amount >= 0 ? amount : null;
}
function attachAmountSlider(control) {
  const exact = control.querySelector(".amount-value");
  const slider = control.querySelector(".amount-range");
  const limit = control.querySelector(".range-limit");
  const unit = control.dataset.unit;
  const baseMax = Number(control.dataset.max);
  const increment = Number(control.dataset.step);
  let committed = parseAmount(exact.value, true) ?? 0;
  exact.dataset.amount = String(committed);
  function sync(acceptValue=false) {
    const value = parseAmount(exact.value, true);
    if (value !== null) exact.dataset.amount = String(value);
    const amount = n(exact.dataset.amount);
    if (acceptValue) {
      committed = amount;
      exact.setCustomValidity("");
    }
    slider.max = String(Math.max(Number(slider.max), Math.ceil(amount / baseMax) * baseMax));
    slider.value = String(amount);
    slider.setAttribute("aria-valuetext", amount+" "+unit);
    slider.style.setProperty("--fill", (100 * amount / Number(slider.max))+"%");
    limit.textContent = slider.max+" "+unit;
  }
  function notify() {
    if (exact.classList.contains("food-input")) renderTotals();
    else renderFoodPreview();
  }
  function commit() {
    if (exact.readOnly || slider.disabled) return;
    const amount = parseAmount(exact.value, true);
    if (amount === null) {
      exact.setCustomValidity("Enter a number that is zero or greater.");
      exact.reportValidity();
      return;
    }
    exact.setCustomValidity("");
    exact.value = String(amount);
    committed = amount;
    sync();
    notify();
    if (exact.classList.contains("food-input")) saveInput(exact);
  }
  exact.addEventListener("input", () => {
    exact.setCustomValidity("");
    if (parseAmount(exact.value) !== null) {
      sync();
      notify();
    }
  });
  exact.addEventListener("change", commit);
  exact.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      exact.blur();
    } else if (event.key === "Escape") {
      exact.value = String(committed);
      exact.setCustomValidity("");
      sync();
      notify();
      exact.blur();
    }
  });
  slider.addEventListener("input", () => {
    if (exact.readOnly || slider.disabled) return;
    const value = rounded(Math.round(Number(slider.value) / increment) * increment, 3);
    exact.value = String(value);
    exact.setCustomValidity("");
    sync();
    notify();
  });
  slider.addEventListener("change", commit);
  slider.addEventListener("keydown", event => {
    const direction = {ArrowLeft:-1, ArrowDown:-1, ArrowRight:1, ArrowUp:1}[event.key];
    if (!direction || slider.disabled) return;
    event.preventDefault();
    slider.value = String(Math.max(0, Math.min(Number(slider.max),
      n(exact.dataset.amount) + direction * increment * (event.shiftKey ? 10 : 1))));
    slider.dispatchEvent(new Event("input", {bubbles:true}));
    slider.dispatchEvent(new Event("change", {bubbles:true}));
  });
  sync();
  amountControls.set(exact, {sync, slider});
}
const saveChains = new WeakMap();
const saveErrors = new Set();
let pendingSaves = 0;
function showSaveStatus() {
  statusEl.classList.toggle("save-error", saveErrors.size > 0);
  statusEl.textContent = pendingSaves ? "Saving..." :
    saveErrors.size ? "Save failed - change the entry to retry" : "Saved";
}
function saveInput(el) {
  if (DAY_LOCKED || dayLockChanging) return Promise.resolve();
  const amount = n(el.dataset.amount);
  pendingSaves++;
  showSaveStatus();
  // Serialize releases for the same food so an older request cannot win.
  const previous = saveChains.get(el) || Promise.resolve();
  const job = previous.catch(() => {}).then(async () => {
    try {
      const res = await fetch("/api/entry", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({day:DAY, food_name:el.dataset.name, amount})
      });
      if (res.status === 423) window.location.reload();
      if (!res.ok) throw new Error("Save failed");
      saveErrors.delete(el);
    } catch (error) {
      saveErrors.add(el);
    } finally {
      pendingSaves--;
      showSaveStatus();
    }
  });
  saveChains.set(el, job);
  return job;
}
document.querySelectorAll(".amount-control").forEach(attachAmountSlider);
document.querySelectorAll(".food-checkbox").forEach(checkbox => {
  checkbox.addEventListener("change", () => {
    if (DAY_LOCKED || dayLockChanging) return;
    checkbox.dataset.amount = checkbox.checked ? checkbox.dataset.checkboxAmount : "0";
    renderTotals();
    saveInput(checkbox);
  });
});


function adjacentDay(isoDay, offset) {
  // UTC calendar arithmetic avoids daylight-saving changes shifting the date.
  const timestamp = Date.parse(isoDay + "T00:00:00Z");
  if (!Number.isFinite(timestamp)) return null;
  const next = new Date(timestamp + offset * 86400000).toISOString().slice(0, 10);
  return /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(next) &&
    next >= "0001-01-01" && next <= "9999-12-31" ? next : null;
}
function navigateDay(offset) {
  const next = adjacentDay(document.getElementById("dayPicker").value || DAY, offset);
  if (next) window.location.href = "/?day=" + encodeURIComponent(next);
}
document.getElementById("previousDay").addEventListener("click", () => navigateDay(-1));
document.getElementById("nextDay").addEventListener("click", () => navigateDay(1));

document.getElementById("dayPicker").addEventListener("change", (e) => {
  if (e.target.value) window.location.href = "/?day="+encodeURIComponent(e.target.value);
});
document.getElementById("healthButton").addEventListener("click", () => {
  const t = computeTotals();
  const payload = {
    source:"MELB Nutrition",
    date:DAY,
    calories:t.calories,
    protein:t.protein,
    carbs:t.carbs,
    fat:t.fat,
    fiber:t.fiber
  };
  const url = "shortcuts://run-shortcut?name=" + encodeURIComponent(SHORTCUT)
            + "&input=text&text=" + encodeURIComponent(JSON.stringify(payload));
  window.location.href = url;
});

const lookupForm = document.getElementById("lookupForm");
const foodQuery = document.getElementById("foodQuery");
const lookupButton = document.getElementById("lookupButton");
const lookupStatus = document.getElementById("lookupStatus");
const lookupResults = document.getElementById("lookupResults");
const dayFoodForm = document.getElementById("dayFoodForm");
const dayFoodStatus = document.getElementById("dayFoodStatus");
const saveDayFood = document.getElementById("saveDayFood");
const fields = {
  name:document.getElementById("dfName"),
  serving_label:document.getElementById("dfServingLabel"),
  servings:document.getElementById("dfServings"),
  calories:document.getElementById("dfCalories"),
  protein:document.getElementById("dfProtein"),
  carbs:document.getElementById("dfCarbs"),
  fat:document.getElementById("dfFat"),
  fiber:document.getElementById("dfFiber")
};
const portionSelect = document.getElementById("dfPortion");
const gramInput = document.getElementById("dfGrams");
let portionState = null;
let selectedSource = null;
let savingFood = false;
let lookupGeneration = 0;
let lookupController = null;
let lookupPendingQuery = "";
let lookupInputValue = foodQuery.value;
const LOOKUP_TIMEOUT_MS = 25000;
const removingFoods = new Set();
const updatingSaltFoods = new Set();

function trustedSource(value) {
  if (typeof value !== "string" || value !== value.trim()) return null;
  const allowed = /^https:\/\/(?:world\.openfoodfacts\.org\/product\/[0-9]{8,14}|fdc\.nal\.usda\.gov\/food-details\/[0-9]+\/nutrients)$/;
  return allowed.test(value) ? value : null;
}
function addSourceLink(container, source) {
  const href = trustedSource(source);
  if (!href) return;
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = href.startsWith("https://fdc.nal.usda.gov/") ? "View USDA source" : "View on Open Food Facts";
  container.appendChild(link);
}
function setFoodStatus(message, isError=false) {
  dayFoodStatus.textContent = message;
  dayFoodStatus.hidden = !message;
  dayFoodStatus.classList.toggle("food-error", isError);
}
function resetEditor() {
  portionState = null;
  nutrientKeys.forEach(key => fields[key].readOnly = savingFood);
  gramInput.required = false;
  gramInput.setCustomValidity("");
  portionSelect.replaceChildren();
  document.getElementById("gramLabel").textContent = "Grams per serving";
  document.getElementById("portionControls").hidden = true;
  document.getElementById("portionSummary").textContent = "";
  document.getElementById("portionNote").textContent =
    "Enter the values for one serving, then how many servings you ate.";
  dayFoodForm.reset();
  amountControls.get(fields.servings).sync(true);
  selectedSource = null;
  document.getElementById("basisWarning").hidden = true;
  document.getElementById("foodSource").replaceChildren();
  document.getElementById("foodSource").hidden = true;
  renderFoodPreview();
}
function chooseMode(manual) {
  if (savingFood || DAY_LOCKED || dayLockChanging) return;
  invalidateLookup();
  document.getElementById("lookupArea").hidden = manual;
  document.getElementById("lookupMode").setAttribute("aria-pressed", String(!manual));
  document.getElementById("manualMode").setAttribute("aria-pressed", String(manual));
  resetEditor();
  dayFoodForm.hidden = !manual;
  setFoodStatus("");
  (manual ? fields.name : document.getElementById("foodQuery")).focus();
}
document.getElementById("lookupMode").addEventListener("click", () => chooseMode(false));
document.getElementById("manualMode").addEventListener("click", () => chooseMode(true));
document.getElementById("cancelDayFood").addEventListener("click", () => {
  if (savingFood || DAY_LOCKED || dayLockChanging) return;
  resetEditor();
  dayFoodForm.hidden = true;
  setFoodStatus("");
});
function numericField(field, optional=false) {
  if (optional && field.value.trim() === "") return null;
  const value = Number(field.value);
  return field.value.trim() !== "" && Number.isFinite(value) && value >= 0 ? value : NaN;
}
function readFoodValues() {
  const values = {
    name:fields.name.value.trim(),
    serving_label:fields.serving_label.value.trim(),
    servings:parseAmount(fields.servings.value) ?? NaN,
    source_url:selectedSource,
    serving_g:portionState && portionIsValid() ? portionState.grams : null
  };
  nutrientKeys.forEach(key => values[key] = numericField(fields[key], key === "fiber"));
  return values;
}
function hasValidMacros(values) {
  return portionIsValid() && Number.isFinite(values.servings) && values.servings > 0 &&
    nutrientKeys.every(key => (key === "fiber" && values[key] === null) ||
      (Number.isFinite(values[key]) && Number.isFinite(values[key] * values.servings)));
}
function macroSummary(food) {
  const servings = n(food.servings);
  const pieces = [
    rounded(n(food.calories)*servings)+" kcal",
    rounded(n(food.protein)*servings)+" g protein",
    rounded(n(food.carbs)*servings)+" g carbs",
    rounded(n(food.fat)*servings)+" g fat",
    food.fiber == null ? "fiber unknown" : rounded(n(food.fiber)*servings)+" g fiber"
  ];
  return pieces.join(" · ");
}
function renderFoodPreview() {
  const values = readFoodValues();
  const totalGrams = portionIsValid() && portionState && Number.isFinite(values.servings) ?
    portionState.grams * values.servings : null;
  document.getElementById("portionSummary").textContent = totalGrams != null ?
    "Total eaten: " + (portionState.estimated ? "~" : "") + rounded(totalGrams, 3) +
      " g (" + rounded(values.servings, 3) + " x " + rounded(portionState.grams, 3) + " g per serving)." : "";
  document.getElementById("foodPreview").textContent = hasValidMacros(values)
    ? "This entry adds: "+macroSummary(values)
    : "Fill in the macros to preview this entry.";
}
function portionLabel(portion, estimated=false) {
  const weight = rounded(portion.grams, 3);
  // Packaged labels already include their measured serving, if supplied.
  return portion.id === "label" ? portion.label : portion.label.slice(0, 85) +
    " (" + (estimated ? "~" : "") + weight + " g)";
}
function portionIsValid() {
  return !portionState || (Number.isFinite(portionState.grams) && portionState.grams > 0);
}
function scalePortionMacros() {
  nutrientKeys.forEach(key => {
    const density = portionState.density[key];
    fields[key].readOnly = savingFood;
    fields[key].value = density == null || !Number.isFinite(density) ? "" :
      rounded(density * portionState.grams / 100, 4);
  });
}
function applyPortion(portion, estimated, writeGrams=true) {
  const oldCountable = portionState.countable;
  portionState.grams = portion.grams;
  portionState.estimated = estimated;
  portionState.countable = Boolean(portion.countable);
  if (portion.id !== "custom" && oldCountable && !portionState.countable) {
    fields.servings.value = 1;
    amountControls.get(fields.servings).sync(true);
  }
  if (writeGrams) gramInput.value = portion.grams;
  gramInput.setCustomValidity("");
  document.getElementById("basisWarning").hidden = true;
  document.getElementById("gramLabel").textContent = estimated ?
    "Estimated grams per serving" : "Grams per serving";
  fields.serving_label.value = portionLabel(portion, estimated).slice(0, 120);
  scalePortionMacros();
  renderFoodPreview();
}
portionSelect.addEventListener("change", () => {
  if (!portionState || savingFood) return;
  const portion = portionState.portions.find(portion => portion.id === portionSelect.value);
  if (portion) applyPortion(portion, portionState.sourceEstimated);
  else if (portionIsValid()) {
    applyPortion({id:"custom", label:"Custom portion", grams:portionState.grams, countable:false}, false);
  } else gramInput.focus();
});
gramInput.addEventListener("input", () => {
  if (!portionState || savingFood) return;
  const grams = numericField(gramInput);
  if (!Number.isFinite(grams) || grams <= 0) {
    portionState.grams = null;
    gramInput.setCustomValidity("Enter a weight greater than zero.");
    nutrientKeys.forEach(key => fields[key].readOnly = true);
    renderFoodPreview();
    return;
  }
  gramInput.setCustomValidity("");
  portionSelect.value = "custom";
  applyPortion({id:"custom", label:"Custom portion", grams, countable:false}, false, false);
});
nutrientKeys.forEach(key => fields[key].addEventListener("input", () => {
  if (!portionState || !portionIsValid()) return;
  // An edited macro becomes the density for later size/weight changes.
  const value = numericField(fields[key], key === "fiber");
  portionState.density[key] = value == null ? null : value * 100 / portionState.grams;
}));
function setupPortion(product) {
  let density = product.nutrition_per_100g;
  if (!density && product.basis === "100g") {
    density = Object.fromEntries(nutrientKeys.map(key => [key, product[key]]));
  } else if (!density && product.serving_g > 0) {
    density = Object.fromEntries(nutrientKeys.map(key => [key,
      product[key] == null ? null : product[key] * 100 / product.serving_g]));
  }
  if (!density) {
    document.getElementById("portionNote").textContent =
      "Use the package's label serving and enter servings eaten. Its weight in grams is not available.";
    return;
  }
  const portions = (Array.isArray(product.portions) ? product.portions : []).filter(portion =>
    typeof portion.label === "string" && Number.isFinite(Number(portion.grams)) && Number(portion.grams) > 0
  ).map(portion => ({...portion, id:String(portion.id), grams:Number(portion.grams)}));
  if (!portions.length && product.basis === "serving" && product.serving_g > 0) {
    portions.push({id:"label", label:product.serving_label || "1 serving", grams:Number(product.serving_g), countable:false});
  }
  portionState = {density:{...density}, portions, grams:null, estimated:false,
    sourceEstimated:Boolean(product.portion_estimated), countable:false};
  portionSelect.replaceChildren();
  for (const portion of portions) {
    const option = document.createElement("option");
    option.value = portion.id;
    option.textContent = portionLabel(portion, portionState.sourceEstimated);
    portionSelect.appendChild(option);
  }
  const custom = document.createElement("option");
  custom.value = "custom";
  custom.textContent = "Custom grams";
  portionSelect.appendChild(custom);
  document.getElementById("portionControls").hidden = false;
  gramInput.required = true;
  const selected = portions.find(portion => portion.id === String(product.default_portion_id)) || portions[0];
  document.getElementById("portionNote").textContent = product.kind === "generic" ?
    "Typical edible weights are estimates. Choose a size or enter your measured grams, then set servings eaten." :
    "Start with the label serving or enter your measured grams, then set servings eaten.";
  if (selected && product.basis === "serving") {
    portionSelect.value = selected.id;
    applyPortion(selected, portionState.sourceEstimated);
  } else {
    portionSelect.value = "custom";
    fields.servings.value = 1;
    fields.serving_label.value = "Custom portion";
    nutrientKeys.forEach(key => {
      fields[key].value = "";
      fields[key].readOnly = true;
    });
    gramInput.value = "";
    gramInput.setCustomValidity("Enter the weight you ate before saving.");
    document.getElementById("basisWarning").hidden = false;
    document.getElementById("basisWarning").textContent =
      "This food has nutrition per 100 g but no reliable serving weight. Enter grams to calculate your portion.";
  }
}

dayFoodForm.addEventListener("input", renderFoodPreview);
function selectProduct(product, suggestedServings) {
  if (savingFood || DAY_LOCKED || dayLockChanging) return;
  resetEditor();
  fields.name.value = [product.name, product.brand].filter(Boolean).join(" — ").slice(0, 160);
  fields.serving_label.value = product.basis === "100g" ? "100 g" : (product.serving_label || "1 serving");
  // Item-count hints apply only to sourced single-item portions. A label
  // serving may contain several items, and a cup is a different measure.
  fields.servings.value = product.portion_countable && Number.isFinite(Number(suggestedServings)) &&
    Number(suggestedServings) > 0 ? Number(suggestedServings) : 1;
  nutrientKeys.forEach(key => fields[key].value = product[key] == null ? "" : product[key]);
  selectedSource = trustedSource(product.source_url);
  const source = document.getElementById("foodSource");
  addSourceLink(source, selectedSource);
  source.hidden = !selectedSource;
  setupPortion(product);
  dayFoodForm.hidden = false;
  setFoodStatus("");
  amountControls.get(fields.servings).sync(true);
  renderFoodPreview();
  (portionState && !portionIsValid() ? gramInput : amountControls.get(fields.servings).slider).focus();
}
function renderLookupResults(products, suggestedServings) {
  lookupResults.replaceChildren();
  for (const product of products) {
    const card = document.createElement("div");
    card.className = "food-result";
    const heading = document.createElement("strong");
    heading.textContent = product.name || "Unnamed food";
    const details = document.createElement("p");
    details.className = "small";
    details.textContent = [product.brand, product.kind === "generic" ? "Plain food" : "", product.basis === "100g" ? "Per 100 g — portion adjustment required" :
      "Per "+(product.serving_label || "serving")].filter(Boolean).join(" · ");
    const macros = document.createElement("p");
    macros.className = "small";
    macros.textContent = macroSummary({...product, servings:1});
    const pick = document.createElement("button");
    pick.className = "btn";
    pick.type = "button";
    pick.textContent = "Use this food";
    pick.addEventListener("click", () => selectProduct(product, suggestedServings));
    const source = document.createElement("p");
    source.className = "small";
    addSourceLink(source, product.source_url);
    card.append(heading, details, macros, pick, source);
    lookupResults.appendChild(card);
  }
}
async function requestJson(url, options={}) {
  const response = await fetch(url, options);
  let data;
  try {
    data = await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("The server could not complete this request. Try again.");
  }
  if (!response.ok || !data.ok) {
    throw new Error(typeof data.error === "string" ? data.error : "This request failed. Try again.");
  }
  return data;
}
function invalidateLookup() {
  lookupGeneration++;
  lookupController?.abort();
  lookupController = null;
  lookupPendingQuery = "";
  lookupResults.replaceChildren();
  lookupStatus.textContent = "";
  lookupStatus.classList.remove("food-error");
  lookupButton.disabled = false;
  lookupButton.textContent = "Look up food";
}
function handleQueryEdit() {
  if (foodQuery.value === lookupInputValue) return;
  lookupInputValue = foodQuery.value;
  invalidateLookup();
  if (!savingFood && document.getElementById("lookupMode").getAttribute("aria-pressed") === "true") {
    resetEditor();
    dayFoodForm.hidden = true;
  }
}
foodQuery.addEventListener("input", handleQueryEdit);
foodQuery.addEventListener("search", handleQueryEdit);
lookupForm.addEventListener("submit", async event => {
  event.preventDefault();
  const query = foodQuery.value.trim();
  if (!query) {
    invalidateLookup();
    return;
  }
  if (lookupController && lookupPendingQuery === query) return;
  invalidateLookup();
  lookupInputValue = foodQuery.value;
  const generation = lookupGeneration;
  const controller = new AbortController();
  lookupController = controller;
  lookupPendingQuery = query;
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, LOOKUP_TIMEOUT_MS);
  lookupButton.disabled = true;
  lookupButton.textContent = "Looking up...";
  lookupStatus.textContent = "Looking up matching foods...";
  const currentSearch = () => generation === lookupGeneration && foodQuery.value.trim() === query && !document.getElementById("lookupArea").hidden;
  try {
    const data = await requestJson("/api/food-lookup?q="+encodeURIComponent(query), {signal:controller.signal});
    if (!currentSearch()) return;
    const products = Array.isArray(data.products) ? data.products : [];
    renderLookupResults(products, data.suggested_servings);
    lookupStatus.textContent = products.length
      ? (data.message || "Choose the food and portion that match what you ate. You can edit its macros before saving.")
      : "No matching foods found. Try a more specific food or brand, or choose Enter macros.";
  } catch (error) {
    if (!currentSearch()) return;
    if (error.name === "AbortError" && !timedOut) return;
    lookupStatus.classList.add("food-error");
    lookupStatus.textContent = timedOut
      ? "This search took too long. Try again or choose Enter macros."
      : error instanceof TypeError
        ? "Couldn't connect to food lookup. Try again or choose Enter macros."
        : error.message;
  } finally {
    clearTimeout(timeout);
    if (generation === lookupGeneration) {
      lookupController = null;
      lookupPendingQuery = "";
      lookupButton.disabled = false;
      lookupButton.textContent = "Look up food";
    }
  }
});
function updateDayFoods(data) {
  dayFoodTotals = computeDayFoodTotals();
  renderDayFoods();
  renderTotals();
}
function renderDayFoods() {
  document.getElementById("dayFoodLog").hidden = dayFoods.length === 0;
  document.getElementById("dayFoodCount").textContent = dayFoods.length+" added";
  const list = document.getElementById("dayFoodList");
  list.replaceChildren();
  document.getElementById("dayFoodEmpty").hidden = dayFoods.length > 0;
  for (const food of dayFoods) {
    const item = document.createElement("li");
    item.className = "day-food-item";
    const content = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = food.name;
    const serving = document.createElement("p");
    serving.className = "small";
    serving.textContent = rounded(n(food.servings), 3)+" × "+(food.serving_label || "1 serving");
    const macros = document.createElement("p");
    macros.className = "small";
    macros.textContent = macroSummary(food);
    const source = document.createElement("p");
    source.className = "small";
    addSourceLink(source, food.source_url);
    content.append(name, serving, macros, source);
    const saltControls = document.createElement("div");
    saltControls.className = "logged-salt-controls";
    const saltLabel = document.createElement("label");
    saltLabel.className = "salt-inclusion";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(food.include_in_spins);
    checkbox.disabled = DAY_LOCKED || dayLockChanging || !(Number(food.serving_g) > 0) || updatingSaltFoods.has(food.id) || removingFoods.has(food.id);
    checkbox.setAttribute("aria-label", "Include "+food.name+" in salt shaker spins");
    checkbox.addEventListener("change", () => saveSaltSelection(food, checkbox.checked));
    const caption = document.createElement("span");
    caption.textContent = Number(food.serving_g) > 0 ?
      "Include in spins ("+rounded(Number(food.serving_g)*n(food.servings), 1)+" g)" :
      "Include in spins";
    saltLabel.append(checkbox, caption);
    saltControls.appendChild(saltLabel);
    if (!(Number(food.serving_g) > 0)) {
      const massLabel = document.createElement("label");
      massLabel.className = "logged-mass-label";
      massLabel.textContent = "Grams per serving";
      const mass = document.createElement("input");
      mass.type = "number";
      mass.min = "0";
      mass.max = "1000000";
      mass.step = "any";
      mass.inputMode = "decimal";
      mass.placeholder = "Weight needed";
      mass.disabled = DAY_LOCKED || dayLockChanging || updatingSaltFoods.has(food.id) || removingFoods.has(food.id);
      mass.setAttribute("aria-label", food.name+" grams per serving");
      mass.addEventListener("change", () => {
        const grams = numericField(mass);
        if (!Number.isFinite(grams) || grams <= 0 || grams > 1000000) {
          mass.setCustomValidity("Enter grams per serving greater than zero, up to 1,000,000.");
          mass.reportValidity();
          return;
        }
        mass.setCustomValidity("");
        saveSaltSelection(food, false, grams);
      });
      mass.addEventListener("input", () => mass.setCustomValidity(""));
      massLabel.appendChild(mass);
      saltControls.appendChild(massLabel);
    }
    content.appendChild(saltControls);
    const remove = document.createElement("button");
    remove.className = "btn danger";
    remove.type = "button";
    remove.textContent = removingFoods.has(food.id) ? "Removing…" : "Remove";
    remove.disabled = DAY_LOCKED || dayLockChanging || removingFoods.has(food.id) || updatingSaltFoods.has(food.id);
    remove.setAttribute("aria-label", "Remove "+food.name+" from "+DAY);
    remove.addEventListener("click", () => removeDayFood(food.id));
    item.append(content, remove);
    list.appendChild(item);
  }
}
async function saveSaltSelection(food, included, grams=food.serving_g) {
  if (DAY_LOCKED || dayLockChanging || updatingSaltFoods.has(food.id) || removingFoods.has(food.id)) return;
  updatingSaltFoods.add(food.id);
  renderDayFoods();
  setFoodStatus("");
  try {
    const payload = {day:DAY, include_in_spins:included};
    if (grams != null) payload.serving_g = grams;
    const data = await requestJson("/api/day-food/"+encodeURIComponent(food.id)+"/salt", {
      method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)
    });
    dayFoods = dayFoods.map(entry => entry.id === food.id ? data.entry : entry);
    updateDayFoods(data);
  } catch (error) {
    setFoodStatus(error instanceof TypeError ? "Could not save the salt selection. Try again." : error.message, true);
  } finally {
    updatingSaltFoods.delete(food.id);
    renderDayFoods();
  }
}

async function removeDayFood(id) {
  if (DAY_LOCKED || dayLockChanging || removingFoods.has(id) || updatingSaltFoods.has(id)) return;
  removingFoods.add(id);
  renderDayFoods();
  setFoodStatus("");
  try {
    const data = await requestJson("/api/day-food/"+encodeURIComponent(id), {
      method:"DELETE",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({day:DAY})
    });
    dayFoods = dayFoods.filter(food => food.id !== id);
    updateDayFoods(data);
    setFoodStatus("Food removed from "+DAY+".");
  } catch (error) {
    setFoodStatus(error instanceof TypeError ? "Could not remove this food. Check your connection and try again." : error.message, true);
  } finally {
    removingFoods.delete(id);
    renderDayFoods();
  }
}
dayFoodForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (DAY_LOCKED || dayLockChanging || savingFood || !dayFoodForm.reportValidity()) return;
  const values = readFoodValues();
  if (!values.name || !values.serving_label || !hasValidMacros(values)) {
    setFoodStatus("Enter a food name, serving size, and valid nonnegative macros. Servings eaten must be greater than zero.", true);
    return;
  }
  savingFood = true;
  Object.values(fields).forEach(field => field.readOnly = true);
  gramInput.readOnly = true;
  portionSelect.disabled = true;
  amountControls.get(fields.servings).slider.disabled = true;
  saveDayFood.disabled = true;
  document.getElementById("cancelDayFood").disabled = true;
  document.getElementById("lookupMode").disabled = true;
  document.getElementById("manualMode").disabled = true;
  saveDayFood.textContent = "Saving…";
  setFoodStatus("");
  try {
    const data = await requestJson("/api/day-food", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({day:DAY, ...values})
    });
    dayFoods.push(data.entry);
    updateDayFoods(data);
    resetEditor();
    dayFoodForm.hidden = document.getElementById("manualMode").getAttribute("aria-pressed") !== "true";
    setFoodStatus(values.name+" saved to "+DAY+".");
  } catch (error) {
    setFoodStatus(error instanceof TypeError ? "Could not save this food. Check your connection and try again." : error.message, true);
  } finally {
    savingFood = false;
    Object.values(fields).forEach(field => field.readOnly = false);
    gramInput.readOnly = false;
    portionSelect.disabled = false;
    amountControls.get(fields.servings).slider.disabled = false;
    saveDayFood.disabled = false;
    document.getElementById("cancelDayFood").disabled = false;
    document.getElementById("lookupMode").disabled = false;
    document.getElementById("manualMode").disabled = false;
    saveDayFood.textContent = "Save to "+DAY;
  }
});
renderDayFoods();
renderTotals();

function applyDayEditingState() {
  const blocked = DAY_LOCKED || dayLockChanging;
  inputs.forEach(input => input.disabled = blocked);
  document.querySelectorAll(".foodrow .amount-range, #dayFoodPanel input, #dayFoodPanel button, #dayFoodPanel select, #dayFoodPanel textarea")
    .forEach(control => control.disabled = blocked);
  document.getElementById("resetDayButton").disabled = blocked;
  document.querySelectorAll("#dayFoodList input, #dayFoodList button")
    .forEach(control => {
      if (blocked) control.disabled = true;
    });
}
const dayLockButton = document.getElementById("dayLockButton");
const dayLockNotice = document.getElementById("dayLockNotice");
dayLockButton.addEventListener("click", async () => {
  if (dayLockChanging) return;
  if (savingFood || removingFoods.size || updatingSaltFoods.size) {
    dayLockNotice.hidden = false;
    dayLockNotice.textContent = "Wait for the current food save to finish, then lock the day.";
    return;
  }
  dayLockChanging = true;
  dayLockButton.disabled = true;
  dayLockButton.textContent = DAY_LOCKED ? "Unlocking..." : "Locking...";
  invalidateLookup();
  applyDayEditingState();
  let reloading = false;
  try {
    // Finish all queued slider/checkbox releases before capturing the day.
    await Promise.allSettled(inputs.map(input => saveChains.get(input)).filter(Boolean));
    if (!DAY_LOCKED && saveErrors.size) throw new Error("An entry failed to save. Retry it before locking the day.");
    await requestJson("/api/day-lock", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({day:DAY, locked:!DAY_LOCKED})
    });
    reloading = true;
    window.location.reload();
  } catch (error) {
    dayLockNotice.hidden = false;
    dayLockNotice.textContent = error instanceof TypeError ? "Could not change the day lock. Try again." : error.message;
  } finally {
    if (!reloading) {
      dayLockChanging = false;
      dayLockButton.disabled = false;
      dayLockButton.textContent = DAY_LOCKED ? "Unlock day" : "Lock day";
      renderDayFoods();
      applyDayEditingState();
    }
  }
});
applyDayEditingState();
