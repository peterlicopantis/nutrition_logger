/* Phone camera and photo scanning. Images stay in this browser; only barcode digits
 * go to the existing food lookup. OCR assets are bundled and loaded on demand. */
(() => {
  "use strict";
  const panel = document.getElementById("foodScanPanel");
  if (!panel) return;
  const barcodeButton = document.getElementById("scanBarcodeButton");
  const labelButton = document.getElementById("scanLabelButton");
  const barcodePhoto = document.getElementById("barcodePhoto");
  const labelPhoto = document.getElementById("nutritionLabelPhoto");
  const cancelButton = document.getElementById("cancelFoodScan");
  const photoBarcodeButton = document.getElementById("photoBarcodeButton");
  const photoLabelButton = document.getElementById("photoLabelButton");
  const livePanel = document.getElementById("foodLiveCamera");
  const captureButton = document.getElementById("captureFoodNow");
  const video = document.getElementById("foodCameraVideo");
  const status = document.getElementById("foodScanStatus");
  const textPanel = document.getElementById("foodScanText");
  const rawText = document.getElementById("foodScanRawText");
  const assets = new URL(panel.dataset.assets, location.href);
  const scripts = new Map();
  let generation = 0;
  let busy = false;
  let mode = null;
  let controller = null;
  let deadline = null;
  let workerPromise = null;
  let worker = null;
  let camera = null;
  let live = false;

  function blocked() { return DAY_LOCKED || dayLockChanging || savingFood; }
  function current(token) { return token === generation && busy && !blocked(); }
  function message(text, error=false) {
    status.textContent = text;
    status.hidden = !text;
    status.classList.toggle("food-error", error);
  }
  function syncButtons() {
    if (blocked() && busy) { cancel(); return; }
    [barcodeButton, labelButton, photoBarcodeButton, photoLabelButton, barcodePhoto, labelPhoto]
      .forEach(element => element.disabled = busy || blocked());
    captureButton.disabled = !live || blocked();
    cancelButton.hidden = !busy;
    cancelButton.disabled = blocked();
    panel.setAttribute("aria-busy", String(busy));
  }
  function releaseWorker() {
    const previous = worker;
    worker = null;
    workerPromise = null;
    if (previous) Promise.resolve(previous.terminate()).catch(() => {});
  }
  function cancel(showMessage=false) {
    const wasBusy = busy;
    camera?.stop();
    camera = null;
    live = false;
    livePanel.hidden = true;
    generation++;
    busy = false;
    mode = null;
    controller?.abort();
    controller = null;
    clearTimeout(deadline);
    deadline = null;
    if (wasBusy) releaseWorker();
    syncButtons();
    if (wasBusy) message(showMessage ? "Scan canceled. You can try again." : "");
  }
  function loadScript(filename, globalName) {
    if (window[globalName]) return Promise.resolve(window[globalName]);
    if (scripts.has(filename)) return scripts.get(filename);
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        script.onload = script.onerror = null;
        if (error) {
          scripts.delete(filename);
          script.remove();
          reject(new Error("Couldn't load the scanner. Check the connection to your PC and try again."));
        } else resolve(window[globalName]);
      };
      const timeout = setTimeout(() => finish(true), 20000);
      script.src = new URL(filename, assets).href;
      script.async = true;
      script.onload = () => finish(!window[globalName]);
      script.onerror = () => finish(true);
      document.head.appendChild(script);
    });
    scripts.set(filename, promise);
    return promise;
  }
  async function photoCanvas(file, token) {
    if (!file || !file.type.startsWith("image/")) throw new Error("Choose a photo of the barcode or nutrition label.");
    if (file.size > 25 * 1024 * 1024) throw new Error("That photo is too large. Take another photo under 25 MB.");
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      try { await image.decode(); }
      catch (_) { throw new Error("Couldn't read this image. Try a new camera photo or a JPEG/PNG image."); }
      if (!current(token)) return null;
      const ratio = Math.min(1, 2400 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
      const context = canvas.getContext("2d");
      context.fillStyle = "white";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      return canvas;
    } finally { URL.revokeObjectURL(url); }
  }
  function barcodeDigits(value) {
    const text = String(value || "").trim();
    return /^[0-9]{8,14}$/.test(text) ? text : null;
  }
  async function decodeBarcode(canvas, token, quiet=false) {
    // Use a native decoder when provided, with ZXing as the portable fallback.
    if (window.BarcodeDetector) {
      try {
        const formats = (await BarcodeDetector.getSupportedFormats()).filter(format =>
          ["ean_13", "ean_8", "upc_a", "upc_e", "itf"].includes(format));
        if (formats.length) {
          const hits = await new BarcodeDetector({formats}).detect(canvas);
          const code = hits.map(hit => barcodeDigits(hit.rawValue)).find(Boolean);
          if (code) return code;
        }
      } catch (_) { /* Fall back to the bundled decoder. */ }
    }
    if (!current(token)) return null;
    const library = await loadScript("zxing-browser.min.js", "ZXingBrowser");
    if (!current(token)) return null;
    const reader = new library.BrowserMultiFormatReader();
    // A portrait camera photo can contain a sideways barcode.
    for (const rotate of [false, true]) {
      if (!current(token)) return null;
      const image = rotate ? document.createElement("canvas") : canvas;
      if (rotate) {
        image.width = canvas.height;
        image.height = canvas.width;
        const context = image.getContext("2d");
        context.translate(image.width, 0);
        context.rotate(Math.PI / 2);
        context.drawImage(canvas, 0, 0);
      }
      try {
        const result = await reader.decodeFromCanvas(image);
        const code = barcodeDigits(result.getText());
        if (code) return code;
      } catch (_) { /* Try the other orientation, then offer a retake. */ }
      // Give the cancel button a chance to run between decoding attempts.
      await new Promise(resolve => setTimeout(resolve, 0));
    }
    if (quiet) return null;
    throw new Error("Couldn't read a product barcode. Retake a sharp photo with the whole barcode in frame, or type its numbers in food search.");
  }
  async function getWorker() {
    if (!workerPromise) {
      const pending = loadScript("tesseract.min.js", "Tesseract").then(library => {
        if (workerPromise !== pending) throw new DOMException("Scan canceled.", "AbortError");
        return library.createWorker("eng", 1, {
          workerPath:new URL("worker.min.js", assets).href,
          corePath:new URL("core/", assets).href,
          langPath:new URL("lang/", assets).href,
          workerBlobURL:false,
          legacyCore:false,
          legacyLang:false,
          logger:event => {
            if (!busy || mode !== "label") return;
            if (event.status === "recognizing text") {
              message("Reading nutrition label... " + Math.round((event.progress || 0) * 100) + "%");
            } else message("Preparing label reader... The first scan can take a little longer.");
          }
        });
      }).then(result => {
        if (workerPromise !== pending) {
          Promise.resolve(result.terminate()).catch(() => {});
          throw new DOMException("Scan canceled.", "AbortError");
        }
        worker = result;
        return result;
      }).catch(error => {
        if (workerPromise === pending) workerPromise = null;
        throw error;
      });
      workerPromise = pending;
    }
    return workerPromise;
  }
  function recognizeLabel(reader, canvas) {
    // Small uploaded labels need enough pixels for units such as "21g".
    let image = canvas;
    const scale = Math.min(3, 900 / canvas.width, 2400 / Math.max(canvas.width, canvas.height));
    if (scale > 1) {
      image = document.createElement("canvas");
      image.width = Math.round(canvas.width * scale);
      image.height = Math.round(canvas.height * scale);
      image.getContext("2d").drawImage(canvas, 0, 0, image.width, image.height);
    }
    return reader.recognize(image, {tessedit_pageseg_mode:"11"}, {text:true, blocks:true});
  }
  async function readLabel(canvas, token) {
    const reader = await getWorker();
    if (!current(token)) return;
    const result = await recognizeLabel(reader, canvas);
    if (!current(token)) return;
    showLabelReading(result.data, token);
  }
  function showLabelReading(data, token) {
    if (!current(token)) return;
    const text = String(data?.text || "").trim();
    if (!text) throw new Error("No text was readable. Take a closer, sharper photo of just the Nutrition Facts panel.");
    const parsed = NutritionLabel.parse(data);
    const keys = ["calories", "protein", "carbs", "fat", "fiber"];
    const recognized = keys.filter(key => Number.isFinite(parsed[key]));
    loadManualFood({name:"", serving_label:parsed.serving_label || "1 serving",
      serving_g:parsed.serving_g, source_url:"", ...Object.fromEntries(keys.map(key => [key, parsed[key]]))});
    rawText.textContent = text;
    textPanel.hidden = false;
    textPanel.open = false;
    document.getElementById("dayFoodEditorHeading").textContent = "Review scanned nutrition label";
    document.getElementById("portionNote").textContent =
      "Check the serving weight and every number against the label. Add a food name and set grams eaten before saving. Unread values are left blank.";
    const warning = parsed.warnings?.length ? " " + parsed.warnings.join(" ") : "";
    message((recognized.length ? "Label read. Review the values, add a food name, and fill in any blanks before saving." :
      "The label text was read, but its nutrition couldn't be matched reliably. Enter the values below or retake a clearer photo.") + warning,
      recognized.length < 4 || Boolean(parsed.warnings?.length));
    fields.name.focus();
  }
  async function lookUpBarcode(code, token) {
    if (!current(token)) return;
    message("Barcode " + code + " found. Looking up its nutrition...");
    controller = new AbortController();
    const data = await requestJson("/api/food-lookup?q=" + encodeURIComponent(code), {signal:controller.signal});
    if (!current(token)) return;
    const products = Array.isArray(data.products) ? data.products : [];
    foodQuery.value = code;
    lookupInputValue = code;
    if (!products.length) {
      message("Barcode " + code + " isn't in the food database with complete nutrition. Try Read nutrition label or Enter macros.", true);
      return;
    }
    chooseMode(false);
    selectProduct(products[0], 1);
    document.getElementById("dayFoodPanel").open = true;
    message("Barcode matched. Check the brand, serving weight, and nutrition against your package, then set grams eaten and save.");
  }
  function finish(token) {
    if (token !== generation) return;
    camera?.stop();
    camera = null;
    live = false;
    livePanel.hidden = true;
    busy = false;
    mode = null;
    clearTimeout(deadline);
    deadline = null;
    controller = null;
    syncButtons();
  }
  function canUseLiveCamera() {
    return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.LiveFoodCamera);
  }
  async function startLive(nextMode) {
    if (busy || blocked()) return;
    if (!canUseLiveCamera()) {
      message("Live auto-scan needs the app's HTTPS address. Using photo capture for now.");
      takePhoto(nextMode === "barcode" ? barcodePhoto : labelPhoto);
      return;
    }
    cancel();
    invalidateLookup();
    textPanel.hidden = true;
    rawText.textContent = "";
    const token = generation;
    busy = true;
    live = true;
    mode = nextMode;
    const detector = LiveLabelDetector.create();
    // Load OCR while camera permission/preview starts, instead of waiting for
    // the first frame. A canceled scan invalidates and releases this worker.
    if (nextMode === "label") void getWorker().catch(() => {});
    livePanel.hidden = false;
    document.getElementById("foodCameraGuide").textContent = nextMode === "barcode" ?
      "Point at the whole barcode. It will capture automatically when readable." :
      "Keep the whole Nutrition Facts panel in view. Hold still for automatic capture, or tap Capture now.";
    message("Allow camera access to start automatic scanning.");
    syncButtons();
    deadline = setTimeout(() => {
      if (!current(token)) return;
      cancel();
      message("Scanning timed out. Try again with the barcode or Nutrition Facts panel closer and well lit.", true);
    }, 120000);
    camera = LiveFoodCamera.create({
      video,
      // Full-resolution reads give labels the same detail as Capture now.
      // Barcodes can still use the smaller, faster analysis canvas.
      fullResolution:nextMode === "label",
      isCurrent:() => current(token) && live,
      onStatus:text => { if (current(token)) message(text); },
      onFrame:async canvas => {
        if (!current(token)) return null;
        if (nextMode === "barcode") {
          const code = await decodeBarcode(canvas, token, true);
          if (code && current(token)) return {key:code, barcode:code};
          if (current(token)) message("Looking for a barcode... Keep it in view and hold still.");
          return null;
        }
        const reader = await getWorker();
        if (!current(token)) return null;
        const result = await recognizeLabel(reader, canvas);
        if (!current(token)) return null;
        const observed = detector.observe(result.data);
        message(observed.ready ? "Nutrition label read. Opening for review..." :
          observed.detected ? "Still reading " + (observed.missing.join(", ") || "the label") +
            ". Keep the whole label steady and well lit, or use Capture now." :
          "Looking for a readable Nutrition Facts panel... Move closer and keep the whole label in view.");
        return observed.ready ? {key:observed.key, label:true, ocrData:result.data} : null;
      },
      onCapture:async (canvas, detection) => {
        if (!current(token)) return;
        live = false;
        livePanel.hidden = true;
        syncButtons();
        message("Captured. Reading the food details...");
        try {
          if (nextMode === "barcode") {
            const code = detection?.barcode || await decodeBarcode(canvas, token);
            if (code && current(token)) await lookUpBarcode(code, token);
          } else if (detection?.label && detection.ocrData) {
            // This data belongs to the recognized still. Re-reading a later
            // frame adds delay and can throw away an already useful result.
            showLabelReading(detection.ocrData, token);
          } else await readLabel(canvas, token);
        } catch (error) {
          if (!current(token)) return;
          if (nextMode === "label") releaseWorker();
          message(error.message || "Couldn't read the capture. Try again or use a photo.", true);
        } finally { finish(token); }
      },
      onError:error => {
        if (!current(token)) return;
        cancel();
        message(error.message || "Couldn't open the camera. Use a photo instead.", true);
      }
    });
    await camera.start();
  }
  async function processPhoto(file, nextMode) {
    if (!file || blocked()) return;
    cancel();
    invalidateLookup();
    textPanel.hidden = true;
    rawText.textContent = "";
    const token = generation;
    busy = true;
    mode = nextMode;
    syncButtons();
    message(nextMode === "barcode" ? "Reading barcode photo..." : "Reading nutrition label photo...");
    deadline = setTimeout(() => {
      if (!current(token)) return;
      cancel();
      message(nextMode === "barcode" ? "Barcode lookup took too long. Try again or read the nutrition label." :
        "Label reading took too long. Try a closer photo of just the Nutrition Facts panel.", true);
    }, nextMode === "barcode" ? 30000 : 120000);
    try {
      const canvas = await photoCanvas(file, token);
      if (!canvas || !current(token)) return;
      if (nextMode === "barcode") {
        const code = await decodeBarcode(canvas, token);
        if (code && current(token)) await lookUpBarcode(code, token);
      } else await readLabel(canvas, token);
    } catch (error) {
      if (!current(token)) return;
      if (nextMode === "label") releaseWorker();
      message(error.message || "Couldn't read the photo. Try again or enter the values manually.", true);
    } finally {
      finish(token);
    }
  }
  function takePhoto(input) {
    if (busy || blocked()) return;
    // Keep the picker directly in the tap handler: iPhone requires user activation.
    input.value = "";
    input.click();
  }
  barcodeButton.addEventListener("click", () => startLive("barcode"));
  labelButton.addEventListener("click", () => startLive("label"));
  photoBarcodeButton.addEventListener("click", () => takePhoto(barcodePhoto));
  photoLabelButton.addEventListener("click", () => takePhoto(labelPhoto));
  captureButton.addEventListener("click", () => {
    if (live && current(generation)) camera?.capture();
  });
  barcodePhoto.addEventListener("change", () => processPhoto(barcodePhoto.files?.[0], "barcode"));
  labelPhoto.addEventListener("change", () => processPhoto(labelPhoto.files?.[0], "label"));
  cancelButton.addEventListener("click", () => cancel(true));

  // A later search/edit always wins over a slow photo scan. Do not cancel on
  // visibilitychange: opening the native iPhone camera can background the page.
  document.addEventListener("click", event => {
    if (event.target.closest("#lookupMode, #manualMode, #cancelDayFood, #dayLockButton, #resetDayButton, .edit-day-food, .use-history-food, #lookupResults button, #saveDayFood")) cancel();
  }, true);
  function cancelForEdit(event) {
    if (event.target.closest("#dayFoodForm, #foodQuery, #customFoodHistoryQuery")) cancel();
  }
  document.addEventListener("input", cancelForEdit, true);
  document.addEventListener("change", cancelForEdit, true);
  foodQuery.addEventListener("search", cancelForEdit);
  dayFoodForm.addEventListener("keydown", event => {
    if (event.target.matches(".amount-range")) cancel();
  }, true);
  document.addEventListener("submit", event => {
    if (event.target.matches("#lookupForm, #dayFoodForm")) cancel();
  }, true);
  document.getElementById("dayFoodPanel").addEventListener("toggle", event => {
    if (!event.target.open && busy) cancel();
  });
  new MutationObserver(syncButtons).observe(saveDayFood, {attributes:true, attributeFilter:["disabled"]});
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && live) cancel(true);
  });
  window.addEventListener("pagehide", () => { cancel(); releaseWorker(); });
  document.getElementById("liveCameraHint").hidden = canUseLiveCamera();
  syncButtons();
})();
