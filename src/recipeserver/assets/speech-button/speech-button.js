(() => {
  // The dictation button for the recipe search field. The microphone and
  // transcription transport are shared with the assistant in assets/dictation.js;
  // this file owns the button, its status pill, and the pointer/tap wiring.

  const SELECTOR = ".speech-input";
  const BUTTON_SELECTOR = ".speech-button";

  const {
    isSecurePage,
    canRecord,
    createRecorder,
    transcribe,
    LONG_PRESS_MS,
    MOVE_TOLERANCE_PX,
    COMPLETE_STATE_MS,
    ERROR_STATE_MS,
  } = window.RecipeDictation;

  // Icons live in the assets directory and are inlined so they inherit the
  // colour of the button through currentColor.
  const MICROPHONE_ICON_URL = "/assets/microphone.svg";
  const CHECKMARK_ICON_URL = "/assets/checkmark.svg";

  const PILL_LABELS = {
    preparing: "Starting microphone…",
    recording: "Listening… tap the mic to stop",
    recordingHold: "Listening — release to stop",
    transcribing: "Transcribing…",
    complete: "Done",
    error: "Dictation failed",
  };

  const BUTTON_LABELS = {
    idle: "Start dictation",
    preparing: "Starting microphone",
    recording: "Stop dictation",
    transcribing: "Transcribing audio",
    complete: "Dictation complete",
    error: "Dictation failed",
  };

  const iconMarkup = async (url) => {
    if (!window.RecipeIcons?.loadSvgIcon) return "";
    return window.RecipeIcons.loadSvgIcon(url);
  };

  const initializeSpeechInput = (wrapper) => {
    const input = wrapper.querySelector("input, textarea");
    const button = wrapper.querySelector(BUTTON_SELECTOR);

    if (!input || !button || button.dataset.initialized) return;
    button.dataset.initialized = "true";

    if (!canRecord()) {
      button.remove();
      return;
    }

    const icon = button.querySelector(".speech-button__icon");

    let originalValue = "";
    let originalSelectionStart = 0;
    let originalSelectionEnd = 0;
    let longPressTimer = null;
    let longPressStart = null;
    let suppressTimer = null;
    let holdToTalk = false;
    let suppressClick = false;

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
      if (state === "recording" && holdToTalk) label = PILL_LABELS.recordingHold;

      pill.dataset.state = state;
      pillLabel.textContent = label;
      pill.classList.add("speech-button__status--visible");
      pill.setAttribute("aria-hidden", "false");

      const iconUrl = state === "complete" ? CHECKMARK_ICON_URL : MICROPHONE_ICON_URL;
      iconMarkup(iconUrl).then((markup) => {
        if (markup) pillIcon.innerHTML = markup;
      });
    };

    const showIcon = async (url) => {
      if (!icon) return;
      const markup = await iconMarkup(url);
      if (markup) icon.innerHTML = markup;
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

      showIcon(state === "complete" ? CHECKMARK_ICON_URL : MICROPHONE_ICON_URL);
      setPillState(state, message);

      if (state === "idle") holdToTalk = false;
    };

    const resetAfterDelay = (state, delay) => {
      window.setTimeout(() => {
        if (button.dataset.state === state) setState("idle");
      }, delay);
    };

    const fail = (message) => {
      setState("error", message);
      resetAfterDelay("error", ERROR_STATE_MS);
    };

    const insertTranscript = (text) => {
      const prefix = originalValue.slice(0, originalSelectionStart);
      const suffix = originalValue.slice(originalSelectionEnd);

      const needsPrefixSpace = prefix.length > 0 && !/\s$/.test(prefix) && !/^[.,!?;:]/.test(text);
      const needsSuffixSpace = suffix.length > 0 && !/^\s/.test(suffix) && !/[.,!?;:]\s*$/.test(text);
      const inserted = (needsPrefixSpace ? " " : "") + text + (needsSuffixSpace ? " " : "");

      input.value = prefix + inserted + suffix;
      input.dispatchEvent(new Event("input", { bubbles: true }));

      try {
        const cursorPosition = prefix.length + inserted.length;
        input.setSelectionRange(cursorPosition, cursorPosition);
      } catch {
        // Some input types do not support selection ranges.
      }
    };

    const recorder = createRecorder({
      onStop: async (blob) => {
        setState("transcribing");
        button.disabled = true;
        try {
          // A search query never needs the full stop the model closes
          // utterances with, so the transcript must not end in one.
          const text = await transcribe(blob, { stripTrailingPeriod: true });
          insertTranscript(text);
          setState("complete");
          resetAfterDelay("complete", COMPLETE_STATE_MS);
        } catch (error) {
          console.error("Transcription failed:", error);
          fail(error.message);
        } finally {
          button.disabled = false;
        }
      },
      onError: () => fail(),
    });

    const startRecording = async () => {
      originalValue = input.value;
      try {
        originalSelectionStart = input.selectionStart ?? input.value.length;
        originalSelectionEnd = input.selectionEnd ?? input.value.length;
      } catch {
        originalSelectionStart = input.value.length;
        originalSelectionEnd = input.value.length;
      }

      setState("preparing");
      const started = await recorder.start();
      if (started) setState("recording");
      else if (button.dataset.state !== "idle") fail();
    };

    const cancelLongPress = () => {
      if (longPressTimer) {
        window.clearTimeout(longPressTimer);
        longPressTimer = null;
      }
      longPressStart = null;
    };

    button.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (button.dataset.state !== "idle") return;

      longPressStart = { x: event.clientX, y: event.clientY };
      longPressTimer = window.setTimeout(() => {
        longPressTimer = null;
        longPressStart = null;
        holdToTalk = true;
        startRecording();
      }, LONG_PRESS_MS);
    });

    button.addEventListener("pointermove", (event) => {
      if (!longPressStart) return;
      const moved = Math.hypot(event.clientX - longPressStart.x, event.clientY - longPressStart.y);
      if (moved > MOVE_TOLERANCE_PX) cancelLongPress();
    });

    const suppressTrailingClick = () => {
      suppressClick = true;
      window.clearTimeout(suppressTimer);
      suppressTimer = window.setTimeout(() => {
        suppressClick = false;
      }, 600);
    };

    const handleRelease = () => {
      if (holdToTalk && recorder.isRecording()) {
        suppressTrailingClick();
        recorder.stop();
        return;
      }

      if (holdToTalk) {
        const state = button.dataset.state;
        if (state === "transcribing" || state === "complete" || state === "error") {
          suppressTrailingClick();
          return;
        }
        // Released before the microphone came up: cancel quietly.
        recorder.cancel();
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
        suppressClick = false;
        return;
      }
      if (recorder.isRecording()) {
        recorder.stop();
        return;
      }
      if (button.dataset.state === "transcribing") return;
      startRecording();
    });

    setState("idle");
    button.hidden = false;
  };

  const initialize = () => {
    if (!isSecurePage()) {
      document.querySelectorAll(`${SELECTOR} ${BUTTON_SELECTOR}`).forEach((button) => button.remove());
      return;
    }
    document.querySelectorAll(SELECTOR).forEach(initializeSpeechInput);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  window.initializeSpeechInputs = initialize;
})();
