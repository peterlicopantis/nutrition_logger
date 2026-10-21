const dashboardConfig = JSON.parse(document.getElementById("dashboardConfig").dataset.config);
const DAY = dashboardConfig.day;
const DAY_LOCKED = Boolean(dashboardConfig.dayLocked);
let dayLockChanging = false;
const SALT_CATEGORY = dashboardConfig.saltCategory || "Dawg Bowl";
let SALT_GRAMS_PER_SPIN = dashboardConfig.saltGramsPerSpin;
const SHAKER_CALIBRATION = dashboardConfig.shakerCalibration;
let confirmedSaltPercent = SHAKER_CALIBRATION.salt_g_per_spin * 100 / SALT_GRAMS_PER_SPIN;
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
  if (phoneLayout.matches) document.getElementById("mobileFoodTabs").scrollIntoView({block:"start"});
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
  let grams = 0, riceBonus = 0, riceGrams = 0, riceSaltWeight = 0;
  for (const input of inputs) {
    if (input.closest(".section")?.dataset.category === SALT_CATEGORY &&
        input.closest(".foodrow")?.dataset.unit === "g") {
      const mass = n(input.dataset.amount);
      grams += mass;
      riceBonus += mass * n(input.dataset.saltExtra);
      if (isRiceForSpins(input.dataset.name)) {
        riceGrams += mass;
        riceSaltWeight += mass * (1 + n(input.dataset.saltExtra));
      }
    }
  }
  for (const food of dayFoods) {
    if (food.include_in_spins && Number(food.serving_g) > 0) {
      const mass = Number(food.serving_g) * n(food.servings);
      grams += mass;
      const factor = food.salt_extra_weight_factor ??
        (isRiceForSpins(food.name) ? 1.5 : 0);
      riceBonus += mass * n(factor);
      if (isRiceForSpins(food.name)) {
        riceGrams += mass;
        riceSaltWeight += mass * (1 + n(factor));
      }
    }
  }
  grams += riceBonus;
  const spins = grams / SALT_GRAMS_PER_SPIN;
  return {grams, spins, riceBonus, riceGrams, riceSaltWeight,
    saltDispensed:spins * SHAKER_CALIBRATION.salt_g_per_spin,
    sodiumMg:spins * SHAKER_CALIBRATION.sodium_mg_per_spin};
}
function saltedRicePlan(result=computeSaltSpins()) {
  const recipeSaltG = result.riceGrams * 3 / 185;
  const riceSaltG = Math.min(recipeSaltG, result.saltDispensed);
  const bowlSaltG = Math.max(0, result.saltDispensed - riceSaltG);
  const riceSpins = riceSaltG / SHAKER_CALIBRATION.salt_g_per_spin;
  const riceSodiumMg = riceSpins * SHAKER_CALIBRATION.sodium_mg_per_spin;
  return {
    riceGrams:result.riceGrams, recipeSaltG, riceSaltG, riceSpins, riceSodiumMg,
    bowlSpins:bowlSaltG / SHAKER_CALIBRATION.salt_g_per_spin, bowlSaltG,
    bowlSodiumMg:Math.max(0, result.sodiumMg - riceSodiumMg),
    totalSaltG:result.saltDispensed, totalSodiumMg:result.sodiumMg,
    riceLimited:recipeSaltG > result.saltDispensed + 1e-9
  };
}

function variableSaltMode() {
  return Boolean(document.getElementById("saltVariableMode")?.checked);
}
function variableRatioValue(id, fallback) {
  const control = document.getElementById(id);
  const value = control?.dataset?.validValue ?? control?.value;
  return value === undefined || value === "" ? fallback : Number(value);
}
function variableSaltPlan(result=computeSaltSpins()) {
  const riceRatio = variableRatioValue("riceRatioInput", 3);
  const mealPercent = variableRatioValue("mealRatioInput", 0.5);
  const mealGrams = Math.max(0, result.grams - result.riceBonus - result.riceGrams);
  const riceSaltG = result.riceGrams * riceRatio / 185;
  const bowlSaltG = mealGrams * mealPercent / 100;
  const sodiumPerGram = SHAKER_CALIBRATION.sodium_mg_per_spin / SHAKER_CALIBRATION.salt_g_per_spin;
  return {
    riceGrams:result.riceGrams, mealGrams, riceRatio, mealPercent,
    recipeSaltG:riceSaltG, riceSaltG, bowlSaltG,
    riceSpins:riceSaltG / SHAKER_CALIBRATION.salt_g_per_spin,
    bowlSpins:bowlSaltG / SHAKER_CALIBRATION.salt_g_per_spin,
    riceSodiumMg:riceSaltG * sodiumPerGram, bowlSodiumMg:bowlSaltG * sodiumPerGram,
    totalSaltG:riceSaltG + bowlSaltG, totalSodiumMg:(riceSaltG + bowlSaltG) * sodiumPerGram,
    riceLimited:false
  };
}
function activeSaltPlan(result=computeSaltSpins()) {
  return variableSaltMode() ? variableSaltPlan(result) : saltedRicePlan(result);
}

function syncSaltChoiceSelection() {
  const mode = document.getElementById("saltVariableMode");
  for (const [id, selected] of [["sharedSaltMode", !variableSaltMode()], ["variableSaltMode", variableSaltMode()]]) {
    const button = document.getElementById(id);
    if (button) {
      button.setAttribute?.("aria-pressed", String(selected));
      button.disabled = Boolean(mode?.disabled);
    }
  }
  const rice = document.getElementById("ricePreparation");
  if (rice) {
    const backing = document.getElementById("riceSalted");
    rice.value = backing?.checked ? "salted" : "unsalted";
    rice.disabled = Boolean(backing?.disabled);
  }
}

