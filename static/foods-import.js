const importForm = document.getElementById("foodImportForm");
const backupInput = importForm.elements.backup;
const importStatus = document.getElementById("foodImportStatus");
const selectionPanel = document.getElementById("foodImportSelection");
const importChoices = document.getElementById("foodImportChoices");
const selectAllFoods = document.getElementById("selectAllImportFoods");
const importButton = document.getElementById("importSelectedFoods");
let previewController = null;
let previewGeneration = 0;
function selectedImportFoods() {
  return [...importChoices.querySelectorAll("input[type=checkbox]")];
}
function syncImportSelection() {
  const choices = selectedImportFoods();
  const count = choices.filter(input => input.checked).length;
  selectAllFoods.checked = choices.length > 0 && count === choices.length;
  selectAllFoods.indeterminate = count > 0 && count < choices.length;
  selectAllFoods.disabled = !choices.length;
  importButton.disabled = !count;
  importButton.textContent = "Import "+count+" selected food"+(count === 1 ? "" : "s");
  importStatus.textContent = count+" of "+choices.length+" foods selected.";
}
selectAllFoods.addEventListener("change", () => {
  selectedImportFoods().forEach(input => input.checked = selectAllFoods.checked);
  syncImportSelection();
});
backupInput.addEventListener("change", async () => {
  const generation = ++previewGeneration;
  previewController?.abort();
  previewController = null;
  importForm.dataset.previewPending = "false";
  importForm.elements.selection_present.value = "0";
  selectionPanel.hidden = true;
  importChoices.replaceChildren();
  importButton.disabled = true;
  importButton.textContent = "Import selected foods";
  importStatus.classList.remove("food-error");
  const file = backupInput.files[0];
  if (!file) {
    importStatus.textContent = "Choose a backup to preview its foods.";
    return;
  }
  if (file.size > 1000000) {
    importStatus.textContent = "The food backup must be smaller than 1 MB.";
    importStatus.classList.add("food-error");
    return;
  }
  importStatus.textContent = "Checking backup...";
  importForm.dataset.previewPending = "true";
  const controller = new AbortController();
  previewController = controller;
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(importForm.dataset.previewUrl, {
      method:"POST", body:new FormData(importForm), signal:controller.signal
    });
    const data = await response.json();
    if (generation !== previewGeneration) return;
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not preview this backup.");
    for (const food of data.foods) {
      const label = document.createElement("label");
      label.className = "import-food-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "selected_food";
      checkbox.value = food.name;
      checkbox.checked = true;
      checkbox.addEventListener("change", syncImportSelection);
      const text = document.createElement("span");
      text.textContent = food.name;
      const details = document.createElement("small");
      details.textContent = food.category+" - "+(food.exists ? "updates existing food" : "new food")+
        (food.category === "Dawg Bowl" && food.salt_extra_weight_factor > 0 ?
          " - "+(1 + food.salt_extra_weight_factor)+"x salt weight" : "");
      text.appendChild(details);
      label.append(checkbox, text);
      importChoices.appendChild(label);
    }
    selectionPanel.hidden = false;
    importForm.elements.selection_present.value = "1";
    syncImportSelection();
    if (!data.foods.length) importStatus.textContent = "This backup contains no foods to import.";
  } catch (error) {
    if (generation !== previewGeneration) return;
    importStatus.classList.add("food-error");
    importStatus.textContent = error.name === "AbortError" ?
      "Backup preview took too long. Choose the file again to retry." :
      error instanceof TypeError ? "Could not connect. Choose the file again to retry." : error.message;
  } finally {
    clearTimeout(timeout);
    if (generation === previewGeneration) {
      importForm.dataset.previewPending = "false";
      previewController = null;
    }
  }
});
importForm.addEventListener("submit", event => {
  const count = selectedImportFoods().filter(input => input.checked).length;
  if (importForm.elements.selection_present.value !== "1" || count === 0) {
    event.preventDefault();
    importStatus.textContent = "Select at least one food to import.";
    return;
  }
  if (importForm.elements.mode.value === "replace" &&
      !confirm("Replace the entire food library with the "+count+" selected foods? An automatic backup will be saved first.")) {
    event.preventDefault();
  }
});
