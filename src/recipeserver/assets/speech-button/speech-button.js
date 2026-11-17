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

  // How long a press must be held to be treated as hold-to-dictate (a
  // shorter press is a normal tap that toggles the recording).
  const LONG_PRESS_MS = 450;
  const MOVE_TOLERANCE_PX = 10;

  // How long the "complete" and "error" states stay visible before the
  // button returns to idle.
  const COMPLETE_STATE_MS = 1500;
  const ERROR_STATE_MS = 2500;

  // The label of the pill above the button for each live state.
  const PILL_LABELS = {
    preparing: "Starting microphone…",
    recording: "Listening… tap the mic to stop",
    recordingHold: "Listening — release to stop",
    transcribing: "Transcribing…",
    complete: "Done",
    error: "Dictation failed",
  };

  // The label and title of the button for each state.
  const BUTTON_LABELS = {
    idle: "Start dictation",
    preparing: "Starting microphone",
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
    let longPressTimer = null;
    let longPressStart = null;
    let suppressTimer = null;
    // True while a hold-to-dictate press is being captured or is waiting on
    // the microphone permission; cleared when the capture resolves or is
    // cancelled.
    let dictationCancelled = false;
    // True when the recording was started by holding the press; false when
    // it was started by a tap (toggle mode). Decides the pill's label.
    let holdToTalk = false;
    // Set when the release of a hold must not also trigger the click toggle.
    let suppressClick = false;

    // The status pill above the button (the same treatment the AI assistant
    // popup gets): a small pill that shows what the recording is doing.
    const pill = document.createElement("div");
    pill.className = "speech-button__status";
    pill.setAttribute("role", "status");
    pill.setAttribute("aria-hidden", "true");
    pill.dataset.state = "idle";
    const pillIcon = document.createElement("span");
    pillIcon.className = "speech-button__status-icon";
    const pillLabel = document.createElement("span");
    pillLabel.className = "speech-button__status-label";
    pillLabel.textContent = PILL_LABELS.preparing;
    pill.append(pillIcon, pillLabel);
    wrapper.append(pill);

    const setPillState = (state, message = "") => {
      if (state === "idle") {
        pill.dataset.state = "idle";
        pill.classList.remove("speech-button__status--visible");
        pill.setAttribute("aria-hidden", "true");
        return;
      }

      let label = message || PILL_LABELS[state] || PILL_LABELS.error;
      if (state === "recording" && holdToTalk) {
        label = PILL_LABELS.recordingHold;
      }

      pill.dataset.state = state;
      pillLabel.textContent = label;
      pill.classList.add("speech-button__status--visible");
      pill.setAttribute("aria-hidden", "false");

      const iconUrl = state === "complete" ? CHECKMARK_ICON_URL : MICROPHONE_ICON_URL;
      iconMarkup(iconUrl).then((markup) => {
        if (markup) pillIcon.innerHTML = markup;
      });
    };

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
      setPillState(state, message);

      if (state === "idle") {
        // A hold that completed (or failed) ends here.
        holdToTalk = false;
      }
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
      dictationCancelled = false;
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

        if (dictationCancelled) {
          // The user let go before the microphone came up.
          stream.getTracks().forEach((track) => track.stop());
          stream = null;
          setState("idle");
          return;
        }

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

    const cancelLongPress = () => {
      if (longPressTimer) {
        window.clearTimeout(longPressTimer);
        longPressTimer = null;
      }
      longPressStart = null;
    };

    button.addEventListener("pointerdown", (event) => {
      // Right-clicks and non-primary buttons never dictate.
      if (event.pointerType === "mouse" && event.button !== 0) return;
      // Starting a new dictation is only possible from idle: a press while
      // recording stops through the click path (handled below), and a press
      // while transcribing is ignored.
      if (button.dataset.state !== "idle") return;

      longPressStart = { x: event.clientX, y: event.clientY };
      longPressTimer = window.setTimeout(() => {
        longPressTimer = null;
        longPressStart = null;
        holdToTalk = true;
        setState("preparing");
        startRecording();
      }, LONG_PRESS_MS);
    });

    button.addEventListener("pointermove", (event) => {
      if (!longPressStart) return;

      const moved = Math.hypot(event.clientX - longPressStart.x, event.clientY - longPressStart.y);
      if (moved > MOVE_TOLERANCE_PX) {
        cancelLongPress();
      }
    });

    const suppressTrailingClick = () => {
      suppressClick = true;
      window.clearTimeout(suppressTimer);
      suppressTimer = window.setTimeout(() => {
        suppressClick = false;
      }, 600);
    };

    // Release anywhere stops the recording (a hold can drift off the button).
    const handleRelease = () => {
      if (holdToTalk && recorder?.state === "recording") {
        suppressTrailingClick();
        recorder.stop();
        return;
      }

      if (holdToTalk) {
        const state = button.dataset.state;
        if (state === "transcribing" || state === "complete" || state === "error") {
          // The capture is already finished; swallow the trailing click and
          // let the pill hide itself.
          suppressTrailingClick();
          return;
        }

        // Released before the microphone came up: cancel the capture quietly.
        dictationCancelled = true;
        holdToTalk = false;
        suppressTrailingClick();
        setState("idle");
        return;
      }

      cancelLongPress();
    };
    document.addEventListener("pointerup", handleRelease);
    document.addEventListener("pointercancel", handleRelease);

    button.addEventListener("click", () => {
      if (suppressClick) {
        // The click that ends a hold must not toggle anything.
        suppressClick = false;
        return;
      }

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
