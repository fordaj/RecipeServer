(() => {
  // Dictation button for the recipe search field.
  //
  // The browser only hands out the microphone to pages served over HTTPS,
  // so the button is removed unless the page was loaded over HTTPS. The
  // recording is transcribed by the server (POST /api/transcribe), which
  // runs the local Whisper model.

  // ----- Constants ----- //
  const SELECTOR = ".speech-input";
  const BUTTON_SELECTOR = ".speech-button";
  const TRANSCRIBE_URL = "/api/transcribe";

  // Icons live in the assets directory and are inlined so they inherit the
  // colour of the button through currentColor.
  const MICROPHONE_ICON_URL = "/assets/microphone.svg";
  const CHECKMARK_ICON_URL = "/assets/checkmark.svg";

  // Containers the browser can record, most preferred first.
  const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

  // How long the "complete" and "error" states stay visible before the
  // button returns to idle.
  const COMPLETE_STATE_MS = 1500;
  const ERROR_STATE_MS = 2500;

  // The label and title of the button for each state.
  const BUTTON_LABELS = {
    idle: "Start dictation",
    recording: "Stop dictation",
    transcribing: "Transcribing audio",
    complete: "Dictation complete",
    error: "Dictation failed",
  };

  // ----- Helpers ----- //

  // The dictation button only works on a secure connection. The site is
  // served over HTTPS by a local reverse proxy, so the protocol of the page
  // is what decides whether the button is offered at all.
  const isSecurePage = () => window.location?.protocol === "https:";

  const supportedMimeType = () => {
    if (!window.MediaRecorder) return "";

    return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  };

  const canRecord = () =>
    Boolean(window.MediaRecorder) && Boolean(navigator.mediaDevices?.getUserMedia);

  // The icon markup comes from assets/icons.js, which has to be loaded
  // before this file. A missing helper only costs the icon, not the button.
  const iconMarkup = async (url) => {
    if (!window.RecipeIcons?.loadSvgIcon) return "";

    return window.RecipeIcons.loadSvgIcon(url);
  };

  // ----- Speech input ----- //
  const initializeSpeechInput = (wrapper) => {
    const input = wrapper.querySelector("input, textarea");
    const button = wrapper.querySelector(BUTTON_SELECTOR);

    if (!input || !button || button.dataset.initialized) return;

    button.dataset.initialized = "true";

    if (!canRecord()) {
      // Nothing to dictate with: leave the button hidden.
      button.remove();
      return;
    }

    const icon = button.querySelector(".speech-button__icon");

    let recorder = null;
    let stream = null;
    let chunks = [];
    let originalValue = "";
    let originalSelectionStart = 0;
    let originalSelectionEnd = 0;

    const setState = (state, message = "") => {
      button.dataset.state = state;

      button.classList.toggle("is-recording", state === "recording");
      button.classList.toggle("is-complete", state === "complete");
      button.classList.toggle("is-transcribing", state === "transcribing");
      button.classList.toggle("is-error", state === "error");

      const label = message || BUTTON_LABELS[state] || BUTTON_LABELS.idle;

      button.setAttribute("aria-label", label);
      button.title = label;

      // The checkmark shows that the transcript made it into the field.
      showIcon(state === "complete" ? CHECKMARK_ICON_URL : MICROPHONE_ICON_URL);
    };

    const resetAfterDelay = (state, delay) => {
      window.setTimeout(() => {
        if (button.dataset.state === state) setState("idle");
      }, delay);
    };

    const showIcon = async (url) => {
      if (!icon) return;

      const markup = await iconMarkup(url);
      if (markup) icon.innerHTML = markup;
    };

    // Put the transcript where the caret was when the recording started.
    const insertTranscript = (transcript) => {
      const text = String(transcript || "").trim();
      if (!text) return;

      const prefix = originalValue.slice(0, originalSelectionStart);
      const suffix = originalValue.slice(originalSelectionEnd);

      const needsPrefixSpace = prefix.length > 0 && !/\s$/.test(prefix) && !/^[.,!?;:]/.test(text);
      const needsSuffixSpace =
        suffix.length > 0 && !/^\s/.test(suffix) && !/[.,!?;:]\s*$/.test(text);

      const inserted = (needsPrefixSpace ? " " : "") + text + (needsSuffixSpace ? " " : "");

      input.value = prefix + inserted + suffix;

      const cursorPosition = prefix.length + inserted.length;

      // The search filter listens for "input", so the transcript takes effect
      // right away.
      input.dispatchEvent(new Event("input", { bubbles: true }));

      try {
        input.setSelectionRange(cursorPosition, cursorPosition);
      } catch {
        // Some input types do not support selection ranges.
      }
    };

    const cleanupStream = () => {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      recorder = null;
    };

    const transcribe = async (blob) => {
      if (!blob.size) {
        setState("error");
        resetAfterDelay("error", ERROR_STATE_MS);
        return;
      }

      setState("transcribing");
      button.disabled = true;

      try {
        const response = await fetch(TRANSCRIBE_URL, {
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

        const text = String(result.text || "").trim();

        if (!text) {
          // Nothing was recognised: say so instead of quietly doing nothing.
          setState("error", "Nothing was heard. Try again.");
          resetAfterDelay("error", ERROR_STATE_MS);
          return;
        }

        insertTranscript(text);

        setState("complete");
        resetAfterDelay("complete", COMPLETE_STATE_MS);
      } catch (error) {
        console.error("Transcription failed:", error);

        // The server explains why a transcription was refused (a missing
        // HTTPS connection, an unusable model), so show that instead of a
        // generic failure.
        setState("error", error.message);
        resetAfterDelay("error", ERROR_STATE_MS);
      } finally {
        button.disabled = false;
      }
    };

    const startRecording = async () => {
      originalValue = input.value;

      try {
        originalSelectionStart = input.selectionStart ?? input.value.length;
        originalSelectionEnd = input.selectionEnd ?? input.value.length;
      } catch {
        originalSelectionStart = input.value.length;
        originalSelectionEnd = input.value.length;
      }

      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        const mimeType = supportedMimeType();

        recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

        chunks = [];

        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) chunks.push(event.data);
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
          resetAfterDelay("error", ERROR_STATE_MS);
        };

        recorder.start();
        setState("recording");
      } catch (error) {
        console.error("Unable to start recording:", error);

        cleanupStream();
        setState("error");
        resetAfterDelay("error", ERROR_STATE_MS);
      }
    };

    button.addEventListener("click", () => {
      if (recorder?.state === "recording") {
        recorder.stop();
        return;
      }

      if (button.dataset.state === "transcribing") return;

      startRecording();
    });

    setState("idle");

    // The button starts hidden in the generated page and is only offered
    // when the page is served over HTTPS.
    button.hidden = false;
  };

  // ----- Entry point ----- //
  const initialize = () => {
    if (!isSecurePage()) {
      // No HTTPS, no dictation: the button is not offered at all.
      document
        .querySelectorAll(`${SELECTOR} ${BUTTON_SELECTOR}`)
        .forEach((button) => button.remove());
      return;
    }

    document.querySelectorAll(SELECTOR).forEach(initializeSpeechInput);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  // Expose initialization for inputs added after the page loaded.
  window.initializeSpeechInputs = initialize;
})();