function renderSaltSpins() {
  const result = computeSaltSpins();
  const percentLabel = document.getElementById("saltPercentLabel");
  const spinRatio = document.getElementById("saltSpinRatio");
  if (percentLabel) percentLabel.textContent = (SHAKER_CALIBRATION.salt_g_per_spin * 100 / SALT_GRAMS_PER_SPIN).toFixed(2) + "%";
  if (spinRatio) spinRatio.textContent = "1 spin / " + rounded(SALT_GRAMS_PER_SPIN, 2) + " g";
  document.getElementById("saltSpins").textContent = rounded(result.spins, 1);
  document.getElementById("saltMealGrams").textContent = rounded(result.grams, 1);
  document.getElementById("saltRiceBonus").textContent = rounded(result.riceBonus, 1);
  document.getElementById("saltDispensed").textContent = rounded(result.saltDispensed, 2).toFixed(2);
  document.getElementById("saltSodium").textContent = Math.round(result.sodiumMg).toLocaleString("en-US");
  syncSaltChoiceSelection();
  const variable = variableSaltMode();
  const salted = variable || Boolean(document.getElementById("riceSalted")?.checked);
  const modeLabel = document.getElementById("saltCalculationMode");
  if (modeLabel) modeLabel.textContent = variable ? "Variable ratios" : "Shared total";
  for (const [id, hidden] of [["riceSaltToggle", variable], ["saltRatioControls", variable],
      ["riceVariableRatio", !variable], ["mealVariableRatio", !variable]]) {
    const element = document.getElementById(id);
    if (element) element.hidden = hidden;
  }
  document.getElementById("riceSaltMode").textContent = salted ? "Salted rice" : "Unsalted rice";
  document.getElementById("unsaltedSaltSummary").hidden = salted;
  document.getElementById("riceSaltBreakdown").hidden = !salted;
  const separateSeasoning = salted && hasPortionSeasoningControls();
  document.getElementById("dashboardActions")?.classList?.toggle("rice-salted-mode", separateSeasoning);
  document.getElementById("seasoningToggle").hidden = separateSeasoning;
  if (separateSeasoning) {
    document.getElementById("seasoningPanel").hidden = true;
    document.getElementById("seasoningToggle").setAttribute?.("aria-expanded", "false");
  }
  if (salted) {
    const plan = activeSaltPlan(result);
    document.getElementById("riceDryWeight").textContent = rounded(plan.riceGrams, 1) + " g dry";
    document.getElementById("riceSaltAmount").textContent = plan.riceSaltG.toFixed(2) + " g salt";
    // Assign the rounding remainder to the bowl so the displayed salt sums too.
    const displayedBowl = Math.max(0, rounded(plan.totalSaltG, 2) - rounded(plan.riceSaltG, 2));
    document.getElementById("bowlSaltAmount").textContent = displayedBowl.toFixed(2) + " g salt";
    const note = document.getElementById("riceSaltAllocationNote");
    if (note) {
      note.hidden = !plan.riceLimited;
      note.textContent = plan.riceLimited ? "Rice recipe: " + plan.recipeSaltG.toFixed(2) +
        " g salt; limited to the bowl's " + plan.totalSaltG.toFixed(2) + " g total. No additional bowl salt." : "";
    }
    document.getElementById("riceSaltDetails").textContent = "~" + rounded(plan.riceSpins, 1) +
      " spins \u00b7 " + Math.round(plan.riceSodiumMg).toLocaleString("en-US") + " mg sodium";
    const displayedBowlSodium = Math.max(0, Math.round(plan.totalSodiumMg) - Math.round(plan.riceSodiumMg));
    document.getElementById("bowlSaltDetails").textContent = "~" + rounded(plan.bowlSpins, 1) +
      " spins \u00b7 " + displayedBowlSodium.toLocaleString("en-US") + " mg sodium";
    document.getElementById("riceSaltAmount")?.closest?.(".salt-portion")?.setAttribute("title",
      variable ? plan.riceRatio + " g salt per 185 g dry rice" : "Rice salt allocated from the shared total");
    document.getElementById("bowlSaltAmount")?.closest?.(".salt-portion")?.setAttribute("title",
      variable ? plan.mealPercent + "% salt by actual non-rice food weight" : "Shared total minus the rice allocation");
    const combined = document.getElementById("saltCombinedTotal");
    if (combined) {
      combined.hidden = false;
      combined.textContent = "Combined added salt: " + plan.totalSaltG.toFixed(2) + " g \u00b7 " +
        Math.round(plan.totalSodiumMg).toLocaleString("en-US") + " mg sodium";
    }
    if (variable) {
      const riceLabel = document.getElementById("riceRatioLabel");
      const mealLabel = document.getElementById("mealRatioLabel");
      if (riceLabel) riceLabel.textContent = rounded(plan.riceRatio, 3) + " g / 185 g dry";
      if (mealLabel) mealLabel.textContent = rounded(plan.mealPercent, 3) + "%";
      const mealDetails = document.getElementById("bowlSaltDetails");
      mealDetails.textContent += " \u00b7 " + rounded(plan.mealGrams, 1) + " g food";
    }
  }
  if (!salted) {
    const combined = document.getElementById("saltCombinedTotal");
    if (combined) combined.hidden = true;
  }
  for (const input of inputs) {
    if (!isRiceForSpins(input.dataset.name)) continue;
    const badge = input.closest(".foodrow")?.querySelector?.(".rice-salt-badge");
    if (badge) {
      badge.textContent = salted ? "Salted separately" : rounded(1 + n(input.dataset.saltExtra), 3) + "\u00d7 salt weight";
      badge.title = variable ? "Rice uses its own ratio in variable mode; extra salt weight is not applied." :
        salted ? "Rice salt is allocated from the shared total." :
        "For salt spins: entered grams plus " + n(input.dataset.saltExtra) + " times extra. Calories and macros use the entered grams.";
    }
  }
  renderSeasoningCalculator(result.sodiumMg);
}

