/* Bounded live camera frames. Recognition and food lookup belong to food_scanner.js. */
(() => {
  "use strict";
  const FRAME_INTERVAL_MS = 700;
  const FRAME_MAX_SIZE = 1600;
  const CAPTURE_MAX_SIZE = 2400;

  function create(options) {
    const {video, onFrame=async () => null, onCapture=async () => {},
      onStatus=() => {}, onError=() => {}, isCurrent=() => true, fullResolution=false} = options;
    let generation = 0;
    let active = false;
    let captured = false;
    let stream = null;
    let timer = null;
    let starting = null;
    let startingToken = null;
    let frameWork = null;
    let endedListeners = [];

    function current(token) {
      return token === generation && !document.hidden && isCurrent();
    }
    function stopTracks(value) {
      for (const track of value?.getTracks() || []) {
        try { track.stop(); } catch (_) { /* Other tracks must still be released. */ }
      }
    }
    function release() {
      active = false;
      clearTimeout(timer);
      timer = null;
      for (const [track, listener] of endedListeners) track.removeEventListener?.("ended", listener);
      endedListeners = [];
      const previous = stream;
      stream = null;
      if (video.srcObject === previous) {
        try { video.pause(); } catch (_) { /* An unstarted preview has nothing to pause. */ }
        video.srcObject = null;
      }
      stopTracks(previous);
      document.removeEventListener("visibilitychange", visibilityChanged);
      window.removeEventListener("pagehide", stop);
    }
    function stop() {
      generation++;
      release();
    }
    function visibilityChanged() {
      if (document.hidden) stop();
    }
    function friendlyError(error) {
      const name = error?.name || "";
      const descriptions = {
        NotAllowedError:"Camera access was denied. Allow camera access in your browser, or use Take photo.",
        SecurityError:"Camera access is blocked. Use your secure HTTPS address, or use Take photo.",
        NotFoundError:"No camera was found. You can use Take photo instead.",
        DevicesNotFoundError:"No camera was found. You can use Take photo instead.",
        NotReadableError:"The camera is busy. Close other camera apps and try again, or use Take photo.",
        TrackStartError:"The camera is busy. Close other camera apps and try again, or use Take photo.",
        OverconstrainedError:"Couldn't start this camera. Try Take photo instead."
      };
      return new Error(descriptions[name] || error?.message || "Couldn't start the camera. Try Take photo instead.");
    }
    function fail(error, token) {
      if (token !== generation) return;
      const notify = current(token);
      release();
      if (notify) onError(friendlyError(error));
    }
    function snapshot(maxSize) {
      const width = video.videoWidth;
      const height = video.videoHeight;
      if (video.readyState < 2 || !(width > 0) || !(height > 0)) return null;
      const scale = Math.min(1, maxSize / Math.max(width, height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Couldn't capture this camera frame. Try Take photo instead.");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      return canvas;
    }
    function previewOf(still) {
      if (fullResolution) return still;
      const scale = Math.min(1, FRAME_MAX_SIZE / Math.max(still.width, still.height));
      if (scale === 1) return still;
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(still.width * scale));
      canvas.height = Math.max(1, Math.round(still.height * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Couldn't prepare this camera frame. Try a photo instead.");
      context.drawImage(still, 0, 0, canvas.width, canvas.height);
      return canvas;
    }
    async function capture(detection=null, recognizedStill=null) {
      const token = generation;
      if (!active || captured || !current(token)) return false;
      let canvas;
      try { canvas = recognizedStill || snapshot(CAPTURE_MAX_SIZE); }
      catch (error) { fail(error, token); return false; }
      if (!canvas) {
        onStatus("The camera is still starting. Hold steady and try again.");
        return false;
      }
      captured = true;
      const pendingFrame = frameWork;
      // Stop the camera immediately, even when recognition still owns the worker.
      release();
      if (pendingFrame) {
        try { await pendingFrame; } catch (_) { /* The saved still can be read again. */ }
      }
      if (!current(token)) return false;
      try {
        await onCapture(canvas, detection);
        return true;
      } catch (error) {
        fail(error, token);
        return false;
      }
    }
    function schedule(token) {
      if (!active || !current(token)) return;
      timer = setTimeout(() => { timer = null; void nextFrame(token); }, FRAME_INTERVAL_MS);
    }
    async function nextFrame(token) {
      if (!active || !current(token)) {
        if (token === generation) stop();
        return;
      }
      try {
        // A restart can happen before a canceled recognition job has settled.
        if (frameWork) {
          try { await frameWork; } catch (_) { /* Ignore the old scan result. */ }
          if (!active || !current(token)) {
            if (token === generation && active) stop();
            return;
          }
        }
        const still = snapshot(CAPTURE_MAX_SIZE);
        if (!still) { schedule(token); return; }
        const canvas = previewOf(still);
        // Keep the still from BEFORE recognition. A later live frame may have
        // moved or blurred while OCR was working; it must not replace this one.
        const work = Promise.resolve().then(() => onFrame(canvas));
        frameWork = work;
        let detection;
        try { detection = await work; }
        finally { if (frameWork === work) frameWork = null; }
        if (!active || !current(token)) {
          if (token === generation && !captured) stop();
          return;
        }
        if (detection) await capture(detection, still);
        else schedule(token);
      } catch (error) { fail(error, token); }
    }
    async function begin(token) {
      let acquired = null;
      try {
        if (!current(token)) return false;
        if (!window.isSecureContext) {
          throw new Error("Live scanning needs HTTPS. Open your secure address, or use Take photo.");
        }
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("This browser doesn't support live camera scanning. Use Take photo instead.");
        }
        document.addEventListener("visibilitychange", visibilityChanged);
        window.addEventListener("pagehide", stop);
        onStatus("Requesting camera access...");
        acquired = await navigator.mediaDevices.getUserMedia({
          audio:false,
          video:{facingMode:{ideal:"environment"}, width:{ideal:1920}, height:{ideal:1080}}
        });
        if (!current(token)) {
          stopTracks(acquired);
          if (token === generation) release();
          return false;
        }
        stream = acquired;
        video.playsInline = true;
        video.muted = true;
        video.srcObject = acquired;
        for (const track of acquired.getVideoTracks()) {
          const listener = () => fail(new Error("The camera stopped. Try scanning again or use Take photo."), token);
          track.addEventListener?.("ended", listener);
          endedListeners.push([track, listener]);
        }
        await video.play();
        if (!current(token) || document.hidden) {
          if (stream === acquired) release();
          else stopTracks(acquired);
          return false;
        }
        active = true;
        onStatus("Camera ready. Hold the barcode or nutrition label steady.");
        // Schedule after startup so the caller can show the preview first.
        schedule(token);
        return true;
      } catch (error) {
        if (stream !== acquired) stopTracks(acquired);
        fail(error, token);
        return false;
      }
    }
    function start() {
      if (active && current(generation)) return Promise.resolve(true);
      if (starting && startingToken === generation) return starting;
      release();
      const token = ++generation;
      captured = false;
      startingToken = token;
      const pending = begin(token);
      starting = pending;
      void pending.then(() => {
        if (starting === pending) { starting = null; startingToken = null; }
      });
      return pending;
    }
    return {start, stop, capture:() => capture(null)};
  }
  window.LiveFoodCamera = Object.freeze({create});
})();
