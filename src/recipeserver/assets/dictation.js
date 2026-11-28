// Shared dictation transport: microphone capabilities, MediaRecorder lifecycle
// and the /api/transcribe call. The two triggers (search-field button and the
// assistant bubble/inline mic) keep their own UI and pointer wiring.

(function () {
  "use strict";

  const TRANSCRIBE_URL = "/api/transcribe";
  const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  const LONG_PRESS_MS = 450;
  const MOVE_TOLERANCE_PX = 10;
  const COMPLETE_STATE_MS = 1500;
  const ERROR_STATE_MS = 2500;

  function isSecurePage() {
    return window.location?.protocol === "https:";
  }

  function canRecord() {
    return Boolean(window.MediaRecorder) && Boolean(navigator.mediaDevices?.getUserMedia);
  }

  function supportedMimeType() {
    if (!window.MediaRecorder) return "";
    return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function createRecorder({ onStop, onError } = {}) {
    let stream = null;
    let recorder = null;
    let chunks = [];
    let cancelled = false;

    function cleanup() {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      recorder = null;
      chunks = [];
    }

    return {
      isRecording() {
        return Boolean(recorder && recorder.state === "recording");
      },
      cancel() {
        cancelled = true;
        cleanup();
      },
      async start() {
        cancelled = false;
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (cancelled) {
            cleanup();
            return false;
          }

          const mimeType = supportedMimeType();
          recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
          chunks = [];

          recorder.ondataavailable = (event) => {
            if (event.data.size > 0) chunks.push(event.data);
          };
          recorder.onstop = () => {
            const blob = new Blob(chunks, { type: recorder?.mimeType || chunks[0]?.type || "" });
            cleanup();
            onStop?.(blob);
          };
          recorder.onerror = (event) => {
            console.error("Recording error:", event.error);
            cleanup();
            onError?.(event);
          };

          recorder.start();
          return true;
        } catch (error) {
          console.error("Unable to start recording:", error);
          cleanup();
          onError?.(error);
          return false;
        }
      },
      stop() {
        if (recorder?.state === "recording") recorder.stop();
      },
    };
  }

  async function transcribe(blob, { stripTrailingPeriod = false } = {}) {
    if (!blob || !blob.size) throw new Error("Nothing was heard. Try again.");

    const result = await window.RecipeApi.requestJson(TRANSCRIBE_URL, {
      method: "POST",
      headers: { "Content-Type": blob.type || "application/octet-stream" },
      body: blob,
      fallbackMessage: "Transcription failed",
    });

    let text = String(result?.text || "").trim();
    if (stripTrailingPeriod) text = text.replace(/\.+$/, "");
    if (!text) throw new Error("Nothing was heard. Try again.");
    return text;
  }

  window.RecipeDictation = {
    isSecurePage,
    canRecord,
    supportedMimeType,
    createRecorder,
    transcribe,
    LONG_PRESS_MS,
    MOVE_TOLERANCE_PX,
    COMPLETE_STATE_MS,
    ERROR_STATE_MS,
  };
})();