function seasoningGramsFor(targetSodiumMg, servingGrams, sodiumPerServing) {
  if (![targetSodiumMg, servingGrams, sodiumPerServing].every(Number.isFinite) ||
      targetSodiumMg < 0 || servingGrams <= 0 || sodiumPerServing <= 0) return null;
  const grams = targetSodiumMg / sodiumPerServing * servingGrams;
  return Number.isFinite(grams) ? grams : null;
}
function seasoningMessage(targetSodiumMg, servingValue, sodiumValue) {
  const servingText = String(servingValue ?? "").trim().replace(",", ".");
  const sodiumText = String(sodiumValue ?? "").trim().replace(",", ".");
  if (!servingText || !sodiumText) return "Enter a serving size and sodium per serving to calculate grams.";
  const grams = seasoningGramsFor(targetSodiumMg, Number(servingText), Number(sodiumText));
  if (grams === null) return "Serving size and sodium per serving must both be greater than zero.";
  const amount = grams > 0 && grams < 0.01 ? "<0.01" : rounded(grams, 2).toFixed(2);
  return "Use ~" + amount + " g of seasoning to match ~" +
    Math.round(targetSodiumMg).toLocaleString("en-US") + " mg sodium.";
}
function hasPortionSeasoningControls() {
  return ["rice", "bowl"].every(portion =>
    ["Serving", "Sodium", "Result"].every(field => document.getElementById(portion + "Seasoning" + field)));
}
function renderSeasoningCalculator(targetSodiumMg=computeSaltSpins().sodiumMg) {
  const serving = document.getElementById("seasoningServing")?.value;
  const sodium = document.getElementById("seasoningSodium")?.value;
  const result = document.getElementById("seasoningResult");
  const plan = activeSaltPlan();
  if (variableSaltMode()) targetSodiumMg = plan.totalSodiumMg;
  // An already-running Flask process can still serve its cached older template
  // while static files update immediately. Keep that page functional as well.
  if (result) {
    result.textContent = (variableSaltMode() || document.getElementById("riceSalted")?.checked) && !hasPortionSeasoningControls() ?
      "Rice: " + seasoningMessage(plan.riceSodiumMg, serving, sodium) +
      "\nRest of bowl: " + seasoningMessage(plan.bowlSodiumMg, serving, sodium) :
      seasoningMessage(targetSodiumMg, serving, sodium);
  }
  for (const [portion, sodiumMg] of [["rice", plan.riceSodiumMg], ["bowl", plan.bowlSodiumMg]]) {
    const portionResult = document.getElementById(portion + "SeasoningResult");
    if (portionResult) portionResult.textContent = seasoningMessage(sodiumMg,
      document.getElementById(portion + "SeasoningServing")?.value,
      document.getElementById(portion + "SeasoningSodium")?.value);
  }
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
const scheduledAmountSaves = new Map();
function scheduleAmountSave(input, commit) {
  if (!input.classList.contains("food-input") || DAY_LOCKED || dayLockChanging) return;
  clearTimeout(scheduledAmountSaves.get(input)?.timer);
  const timer = setTimeout(() => {
    scheduledAmountSaves.delete(input);
    commit();
  }, 250);
  scheduledAmountSaves.set(input, {timer, commit});
}
function cancelAmountSave(input) {
  clearTimeout(scheduledAmountSaves.get(input)?.timer);
  scheduledAmountSaves.delete(input);
}
function flushAmountSaves() {
  for (const [input, job] of [...scheduledAmountSaves]) {
    cancelAmountSave(input);
    job.commit();
  }
}
// iOS can suspend a tab while its keyboard or slider is still active.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushAmountSaves();
});
window.addEventListener("pagehide", flushAmountSaves);
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
  let unit = control.dataset.unit;
  let baseMax = Number(control.dataset.max);
  let increment = Number(control.dataset.step);
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
  function saveDraft() {
    if (exact.readOnly || exact.disabled || slider.disabled) return;
    const amount = parseAmount(exact.value);
    if (amount === null) return;
    // Save without rewriting an in-progress decimal such as "12.".
    committed = amount;
    saveInput(exact);
  }
  function commit() {
    cancelAmountSave(exact);
    if (exact.readOnly || exact.disabled || slider.disabled) return;
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
      scheduleAmountSave(exact, saveDraft);
    } else {
      cancelAmountSave(exact);
    }
  });
  exact.addEventListener("change", commit);
  exact.addEventListener("blur", commit);
  exact.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      exact.blur();
    } else if (event.key === "Escape") {
      cancelAmountSave(exact);
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
    scheduleAmountSave(exact, saveDraft);
  });
  slider.addEventListener("change", commit);
  slider.addEventListener("pointerup", commit);
  slider.addEventListener("touchend", commit, {passive:true});
  slider.addEventListener("blur", commit);
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
  function setScale(nextUnit, nextMax, nextIncrement) {
    unit = nextUnit;
    baseMax = nextMax;
    increment = nextIncrement;
    slider.max = String(baseMax);
    sync(true);
  }
  amountControls.set(exact, {sync, slider, setScale});
}
const saveChains = new WeakMap();
const submittedAmounts = new WeakMap();
const saveErrors = new Set();
let pendingSaves = 0;
let riceSavePromise = Promise.resolve();
let saltPercentSaving = false;
let variableSaltSaving = false;
let resettingSaltRatios = false;
function showSaveStatus() {
  statusEl.classList.toggle("save-error", saveErrors.size > 0);
  statusEl.textContent = pendingSaves ? "Saving..." :
    saveErrors.size ? "Save failed - change the entry to retry" : "Saved";
  if (typeof syncSaltBoxUI === "function") syncSaltBoxUI();
}
function saveInput(el) {
  if (DAY_LOCKED || dayLockChanging) return Promise.resolve();
  const amount = n(el.dataset.amount);
  // Input, release and blur can all describe the same edit on a phone.
  if (submittedAmounts.get(el) === amount && !saveErrors.has(el)) {
    return saveChains.get(el) || Promise.resolve();
  }
  submittedAmounts.set(el, amount);
  pendingSaves++;
  showSaveStatus();
  // Serialize releases for the same food so an older request cannot win.
  const previous = saveChains.get(el) || Promise.resolve();
  const job = previous.catch(() => {}).then(async () => {
    try {
      const res = await fetch("/api/entry", {
        method:"POST",
        keepalive:true,
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
async function openDay(next) {
  flushAmountSaves();
  await Promise.allSettled(inputs.map(input => saveChains.get(input)).filter(Boolean));
  await riceSavePromise;
  if (saveErrors.size) return;
  window.location.href = "/?day=" + encodeURIComponent(next);
}
function navigateDay(offset) {
  const next = adjacentDay(DAY, offset);
  if (next) openDay(next);
}
document.getElementById("previousDay").addEventListener("click", () => navigateDay(-1));
document.getElementById("nextDay").addEventListener("click", () => navigateDay(1));

document.getElementById("dayPicker").addEventListener("change", (e) => {
  if (e.target.value) openDay(e.target.value);
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
  amount:document.getElementById("dfAmount"),
  calories:document.getElementById("dfCalories"),
  protein:document.getElementById("dfProtein"),
  carbs:document.getElementById("dfCarbs"),
  fat:document.getElementById("dfFat"),
  fiber:document.getElementById("dfFiber")
};
const portionSelect = document.getElementById("dfPortion");
const gramInput = document.getElementById("dfGrams");
let portionState = null;
let quantityWeight = null;
let quantityPinned = false;
let quantityDraftGrams = null;
let editingFoodId = null;
let selectedSource = null;
let savingFood = false;
let lookupGeneration = 0;
let lookupController = null;
let lookupPendingQuery = "";
let lookupProgressTimer = null;
let lookupInputValue = foodQuery.value;
const LOOKUP_TIMEOUT_MS = 25000;
const removingFoods = new Set();
const updatingSaltFoods = new Set();
const customHistoryPanel = document.getElementById("customFoodHistory");
const customHistoryQuery = document.getElementById("customFoodHistoryQuery");
const customHistoryStatus = document.getElementById("customFoodHistoryStatus");
let customHistory = [];
let customHistoryGeneration = 0;
let customHistoryController = null;
let customHistoryTimer = null;
const removingHistoryFoods = new Set();


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
  quantityWeight = null;
  quantityPinned = false;
  quantityDraftGrams = null;
  editingFoodId = null;
  document.getElementById("dayFoodEditorHeading").textContent = "Macros per serving";
  saveDayFood.textContent = "Save to " + DAY;
  nutrientKeys.forEach(key => fields[key].readOnly = savingFood);
  gramInput.required = false;
  gramInput.setCustomValidity("");
  portionSelect.replaceChildren();
  document.getElementById("gramLabel").textContent = "Grams per serving (optional)";
  document.getElementById("portionControls").hidden = true;
  document.getElementById("portionSummary").textContent = "";
  document.getElementById("portionNote").textContent =
    "Enter the label values and grams for one serving, then set grams eaten. Without a serving weight, use servings eaten.";
  dayFoodForm.reset();
  setQuantityScale(false);
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
function setQuantityScale(inGrams) {
  const label = inGrams ? "Grams eaten" : "Servings eaten";
  document.getElementById("foodQuantityLabel").textContent = label;
  fields.amount.setAttribute("aria-label", "Exact " + label.toLowerCase());
  const control = amountControls.get(fields.amount);
  control.slider.setAttribute("aria-label", label);
  control.setScale(inGrams ? "g" : "servings", inGrams ? 1000 : 10, inGrams ? 10 : 0.05);
}
function syncQuantityMode() {
  const weight = portionState ? portionState.grams : numericField(gramInput, true);
  const previousWeight = quantityWeight;
  const amount = parseAmount(fields.amount.value);
  if (Number.isFinite(weight) && weight > 0) {
    if (previousWeight === null && quantityDraftGrams !== null) {
      // Clearing a weight while replacing it must keep the user's eaten mass.
      fields.amount.value = quantityDraftGrams;
      quantityDraftGrams = null;
      quantityPinned = true;
    } else if (previousWeight === null || (!quantityPinned && weight !== previousWeight)) {
      const servings = previousWeight === null ? amount : amount / previousWeight;
      if (amount !== null) fields.amount.value = rounded(servings * weight, 10);
    }
    quantityWeight = weight;
  } else if (!portionState && weight === null && previousWeight !== null) {
    // An intentionally cleared manual weight returns to servings, preserving
    // the nutrition multiplier. Invalid/incomplete weights cannot reinterpret g.
    quantityDraftGrams = quantityPinned ? amount : null;
    if (amount !== null) fields.amount.value = rounded(amount / previousWeight, 10);
    quantityWeight = null;
    quantityPinned = false;
  }
  if ((quantityWeight === null) !== (previousWeight === null)) {
    setQuantityScale(quantityWeight !== null);
  } else {
    amountControls.get(fields.amount).sync();
  }
}
function pinQuantity() {
  if (quantityWeight !== null) quantityPinned = true;
  else quantityDraftGrams = null;
}
fields.amount.addEventListener("input", pinQuantity);
amountControls.get(fields.amount).slider.addEventListener("input", pinQuantity);
function readFoodValues() {
  const servingGrams = portionState ? (portionIsValid() ? portionState.grams : NaN) : numericField(gramInput, true);
  const amount = parseAmount(fields.amount.value) ?? NaN;
  const values = {
    name:fields.name.value.trim(),
    serving_label:fields.serving_label.value.trim(),
    servings:quantityWeight === null ? amount : amount / servingGrams,
    source_url:selectedSource,
    serving_g:servingGrams
  };
  nutrientKeys.forEach(key => values[key] = numericField(fields[key], key === "fiber"));
  return values;
}
function hasValidMacros(values) {
  return portionIsValid() && Number.isFinite(values.servings) && values.servings > 0 &&
    (values.serving_g === null || (Number.isFinite(values.serving_g) && values.serving_g > 0 && values.serving_g <= 1000000)) &&
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
  syncQuantityMode();
  const values = readFoodValues();
  const totalGrams = Number.isFinite(values.serving_g) && values.serving_g > 0 && Number.isFinite(values.servings) ?
    values.serving_g * values.servings : null;
  document.getElementById("portionSummary").textContent = totalGrams != null ?
    "Total eaten: " + (portionState?.estimated && !quantityPinned ? "~" : "") + rounded(totalGrams, 3) +
      " g (" + rounded(values.servings, 3) + " x " + rounded(values.serving_g, 3) + " g per serving)." : "";
  document.getElementById("foodPreview").textContent = hasValidMacros(values)
    ? "This entry adds: "+macroSummary(values)
    : "Fill in the macros to preview this entry.";
}
function portionLabel(portion, estimated=false) {
  const weight = rounded(portion.grams, 3);
  // Packaged labels already include their measured serving, if supplied.
  return ["label", "reference-100g"].includes(portion.id) ? portion.label : portion.label.slice(0, 85) +
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
  if (!quantityPinned && portion.id !== "custom" && portionState.countable && !portion.countable) {
    // A search count such as two carrots does not mean two cups. Once the
    // user enters their own eaten grams, changing the label keeps that mass.
    fields.amount.value = quantityWeight === null ? 1 : quantityWeight;
  }
  portionState.grams = portion.grams;
  portionState.estimated = estimated;
  portionState.countable = Boolean(portion.countable);
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
  if (savingFood) return;
  if (!portionState) {
    // Manual/edit/history values are already per serving. Weight records mass;
    // it must not multiply or overwrite the entered label macros.
    gramInput.setCustomValidity("");
    renderFoodPreview();
    return;
  }
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
  if (!portions.length && product.basis === "100g") {
    // A reference amount keeps the returned nutrition visible without
    // claiming a known item/package serving. The user can change its grams.
    portions.push({id:"reference-100g", label:"100 g (reference amount)", grams:100, countable:false});
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
    "Typical edible weights are estimates. Choose a serving size, then enter the total grams you ate." :
    "Check the label serving, then enter the total grams you ate.";
  if (selected && (product.basis === "serving" || selected.id === "reference-100g")) {
    portionSelect.value = selected.id;
    applyPortion(selected, portionState.sourceEstimated);
    if (selected.id === "reference-100g") {
      document.getElementById("portionNote").textContent =
        "Nutrition starts at the database's 100 g reference. Enter the total grams you ate; the nutrition scales to that weight.";
      document.getElementById("basisWarning").hidden = false;
      document.getElementById("basisWarning").textContent =
        "100 g is a reference amount, not a known item or package serving. Set Grams eaten to your measured weight.";
    }
  } else {
    portionSelect.value = "custom";
    fields.amount.value = 1;
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
  fields.amount.value = product.portion_countable && Number.isFinite(Number(suggestedServings)) &&
    Number(suggestedServings) > 0 ? Number(suggestedServings) : 1;
  nutrientKeys.forEach(key => fields[key].value = product[key] == null ? "" : product[key]);
  selectedSource = trustedSource(product.source_url);
  const source = document.getElementById("foodSource");
  addSourceLink(source, selectedSource);
  source.hidden = !selectedSource;
  setupPortion(product);
  dayFoodForm.hidden = false;
  setFoodStatus("");
  amountControls.get(fields.amount).sync(true);
  renderFoodPreview();
  (portionState && !portionIsValid() ? gramInput : amountControls.get(fields.amount).slider).focus();
}
function loadManualFood(food, entryId=null) {
  if (savingFood || DAY_LOCKED || dayLockChanging) return;
  if (entryId !== null && (removingFoods.has(entryId) || updatingSaltFoods.has(entryId))) return;
  invalidateLookup();
  resetEditor();
  fields.name.value = food.name;
  fields.serving_label.value = food.serving_label || "1 serving";
  fields.amount.value = entryId === null ? 1 : food.servings;
  nutrientKeys.forEach(key => fields[key].value = food[key] == null ? "" : food[key]);
  gramInput.value = Number(food.serving_g) > 0 ? food.serving_g : "";
  selectedSource = trustedSource(food.source_url);
  const source = document.getElementById("foodSource");
  addSourceLink(source, selectedSource);
  source.hidden = !selectedSource;
  editingFoodId = entryId;
  document.getElementById("dayFoodEditorHeading").textContent = entryId === null ? "Macros per serving" : "Edit logged food";
  saveDayFood.textContent = entryId === null ? "Save to " + DAY : "Save changes";
  document.getElementById("portionNote").textContent =
    "Enter nutrition and grams for one serving, then the total grams eaten. Changing the serving weight keeps your entered macros.";
  document.getElementById("lookupArea").hidden = true;
  document.getElementById("lookupMode").setAttribute("aria-pressed", "false");
  document.getElementById("manualMode").setAttribute("aria-pressed", "true");
  document.getElementById("dayFoodPanel").open = true;
  dayFoodForm.hidden = false;
  amountControls.get(fields.amount).sync(true);
  setFoodStatus("");
  renderFoodPreview();
  quantityPinned = entryId !== null && quantityWeight !== null;
  dayFoodForm.scrollIntoView({block:"nearest"});
  fields.amount.focus();
}
function editDayFood(food) {
  loadManualFood(food, food.id);
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
function renderCustomFoodHistory() {
  const list = document.getElementById("customFoodHistoryList");
  list.replaceChildren();
  document.getElementById("customFoodHistoryCount").textContent = customHistory.length ? "(" + customHistory.length + ")" : "";
  for (const food of customHistory) {
    const item = document.createElement("li");
    item.className = "food-history-item";
    item.dataset.historyId = food.id;
    const content = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = food.name;
    const basis = document.createElement("p");
    basis.className = "small";
    basis.textContent = "Per " + (food.serving_label || "1 serving") +
      (Number(food.serving_g) > 0 ? " (" + rounded(Number(food.serving_g), 3) + " g)" : "");
    const macros = document.createElement("p");
    macros.className = "small";
    macros.textContent = macroSummary({...food, servings:1});
    content.append(name, basis, macros);
    const actions = document.createElement("div");
    actions.className = "food-history-actions";
    const busy = removingHistoryFoods.has(food.id);
    const use = document.createElement("button");
    use.type = "button";
    use.className = "btn use-history-food";
    use.textContent = "Use this food";
    use.disabled = DAY_LOCKED || dayLockChanging || savingFood || busy;
    use.addEventListener("click", () => {
      if (!removingHistoryFoods.has(food.id)) loadManualFood(food);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn danger history-remove";
    remove.textContent = busy ? "Removing..." : "Remove from history";
    remove.disabled = busy || savingFood;
    remove.setAttribute("aria-label", "Remove " + food.name + " from history");
    remove.addEventListener("click", () => removeCustomFoodHistory(food.id));
    actions.append(use, remove);
    item.append(content, actions);
    list.appendChild(item);
  }
}
async function refreshCustomFoodHistory() {
  clearTimeout(customHistoryTimer);
  customHistoryController?.abort();
  const generation = ++customHistoryGeneration;
  const controller = new AbortController();
  customHistoryController = controller;
  const query = customHistoryQuery.value.trim();
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  customHistoryStatus.textContent = "Loading custom foods...";
  customHistoryStatus.classList.remove("food-error");
  try {
    const data = await requestJson("/api/day-food-history?q=" + encodeURIComponent(query), {
      signal:controller.signal, cache:"no-store"
    });
    if (generation !== customHistoryGeneration || customHistoryQuery.value.trim() !== query) return;
    customHistory = Array.isArray(data.entries) ? data.entries : [];
    renderCustomFoodHistory();
    customHistoryStatus.textContent = customHistory.length ? "" :
      query ? "No matching custom foods." : "Your manually entered foods will appear here after saving.";
  } catch (error) {
    if (generation !== customHistoryGeneration) return;
    if (error.name === "AbortError" && !timedOut) return;
    customHistory = [];
    renderCustomFoodHistory();
    customHistoryStatus.classList.add("food-error");
    customHistoryStatus.textContent = "Could not load custom food history. Change the search to try again.";
  } finally {
    clearTimeout(timeout);
    if (generation === customHistoryGeneration) customHistoryController = null;
  }
}
function queueCustomFoodHistory() {
  clearTimeout(customHistoryTimer);
  customHistoryController?.abort();
  customHistoryGeneration++;
  customHistory = [];
  renderCustomFoodHistory();
  customHistoryStatus.textContent = "Searching custom foods...";
  customHistoryStatus.classList.remove("food-error");
  customHistoryTimer = setTimeout(refreshCustomFoodHistory, 200);
}
customHistoryQuery.addEventListener("input", queueCustomFoodHistory);
customHistoryQuery.addEventListener("search", queueCustomFoodHistory);
async function removeCustomFoodHistory(id) {
  if (removingHistoryFoods.has(id) || savingFood) return;
  removingHistoryFoods.add(id);
  renderCustomFoodHistory();
  try {
    await requestJson("/api/day-food-history/" + encodeURIComponent(id), {method:"DELETE"});
    customHistory = customHistory.filter(food => food.id !== id);
    renderCustomFoodHistory();
    await refreshCustomFoodHistory();
  } catch (error) {
    customHistoryStatus.classList.add("food-error");
    customHistoryStatus.textContent = "Could not remove this food from history. Try again.";
  } finally {
    removingHistoryFoods.delete(id);
    renderCustomFoodHistory();
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
  clearTimeout(lookupProgressTimer);
  lookupProgressTimer = null;
  lookupController?.abort();
  lookupController = null;
  lookupPendingQuery = "";
  lookupResults.replaceChildren();
  lookupStatus.textContent = "";
  lookupStatus.classList.remove("food-error");
  lookupButton.disabled = false;
  lookupForm.setAttribute("aria-busy", "false");
  lookupButton.textContent = "Look up food";
}
function handleQueryEdit() {
  if (foodQuery.value === lookupInputValue) return;
  lookupInputValue = foodQuery.value;
  invalidateLookup();
  customHistoryQuery.value = foodQuery.value;
  queueCustomFoodHistory();
  if (foodQuery.value.trim()) customHistoryPanel.open = true;
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
  lookupForm.setAttribute("aria-busy", "true");
  lookupProgressTimer = setTimeout(() => {
    if (generation === lookupGeneration) {
      lookupStatus.textContent = "The food database is taking longer. Still searching automatically; you do not need to click again.";
    }
  }, 4000);
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
      clearTimeout(lookupProgressTimer);
      lookupProgressTimer = null;
      lookupForm.setAttribute("aria-busy", "false");
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
    const busy = DAY_LOCKED || dayLockChanging || updatingSaltFoods.has(food.id) || removingFoods.has(food.id) ||
      (savingFood && editingFoodId === food.id);
    const item = document.createElement("li");
    item.dataset.entryId = food.id;
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
    checkbox.disabled = busy || !(Number(food.serving_g) > 0);
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
      mass.disabled = busy;
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
    remove.disabled = busy;
    remove.setAttribute("aria-label", "Remove "+food.name+" from "+DAY);
    remove.addEventListener("click", () => removeDayFood(food.id));
    const edit = document.createElement("button");
    edit.className = "btn edit-day-food";
    edit.type = "button";
    edit.textContent = "Edit";
    edit.disabled = busy;
    edit.setAttribute("aria-label", "Edit " + food.name + " on " + DAY);
    edit.addEventListener("click", () => editDayFood(food));
    const actions = document.createElement("div");
    actions.className = "day-food-actions";
    actions.append(edit, remove);
    item.append(content, actions);
    list.appendChild(item);
  }
}
async function saveSaltSelection(food, included, grams=food.serving_g) {
  if (DAY_LOCKED || dayLockChanging || updatingSaltFoods.has(food.id) || removingFoods.has(food.id) ||
      (savingFood && editingFoodId === food.id)) return;
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
  if (DAY_LOCKED || dayLockChanging || removingFoods.has(id) || updatingSaltFoods.has(id) ||
      (savingFood && editingFoodId === id)) return;
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
    if (editingFoodId === id) {
      resetEditor();
      dayFoodForm.hidden = true;
    }
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
  if (editingFoodId !== null && (updatingSaltFoods.has(editingFoodId) || removingFoods.has(editingFoodId))) {
    setFoodStatus("Wait for this food's current change to finish, then save your edit.", true);
    return;
  }
  const values = readFoodValues();
  if (!values.name || !values.serving_label || !hasValidMacros(values)) {
    setFoodStatus("Enter a food name, serving size, and valid nonnegative macros. The amount eaten must be greater than zero.", true);
    return;
  }
  const submittedEditId = editingFoodId;
  savingFood = true;
  renderDayFoods();
  renderCustomFoodHistory();
  Object.values(fields).forEach(field => field.readOnly = true);
  gramInput.readOnly = true;
  portionSelect.disabled = true;
  amountControls.get(fields.amount).slider.disabled = true;
  saveDayFood.disabled = true;
  document.getElementById("cancelDayFood").disabled = true;
  document.getElementById("lookupMode").disabled = true;
  document.getElementById("manualMode").disabled = true;
  saveDayFood.textContent = "Saving…";
  setFoodStatus("");
  try {
    const data = await requestJson(submittedEditId === null ? "/api/day-food" : "/api/day-food/" + encodeURIComponent(submittedEditId), {
      method:submittedEditId === null ? "POST" : "PATCH",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({day:DAY, ...values})
    });
    if (submittedEditId === null) dayFoods.push(data.entry);
    else dayFoods = dayFoods.map(entry => entry.id === submittedEditId ? data.entry : entry);
    updateDayFoods(data);
    resetEditor();
    dayFoodForm.hidden = submittedEditId !== null || document.getElementById("manualMode").getAttribute("aria-pressed") !== "true";
    setFoodStatus(values.name + (submittedEditId === null ? " saved to " : " updated for ") + DAY + ".");
    refreshCustomFoodHistory();
  } catch (error) {
    setFoodStatus(error instanceof TypeError ? "Could not save this food. Check your connection and try again." : error.message, true);
  } finally {
    savingFood = false;
    Object.values(fields).forEach(field => field.readOnly = false);
    gramInput.readOnly = false;
    portionSelect.disabled = false;
    amountControls.get(fields.amount).slider.disabled = false;
    saveDayFood.disabled = false;
    document.getElementById("cancelDayFood").disabled = false;
    document.getElementById("lookupMode").disabled = false;
    document.getElementById("manualMode").disabled = false;
    saveDayFood.textContent = editingFoodId === null ? "Save to "+DAY : "Save changes";
    renderDayFoods();
    renderCustomFoodHistory();
  }
});
renderDayFoods();
renderTotals();

function applyDayEditingState() {
  const blocked = DAY_LOCKED || dayLockChanging;
  inputs.forEach(input => input.disabled = blocked);
  document.querySelectorAll(".foodrow .amount-range, #dayFoodPanel input:not(.history-query), #dayFoodPanel button:not(.history-remove), #dayFoodPanel select, #dayFoodPanel textarea")
    .forEach(control => control.disabled = blocked);
  document.getElementById("resetDayButton").disabled = blocked;
  document.getElementById("riceSalted").disabled = blocked || resettingSaltRatios;
  ["saltVariableMode", "riceRatioInput", "riceRatioSlider", "mealRatioInput", "mealRatioSlider"].forEach(id => {
    const control = document.getElementById(id);
    if (control) control.disabled = blocked || variableSaltSaving || resettingSaltRatios;
  });
  ["saltPercentInput", "saltPercentSlider"].forEach(id => {
    const control = document.getElementById(id);
    if (control) control.disabled = blocked || saltPercentSaving || resettingSaltRatios;
  });
  syncSaltBoxUI();
  renderCustomFoodHistory();
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
  flushAmountSaves();
  dayLockChanging = true;
  dayLockButton.disabled = true;
  dayLockButton.textContent = DAY_LOCKED ? "Unlocking..." : "Locking...";
  invalidateLookup();
  applyDayEditingState();
  let reloading = false;
  try {
    // Finish all queued slider/checkbox releases before capturing the day.
    await Promise.allSettled(inputs.map(input => saveChains.get(input)).filter(Boolean));
    await riceSavePromise;
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

const riceSaltedControl = document.getElementById("riceSalted");
riceSaltedControl.addEventListener("change", () => {
  if (DAY_LOCKED || dayLockChanging || riceSaltedControl.disabled) return;
  const salted = riceSaltedControl.checked;
  renderSaltSpins();
  riceSaltedControl.disabled = true;
  pendingSaves++;
  showSaveStatus();
  const previousSaltSave = riceSavePromise;
  riceSavePromise = (async () => {
    await previousSaltSave;
    try {
      await requestJson("/api/day-salt", {
        method:"PATCH", keepalive:true, headers:{"Content-Type":"application/json"},
        body:JSON.stringify({day:DAY, rice_salted:salted})
      });
      saveErrors.delete(riceSaltedControl);
    } catch (error) {
      riceSaltedControl.checked = !salted;
      saveErrors.add(riceSaltedControl);
      renderSaltSpins();
    } finally {
      pendingSaves--;
      showSaveStatus();
      riceSaltedControl.disabled = DAY_LOCKED || dayLockChanging;
      syncSaltBoxUI();
    }
  })();
});

function previewSaltPercentage(source) {
  const percent = Number(source.value);
  const valid = source.value.trim() !== "" && Number.isFinite(percent) && percent >= 0.01 && percent <= 2;
  const exact = document.getElementById("saltPercentInput");
  exact?.setCustomValidity(valid ? "" : "Enter a salt percentage between 0.01 and 2.");
  if (!valid) return false;
  SALT_GRAMS_PER_SPIN = SHAKER_CALIBRATION.salt_g_per_spin * 100 / percent;
  if (source.id === "saltPercentSlider" && exact) exact.value = source.value;
  const slider = document.getElementById("saltPercentSlider");
  if (slider) slider.value = String(percent);
  renderSaltSpins();
  return true;
}
function saveSaltPercentage() {
  const exact = document.getElementById("saltPercentInput");
  if (!exact || DAY_LOCKED || dayLockChanging || saltPercentSaving || resettingSaltRatios) return;
  if (!previewSaltPercentage(exact)) {
    saveErrors.add(exact);
    showSaveStatus();
    exact.reportValidity();
    return;
  }
  const percent = Number(exact.value);
  if (Math.abs(percent - confirmedSaltPercent) < 1e-7 && !saveErrors.has(exact)) return;
  saltPercentSaving = true;
  pendingSaves++;
  showSaveStatus();
  ["saltPercentInput", "saltPercentSlider"].forEach(id => {
    const control = document.getElementById(id);
    if (control) control.disabled = true;
  });
  const previousSaltSave = riceSavePromise;
  riceSavePromise = previousSaltSave.then(async () => {
    try {
      await requestJson("/api/day-salt", {
        method:"PATCH", keepalive:true, headers:{"Content-Type":"application/json"},
        body:JSON.stringify({day:DAY, salt_percent:percent})
      });
      confirmedSaltPercent = percent;
      saveErrors.delete(exact);
    } catch (error) {
      saveErrors.add(exact);
      SALT_GRAMS_PER_SPIN = SHAKER_CALIBRATION.salt_g_per_spin * 100 / confirmedSaltPercent;
      exact.value = String(confirmedSaltPercent);
      const slider = document.getElementById("saltPercentSlider");
      if (slider) slider.value = String(confirmedSaltPercent);
      renderSaltSpins();
    } finally {
      pendingSaves--;
      saltPercentSaving = false;
      showSaveStatus();
      ["saltPercentInput", "saltPercentSlider"].forEach(id => {
        const control = document.getElementById(id);
        if (control) control.disabled = DAY_LOCKED || dayLockChanging;
      });
      syncSaltBoxUI();
    }
  });
}
["saltPercentInput", "saltPercentSlider"].forEach(id => {
  const control = document.getElementById(id);
  control?.addEventListener("input", () => {
    if (!DAY_LOCKED && !dayLockChanging && !saltPercentSaving && !resettingSaltRatios) previewSaltPercentage(control);
  });
  control?.addEventListener("change", saveSaltPercentage);
  control?.addEventListener("blur", saveSaltPercentage);
  control?.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); saveSaltPercentage(); }
  });
});

const variableControlIds = ["saltVariableMode", "riceRatioInput", "riceRatioSlider", "mealRatioInput", "mealRatioSlider"];
function variableSettingsFromControls() {
  return {
    salt_mode:variableSaltMode() ? "variable" : "shared",
    rice_salt_per_185:variableRatioValue("riceRatioInput", 3),
    meal_salt_percent:variableRatioValue("mealRatioInput", 0.5)
  };
}
let confirmedVariableSettings = variableSettingsFromControls();
function syncVariableSettings(settings) {
  const mode = document.getElementById("saltVariableMode");
  if (mode) mode.checked = settings.salt_mode === "variable";
  for (const [prefix, value] of [["rice", settings.rice_salt_per_185], ["meal", settings.meal_salt_percent]]) {
    for (const suffix of ["Input", "Slider"]) {
      const control = document.getElementById(prefix + "Ratio" + suffix);
      if (control) { control.value = String(value); control.dataset.validValue = String(value); }
    }
  }
}
function saveVariableSettings(control) {
  if (DAY_LOCKED || dayLockChanging || variableSaltSaving || resettingSaltRatios) return;
  const settings = variableSettingsFromControls();
  if (JSON.stringify(settings) === JSON.stringify(confirmedVariableSettings) && !saveErrors.has(control)) return;
  variableSaltSaving = true;
  pendingSaves++;
  showSaveStatus();
  variableControlIds.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = true; });
  syncSaltBoxUI();
  const previous = riceSavePromise;
  riceSavePromise = previous.then(async () => {
    try {
      await requestJson("/api/day-salt", {
        method:"PATCH", keepalive:true, headers:{"Content-Type":"application/json"},
        body:JSON.stringify({day:DAY, ...settings})
      });
      confirmedVariableSettings = settings;
      variableControlIds.forEach(id => saveErrors.delete(document.getElementById(id)));
    } catch (error) {
      saveErrors.add(control);
      syncVariableSettings(confirmedVariableSettings);
      renderSaltSpins();
    } finally {
      variableSaltSaving = false;
      pendingSaves--;
      showSaveStatus();
      variableControlIds.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = DAY_LOCKED || dayLockChanging; });
      syncSaltBoxUI();
    }
  });
}
const variableModeControl = document.getElementById("saltVariableMode");
variableModeControl?.addEventListener("change", () => {
  if (DAY_LOCKED || dayLockChanging || variableSaltSaving || resettingSaltRatios) return;
  renderSaltSpins();
  saveVariableSettings(variableModeControl);
});
for (const [prefix, maximum] of [["rice", 10], ["meal", 2]]) {
  const exact = document.getElementById(prefix + "RatioInput");
  const slider = document.getElementById(prefix + "RatioSlider");
  function preview(source) {
    if (!exact || DAY_LOCKED || dayLockChanging || variableSaltSaving || resettingSaltRatios) return false;
    const value = Number(source.value);
    const valid = source.value.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= maximum;
    exact.setCustomValidity(valid ? "" : "Enter a value from 0 to " + maximum + ".");
    if (!valid) return false;
    if (source === slider) exact.value = source.value;
    exact.dataset.validValue = String(value);
    if (slider) slider.value = String(value);
    renderSaltSpins();
    return true;
  }
  function commit(source) {
    if (preview(source)) saveVariableSettings(exact);
    else if (exact && !DAY_LOCKED && !dayLockChanging && !variableSaltSaving && !resettingSaltRatios) {
      saveErrors.add(exact); showSaveStatus(); exact.reportValidity();
    }
  }
  for (const source of [exact, slider].filter(Boolean)) {
    source.addEventListener("input", () => preview(source));
    source.addEventListener("change", () => commit(source));
    source.addEventListener("blur", () => commit(source));
    source.addEventListener("keydown", event => {
      if (event.key === "Enter") { event.preventDefault(); commit(source); }
    });
  }
}

function syncSaltBoxUI() {
  if (resettingSaltRatios) {
    for (const id of ["riceSalted", "saltVariableMode", "saltPercentInput", "saltPercentSlider",
        "riceRatioInput", "riceRatioSlider", "mealRatioInput", "mealRatioSlider"]) {
      const control = document.getElementById(id);
      if (control) control.disabled = true;
    }
  }
  syncSaltChoiceSelection();
  const reset = document.getElementById("resetSaltRatios");
  if (reset) {
    reset.disabled = DAY_LOCKED || dayLockChanging || resettingSaltRatios;
    reset.textContent = resettingSaltRatios ? "Resetting..." : "Reset ratios";
  }
}
for (const [id, variable] of [["sharedSaltMode", false], ["variableSaltMode", true]]) {
  document.getElementById(id)?.addEventListener("click", () => {
    const backing = document.getElementById("saltVariableMode");
    if (!backing || backing.disabled || backing.checked === variable || resettingSaltRatios) return;
    backing.checked = variable;
    backing.dispatchEvent(new Event("change", {bubbles:true}));
  });
}
document.getElementById("ricePreparation")?.addEventListener("change", event => {
  const backing = document.getElementById("riceSalted");
  if (!backing || backing.disabled || resettingSaltRatios) return;
  backing.checked = event.target.value === "salted";
  backing.dispatchEvent(new Event("change", {bubbles:true}));
});
document.getElementById("resetSaltRatios")?.addEventListener("click", () => {
  if (DAY_LOCKED || dayLockChanging || resettingSaltRatios) return;
  const reset = document.getElementById("resetSaltRatios");
  resettingSaltRatios = true;
  pendingSaves++;
  showSaveStatus();
  applyDayEditingState();
  riceSavePromise = riceSavePromise.then(async () => {
    try {
      const data = await requestJson("/api/day-salt", {
        method:"PATCH", keepalive:true, headers:{"Content-Type":"application/json"},
        body:JSON.stringify({day:DAY, reset_ratios:true})
      });
      confirmedSaltPercent = data.salt_percent;
      SALT_GRAMS_PER_SPIN = SHAKER_CALIBRATION.salt_g_per_spin * 100 / confirmedSaltPercent;
      for (const id of ["saltPercentInput", "saltPercentSlider"]) {
        const control = document.getElementById(id);
        if (control) { control.value = String(confirmedSaltPercent); control.setCustomValidity?.(""); }
      }
      confirmedVariableSettings = {salt_mode:data.salt_mode,
        rice_salt_per_185:data.rice_salt_per_185, meal_salt_percent:data.meal_salt_percent};
      syncVariableSettings(confirmedVariableSettings);
      for (const id of ["resetSaltRatios", "saltPercentInput", "saltPercentSlider", ...variableControlIds]) {
        const control = document.getElementById(id);
        control?.setCustomValidity?.("");
        saveErrors.delete(control);
      }
      renderSaltSpins();
    } catch (error) {
      saveErrors.add(reset);
    } finally {
      resettingSaltRatios = false;
      pendingSaves--;
      applyDayEditingState();
      showSaveStatus();
    }
  });
});
syncSaltBoxUI();

// This is an independent calculator: it does not modify food entries or locks.
const seasoningToggle = document.getElementById("seasoningToggle");
const seasoningPanel = document.getElementById("seasoningPanel");
seasoningToggle.addEventListener("click", () => {
  seasoningPanel.hidden = !seasoningPanel.hidden;
  seasoningToggle.setAttribute("aria-expanded", String(!seasoningPanel.hidden));
  if (!seasoningPanel.hidden) renderSeasoningCalculator();
});
["seasoningServing", "seasoningSodium", "riceSeasoningServing", "riceSeasoningSodium",
 "bowlSeasoningServing", "bowlSeasoningSodium"].forEach(id =>
  document.getElementById(id)?.addEventListener("input", () => renderSeasoningCalculator()));

["riceSeasoning", "bowlSeasoning"].forEach(id =>
  document.getElementById(id)?.addEventListener("toggle", () => renderSeasoningCalculator()));

refreshCustomFoodHistory();
