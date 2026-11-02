(() => {
  const SELECTOR = ".speech-input";
  const BUTTON_SELECTOR = ".speech-button";

  const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

  function getSupportedMimeType() {
    if (!window.MediaRecorder) {
      return "";
    }

    return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function initializeSpeechInput(wrapper) {
    const input = wrapper.querySelector("input, textarea");
    const button = wrapper.querySelector(BUTTON_SELECTOR);

    if (!input || !button || button.dataset.initialized) {
      return;
    }

    button.dataset.initialized = "true";

    const icon = button.querySelector(".speech-button__icon");

    if (!icon || !window.MediaRecorder) {
      button.hidden = true;
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      button.disabled = true;
      button.title = "Microphone access requires HTTPS";
      button.setAttribute("aria-label", "Microphone access requires HTTPS");
      return;
    }

    let recorder = null;
    let stream = null;
    let chunks = [];
    let recording = false;
    let originalValue = "";
    let originalSelectionStart = 0;
    let originalSelectionEnd = 0;

    function setState(state) {
      button.dataset.state = state;

      button.classList.toggle("is-recording", state === "recording");
      button.classList.toggle("is-complete", state === "complete");
      button.classList.toggle("is-transcribing", state === "transcribing");
      button.classList.toggle("is-error", state === "error");

      const labels = {
        idle: "Start dictation",
        recording: "Stop dictation",
        transcribing: "Transcribing audio",
        complete: "Dictation complete",
        error: "Dictation failed",
      };

      const label = labels[state] || labels.idle;

      button.setAttribute("aria-label", label);
      button.title = label;

      icon.dataset.icon = state === "complete" ? "checkmark" : "microphone";
    }

    function resetAfterDelay(state, delay = 1500) {
      window.setTimeout(() => {
        if (button.dataset.state === state) {
          setState("idle");
        }
      }, delay);
    }

    function insertTranscript(transcript) {
      transcript = transcript.trim();

      if (!transcript) {
        return;
      }

      const prefix = originalValue.slice(0, originalSelectionStart);
      const suffix = originalValue.slice(originalSelectionEnd);

      const needsPrefixSpace =
        prefix.length > 0 && !/\s$/.test(prefix) && !/^[.,!?;:]/.test(transcript);

      const needsSuffixSpace =
        suffix.length > 0 && !/^\s/.test(suffix) && !/[.,!?;:]\s*$/.test(transcript);

      const inserted = (needsPrefixSpace ? " " : "") + transcript + (needsSuffixSpace ? " " : "");

      input.value = prefix + inserted + suffix;

      const cursorPosition = prefix.length + inserted.length;

      input.dispatchEvent(new Event("input", { bubbles: true }));

      try {
        input.setSelectionRange(cursorPosition, cursorPosition);
      } catch {
        // Some input types do not support selection ranges.
      }
    }

    function cleanupStream() {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      recorder = null;
      recording = false;
    }

    async function transcribe(blob) {
      if (!blob.size) {
        setState("error");
        resetAfterDelay("error");
        return;
      }

      setState("transcribing");
      button.disabled = true;

      try {
        const response = await fetch("/api/transcribe", {
          method: "POST",
          headers: {
            "Content-Type": blob.type || "application/octet-stream",
          },
          body: blob,
        });

        const result = await response.json();

        if (!response.ok) {
          throw new Error(result.error || "Transcription failed");
        }

        insertTranscript(result.text || "");

        setState("complete");
        resetAfterDelay("complete");
      } catch (error) {
        console.error("Transcription failed:", error);

        setState("error");
        resetAfterDelay("error", 2500);
      } finally {
        button.disabled = false;
      }
    }

    async function startRecording() {
      originalValue = input.value;

      try {
        originalSelectionStart = input.selectionStart ?? input.value.length;
        originalSelectionEnd = input.selectionEnd ?? input.value.length;
      } catch {
        originalSelectionStart = input.value.length;
        originalSelectionEnd = input.value.length;
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });

        const mimeType = getSupportedMimeType();

        recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

        chunks = [];

        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            chunks.push(event.data);
          }
        };

        recorder.onstop = async () => {
          const blob = new Blob(chunks, {
            type: recorder?.mimeType || chunks[0]?.type || "",
          });

          cleanupStream();
          await transcribe(blob);
        };

        recorder.onerror = (event) => {
          console.error("Recording error:", event.error);
          cleanupStream();
          setState("error");
          resetAfterDelay("error", 2500);
        };

        recorder.start();
        recording = true;
        setState("recording");
      } catch (error) {
        console.error("Unable to start recording:", error);

        cleanupStream();
        setState("error");
        resetAfterDelay("error", 2500);
      }
    }

    button.addEventListener("click", () => {
      if (recording && recorder?.state === "recording") {
        recorder.stop();
        return;
      }

      if (button.dataset.state === "transcribing") {
        return;
      }

      startRecording();
    });

    setState("idle");
  }

  function initialize() {
    document.querySelectorAll(SELECTOR).forEach(initializeSpeechInput);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  // Expose initialization for dynamically added inputs.
  window.initializeSpeechInputs = initialize;
})();
