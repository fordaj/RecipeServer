// The floating AI assistant bubble, shared by the recipe pages and the index.
// Creates itself from this file (no markup needed), shows a chat panel on
// click, and talks to POST /api/ai-assistant. On a recipe page the current
// recipe's path is sent along so the assistant may edit that one recipe;
// the index page gets read-only answers. The conversation is ephemeral:
// nothing is kept across page loads.
//
// When dictation is enabled in the configuration and the page is served over
// HTTPS (the same gate the search speech button uses), the bubble is
// long-pressable: a microphone pops up directly above it while the user
// holds the press, and releasing stops the recording, transcribes it on the
// machine, and sends the transcript as a message.

(() => {
  const AI_STATUS_API = "/api/ai-status";
  const ASSISTANT_API = "/api/ai-assistant";
  const TRANSCRIBE_URL = "/api/transcribe";
  const AI_ICON_URL = "/assets/ai.svg";
  const SEND_ICON_URL = "/assets/send.svg";
  const MICROPHONE_ICON_URL = "/assets/microphone.svg";
  const CHECKMARK_ICON_URL = "/assets/checkmark.svg";
  // Keep the conversation short enough that Ollama gets a stable prompt.
  // The server enforces its own limits as well.
  const MAX_HISTORY_MESSAGES = 20;
  const MAX_MESSAGE_CHARS = 4000;
  // Scroll deltas below this many pixels are ignored so small jitters do
  // not flip the bubble's visibility.
  const SCROLL_DELTA_PX = 12;
  // Within this many pixels of the top, the page is treated as "at the top"
  // so iOS rubber-band overscroll never hides the bubble.
  const TOP_OF_PAGE_PX = 10;
  const MOBILE_MEDIA_QUERY = "(max-width: 600px)";

  // How long a press has to be held to be treated as dictation (a shorter
  // press is a normal tap on the bubble) and how far a pointer may drift
  // before the long press is cancelled.
  const LONG_PRESS_MS = 450;
  const MOVE_TOLERANCE_PX = 10;
  // How long the "complete" and "error" microphone states stay visible.
  const COMPLETE_STATE_MS = 1200;
  const ERROR_STATE_MS = 2500;

  // Containers the browser can record, most preferred first.
  const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

  // The label of the microphone popup for each state.
  const MIC_LABELS = {
    preparing: "Starting microphone…",
    recording: "Listening… release to send",
    transcribing: "Transcribing…",
    complete: "Sending…",
    error: "Dictation failed",
  };

  const ICON_ATTRIBUTES = {};

  // Dictation only works on a secure connection; the site is served over
  // HTTPS by a local reverse proxy, so the protocol of the page decides.
  const isSecurePage = () => window.location?.protocol === "https:";

  const canRecord = () =>
    Boolean(window.MediaRecorder) && Boolean(navigator.mediaDevices?.getUserMedia);

  const supportedMimeType = () => {
    if (!window.MediaRecorder) return "";

    return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  };

  function recipePathFromLocation() {
    // A recipe page embeds the metadata JSON; the index does not.
    if (!document.getElementById("recipe-metadata")) {
      return null;
    }
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  class AiAssistant {
    constructor() {
      this.conversation = [];
      this.busy = false;
      this.open = false;
      this.recipePath = recipePathFromLocation();
      this.mobileMedia = window.matchMedia(MOBILE_MEDIA_QUERY);
      this.lastScrollY = window.scrollY;
      this.scrollTicking = false;

      // Dictation (long-press on the bubble).
      this.dictationAvailable = false;
      this.longPressTimer = null;
      this.longPressStart = null;
      this.suppressClick = false;
      this.suppressClickTimer = null;
      this.micHideTimer = null;
      this.dictating = false;
      this.dictationCancelled = false;
      this.mediaRecorder = null;
      this.micStream = null;
      this.chunks = [];
    }

    async start() {
      let status = null;
      try {
        const response = await fetch(AI_STATUS_API, { cache: "no-store" });
        if (response.ok) {
          status = await response.json();
        }
      } catch {
        // Without the status endpoint the assistant cannot know whether the
        // model is configured; fail quietly and do not render the bubble.
        return;
      }

      if (!status || status.configured !== true) {
        return;
      }

      this.available = status.available === true;
      this.dictationAvailable =
        this.available && status.dictation_enabled !== false && isSecurePage() && canRecord();
      this.buildDom();
      this.bindScroll();
    }

    buildDom() {
      const wrapper = createElement("div", "ai-assistant");
      wrapper.dataset.aiAssistant = "";
      this.wrapper = wrapper;

      this.button = createElement("button", "ai-assistant__button");
      this.button.type = "button";
      this.button.setAttribute("aria-label", "Ask the AI assistant");
      this.button.title = "Ask the AI assistant";
      this.button.setAttribute("aria-expanded", "false");

      this.panel = createElement("section", "ai-assistant__panel");
      this.panel.setAttribute("role", "dialog");
      this.panel.setAttribute("aria-label", "AI assistant");
      this.panel.setAttribute("aria-hidden", "true");

      const header = createElement("header", "ai-assistant__header");
      this.title = createElement("span", "ai-assistant__title");
      this.titleText = createElement("span", null, "Ask the assistant");
      this.title.append(this.titleText);

      this.closeButton = createElement("button", "ai-assistant__close", "×");
      this.closeButton.type = "button";
      this.closeButton.setAttribute("aria-label", "Close the assistant");
      header.append(this.title, this.closeButton);

      this.messages = createElement("div", "ai-assistant__messages");
      this.messages.setAttribute("aria-live", "polite");

      this.statusLine = createElement("p", "ai-assistant__status");
      this.statusLine.setAttribute("role", "status");

      if (this.available) {
        this.showIntro();
        this.composer = this.buildComposer();
        this.panel.append(header, this.messages, this.statusLine, this.composer);
      } else {
        const notice = createElement(
          "p",
          "ai-assistant__unavailable",
          "The local AI model is not available right now. Check the configuration and that Ollama is running.",
        );
        this.panel.append(header, notice);
      }

      // The microphone popup. The user's thumb covers the bubble while
      // dictating, so the microphone sits directly above it; it is
      // informational only (the press target is the bubble).
      this.mic = createElement("div", "ai-assistant__mic");
      this.mic.setAttribute("role", "status");
      this.mic.setAttribute("aria-hidden", "true");
      this.mic.dataset.state = "idle";
      this.micIcon = createElement("span", "ai-assistant__mic-icon");
      this.micLabel = createElement("span", "ai-assistant__mic-label", MIC_LABELS.preparing);
      this.mic.append(this.micIcon, this.micLabel);

      wrapper.append(this.button, this.panel, this.mic);
      document.body.append(wrapper);

      this.loadIcons();
      this.bindPointerControls();
      this.bindDismiss();

      this.closeButton.addEventListener("click", () => this.setOpen(false));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && this.open) {
          this.setOpen(false);
        }
      });
    }

    async loadIcons() {
      const load = window.RecipeIcons?.loadSvgIcon;
      if (typeof load !== "function") {
        return;
      }

      const [aiIcon, sendIcon, micIcon, checkmarkIcon] = await Promise.all([
        load(AI_ICON_URL, ICON_ATTRIBUTES),
        this.sendButton ? load(SEND_ICON_URL, ICON_ATTRIBUTES) : Promise.resolve(""),
        load(MICROPHONE_ICON_URL, ICON_ATTRIBUTES),
        load(CHECKMARK_ICON_URL, ICON_ATTRIBUTES),
      ]);

      this.microphoneIcon = micIcon;
      this.checkmarkIcon = checkmarkIcon;
      this.setMicIcon("preparing");

      if (aiIcon) {
        this.button.innerHTML = aiIcon;
        const titleIcon = document.createElement("span");
        titleIcon.innerHTML = aiIcon;
        const svg = titleIcon.firstElementChild;
        if (svg) {
          svg.setAttribute("width", "18");
          svg.setAttribute("height", "18");
          this.title.prepend(svg);
        }
      }
      if (this.sendButton && sendIcon) {
        this.sendButton.innerHTML = sendIcon;
      }
    }

    buildComposer() {
      const form = createElement("form", "ai-assistant__composer");

      this.input = createElement("textarea", "ai-assistant__input");
      this.input.rows = 1;
      this.input.maxLength = MAX_MESSAGE_CHARS;
      this.input.placeholder = this.recipePath
        ? "Ask anything, or request a change to this recipe…"
        : "Ask anything…";
      this.input.setAttribute("aria-label", "Message the assistant");

      this.sendButton = createElement("button", "ai-assistant__send");
      this.sendButton.type = "submit";
      this.sendButton.setAttribute("aria-label", "Send message");
      this.sendButton.title = "Send";

      form.append(this.input, this.sendButton);

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.send();
      });

      this.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          this.send();
        }
      });

      this.input.addEventListener("input", () => this.autoResize());
      return form;
    }

    autoResize() {
      this.input.style.height = "auto";
      this.input.style.height = `${Math.min(this.input.scrollHeight, 128)}px`;
    }

    showIntro() {
      const intro = createElement(
        "div",
        "ai-assistant__message ai-assistant__message--intro",
        this.recipePath
          ? "Ask about this recipe, or request a change — e.g. “Adjust the recipe to use half as much salt.”"
          : "Ask anything — e.g. “How many tablespoons are in a cup?”",
      );
      this.messages.append(intro);
    }

    toggle() {
      this.setOpen(!this.open);
    }

    setOpen(open) {
      this.open = open;
      this.wrapper.classList.toggle("ai-assistant--open", open);
      this.button.setAttribute("aria-expanded", String(open));
      this.panel.setAttribute("aria-hidden", String(!open));
      // While the panel is open the bubble is the way to close it, so it
      // must not hide itself on mobile either.
      this.wrapper.classList.toggle("ai-assistant--hidden", false);

      if (open && this.input) {
        this.input.focus();
      } else if (this.button) {
        this.button.focus();
      }
    }

    bindScroll() {
      window.addEventListener(
        "scroll",
        () => {
          if (this.scrollTicking) {
            return;
          }
          this.scrollTicking = true;
          window.requestAnimationFrame(() => {
            this.scrollTicking = false;
            this.updateVisibility();
          });
        },
        { passive: true },
      );
    }

    updateVisibility() {
      const currentY = window.scrollY;
      const delta = currentY - this.lastScrollY;

      if (this.open || this.dictating) {
        this.lastScrollY = currentY;
        return;
      }

      // At the top of the page (within a small allowance for bounce), the
      // bubble is always visible — momentum scrolling bounces the page
      // downward past the top, which would otherwise hide it.
      if (currentY <= TOP_OF_PAGE_PX) {
        this.wrapper.classList.remove("ai-assistant--hidden");
        this.lastScrollY = currentY;
        return;
      }

      if (Math.abs(delta) < SCROLL_DELTA_PX) {
        return;
      }

      if (delta > 0 && this.mobileMedia.matches) {
        // Scrolling down: hide the bubble (mobile only).
        this.wrapper.classList.add("ai-assistant--hidden");
      } else if (delta < 0) {
        // Scrolling up: bring it back.
        this.wrapper.classList.remove("ai-assistant--hidden");
      }

      this.lastScrollY = currentY;
    }

    // ----- Long-press dictation ----- //

    bindPointerControls() {
      this.button.addEventListener("pointerdown", (event) => {
        // Without dictation the bubble is a plain button: a press (however
        // long) just toggles the panel. Right-clicks never start dictation.
        if (event.pointerType === "mouse" && event.button !== 0) {
          return;
        }

        if (!this.dictationAvailable || this.busy) {
          return;
        }

        this.longPressStart = { x: event.clientX, y: event.clientY };
        this.dictationCancelled = false;

        this.longPressTimer = window.setTimeout(() => this.beginDictation(), LONG_PRESS_MS);
      });

      this.button.addEventListener("pointermove", (event) => {
        if (!this.longPressStart) {
          return;
        }

        const moved = Math.hypot(
          event.clientX - this.longPressStart.x,
          event.clientY - this.longPressStart.y,
        );
        if (moved > MOVE_TOLERANCE_PX) {
          this.cancelLongPress();
        }
      });

      const release = () => this.handlePointerRelease();
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);

      if (this.dictationAvailable) {
        // A long press must not summon the context menu on phones.
        this.button.addEventListener("contextmenu", (event) => event.preventDefault());
      }

      this.button.addEventListener("click", () => {
        if (this.suppressClick) {
          // The click that ends a dictation press must not toggle the panel.
          this.suppressClick = false;
          return;
        }

        this.toggle();
      });
    }

    scheduleClickSuppressionReset() {
      window.clearTimeout(this.suppressClickTimer);
      this.suppressClickTimer = window.setTimeout(() => {
        this.suppressClick = false;
      }, 600);
    }

    bindDismiss() {
      // Like the other dialogues: a press that lands entirely off the
      // panel — both the pointer down and the pointer up — closes it.
      // The bubble itself toggles the panel, so it is exempt.
      let pressTarget = null;

      const isPrimary = (event) => event.pointerType !== "mouse" || event.button === 0;
      const insideDialogue = (node) =>
        node instanceof Node && (this.panel.contains(node) || this.button.contains(node));

      document.addEventListener("pointerdown", (event) => {
        pressTarget = this.open && isPrimary(event) ? event.target : null;
      });

      document.addEventListener("pointerup", (event) => {
        const down = pressTarget;
        pressTarget = null;

        if (!this.open || !down || !isPrimary(event)) {
          return;
        }

        if (!insideDialogue(down) && !insideDialogue(event.target)) {
          this.setOpen(false);
        }
      });

      document.addEventListener("pointercancel", () => {
        pressTarget = null;
      });
    }

    cancelLongPress() {
      if (this.longPressTimer) {
        window.clearTimeout(this.longPressTimer);
        this.longPressTimer = null;
      }
      this.longPressStart = null;
    }

    handlePointerRelease() {
      // A trailing click usually consumes the suppression; re-arm the
      // fallback every time the press ends.
      this.scheduleClickSuppressionReset();

      const micState = this.mic?.dataset.state;
      const capturing = this.dictating && (micState === "preparing" || micState === "recording");

      if (capturing) {
        this.stopDictation();
        return;
      }

      if (this.dictating) {
        // Transcribing/complete is already detached from the press; the
        // mic hides itself when it is done.
        return;
      }

      this.cancelLongPress();
    }

    setMicIcon(state) {
      if (!this.micIcon) {
        return;
      }

      const markup = state === "complete" ? this.checkmarkIcon : this.microphoneIcon;
      if (markup) {
        this.micIcon.innerHTML = markup;
      }
    }

    showMic(state, message = "") {
      window.clearTimeout(this.micHideTimer);

      this.mic.dataset.state = state;
      this.mic.classList.add("ai-assistant__mic--visible");
      this.mic.setAttribute("aria-hidden", "false");
      this.micLabel.textContent = message || MIC_LABELS[state] || MIC_LABELS.preparing;
      this.setMicIcon(state);
    }

    hideMic(delay = 0) {
      window.clearTimeout(this.micHideTimer);

      const hide = () => {
        this.mic.classList.remove("ai-assistant__mic--visible");
        this.mic.setAttribute("aria-hidden", "true");
        this.mic.dataset.state = "idle";

        this.dictating = false;
        this.wrapper.classList.remove("ai-assistant--dictating");
      };

      if (delay > 0) {
        this.micHideTimer = window.setTimeout(hide, delay);
      } else {
        hide();
      }
    }

    dictationError(message) {
      this.showMic("error", message);
      this.cancelDictationCapture();
      this.hideMic(ERROR_STATE_MS);
    }

    cancelDictationCapture() {
      this.dictationCancelled = true;
      this.stopMicStream();
    }

    stopMicStream() {
      this.micStream?.getTracks().forEach((track) => track.stop());
      this.micStream = null;
      this.mediaRecorder = null;
    }

    beginDictation() {
      this.longPressTimer = null;
      this.longPressStart = null;

      this.dictating = true;
      this.dictationCancelled = false;
      this.suppressClick = true;
      this.wrapper.classList.add("ai-assistant--dictating");
      // The press target is now the release of the press; it must not be
      // hidden by the scroll behavior.
      this.wrapper.classList.remove("ai-assistant--hidden");

      this.showMic("preparing");
      this.startRecording();
    }

    async startRecording() {
      const mimeType = supportedMimeType();

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        if (this.dictationCancelled || !this.dictating) {
          // The user already let go before the microphone came up.
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        this.micStream = stream;

        const recorder = mimeType
          ? new MediaRecorder(stream, { mimeType })
          : new MediaRecorder(stream);
        this.mediaRecorder = recorder;
        this.chunks = [];

        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) {
            this.chunks.push(event.data);
          }
        };

        recorder.onstop = () => {
          const blob = new Blob(this.chunks, {
            type: recorder.mimeType || this.chunks[0]?.type || "",
          });
          this.stopMicStream();
          this.transcribeDictation(blob);
        };

        recorder.onerror = (event) => {
          console.error("Recording error:", event.error);
          this.dictationError("Recording failed. Try again.");
        };

        recorder.start();
        this.showMic("recording");
      } catch (error) {
        console.error("Unable to start recording:", error);
        this.dictationError("Unable to access the microphone.");
      }
    }

    stopDictation() {
      if (this.mediaRecorder?.state === "recording") {
        this.showMic("transcribing");
        this.mediaRecorder.stop();
        return;
      }

      // The release happened before the microphone was ready (or the
      // recorder was already gone): cancel quietly. The trailing click is
      // still swallowed because the press was a dictation press.
      this.cancelDictationCapture();
      this.hideMic();
    }

    async transcribeDictation(blob) {
      if (!blob.size) {
        this.dictationError("Nothing was heard. Try again.");
        return;
      }

      this.showMic("transcribing");

      let text = "";
      try {
        const response = await fetch(TRANSCRIBE_URL, {
          method: "POST",
          headers: {
            "Content-Type": blob.type || "application/octet-stream",
          },
          body: blob,
        });

        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
          throw new Error(result?.error || "Transcription failed");
        }

        text = String(result?.text || "").trim();
      } catch (error) {
        console.error("Transcription failed:", error);
        this.dictationError(error.message || "Transcribing failed. Try again.");
        return;
      }

      if (!text) {
        this.dictationError("Nothing was heard. Try again.");
        return;
      }

      // The transcript goes out exactly like a typed message: open the
      // panel, load it into the composer, send it.
      this.setOpen(true);
      this.input.value = text;
      this.autoResize();

      this.showMic("complete");
      this.hideMic(COMPLETE_STATE_MS);

      this.send();
    }

    // ----- Conversation ----- //

    appendMessage(role, text) {
      this.messages.querySelector(".ai-assistant__message--intro")?.remove();

      const className =
        role === "user"
          ? "ai-assistant__message ai-assistant__message--user"
          : role === "error"
            ? "ai-assistant__message ai-assistant__message--error"
            : "ai-assistant__message ai-assistant__message--assistant";

      const bubble = createElement("div", className, text);
      this.messages.append(bubble);
      this.messages.scrollTop = this.messages.scrollHeight;
      return bubble;
    }

    appendReloadNotice(path) {
      const notice = createElement("div", "ai-assistant__notice");
      const text = createElement("span", null, `The recipe was updated${path ? `: ${path}` : ""}.`);
      const reload = createElement("button", "ai-assistant__notice-button", "Reload page");
      reload.type = "button";
      reload.addEventListener("click", () => window.location.reload());
      notice.append(text, reload);
      this.messages.append(notice);
      this.messages.scrollTop = this.messages.scrollHeight;
    }

    setStatus(message, busy) {
      this.statusLine.textContent = message || "";
      this.statusLine.classList.toggle("ai-assistant__status--busy", Boolean(busy));
    }

    setBusy(busy) {
      this.busy = busy;
      if (this.sendButton) {
        this.sendButton.disabled = busy;
      }
      if (this.input) {
        this.input.disabled = busy;
      }
    }

    rememberTurn(role, content) {
      this.conversation.push({ role, content });
      if (this.conversation.length > MAX_HISTORY_MESSAGES) {
        this.conversation = this.conversation.slice(-MAX_HISTORY_MESSAGES);
      }
    }

    async send() {
      if (this.busy || !this.input) {
        return;
      }

      const message = this.input.value.trim();
      if (!message) {
        return;
      }

      this.appendMessage("user", message);
      this.rememberTurn("user", message);
      this.input.value = "";
      this.autoResize();
      this.setBusy(true);
      this.setStatus("Thinking…", true);

      try {
        const response = await fetch(ASSISTANT_API, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          body: JSON.stringify({
            message,
            history: this.conversation.slice(0, -1),
            ...(this.recipePath ? { path: this.recipePath } : {}),
            stream: true,
          }),
        });

        if (!response.ok || !response.body) {
          const detail = await readErrorDetail(response);
          throw new Error(detail || `The assistant request failed (HTTP ${response.status})`);
        }

        await this.readEventStream(response.body);
      } catch (error) {
        this.appendMessage(
          "error",
          error?.message || "Something went wrong while talking to the assistant.",
        );
      } finally {
        this.setBusy(false);
        // Idempotent: result/error handlers already clear the status line.
        this.setStatus("", false);
      }
    }

    async readEventStream(body) {
      const reader = body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          this.handleEventBlock(block);
        }
      }
    }

    handleEventBlock(block) {
      let event = "message";
      const dataLines = [];

      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).replace(/^ /, ""));
        }
      }

      if (!dataLines.length) {
        return;
      }

      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        return;
      }

      if (event === "status") {
        this.setStatus(data?.message || "", true);
        return;
      }

      if (event === "result") {
        const result = data?.result ?? {};
        const reply =
          typeof result.reply === "string" && result.reply.trim()
            ? result.reply
            : "(The assistant returned an empty reply.)";
        this.appendMessage("assistant", reply);
        this.rememberTurn("assistant", reply);
        if (result.edited === true) {
          this.appendReloadNotice(result.path);
        }
        this.setStatus("", false);
        return;
      }

      if (event === "error") {
        this.appendMessage("error", data?.message || "The assistant ran into a problem.");
        this.setStatus("", false);
      }
    }
  }

  async function readErrorDetail(response) {
    try {
      const body = await response.json();
      return typeof body?.error === "string" ? body.error : "";
    } catch {
      return "";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const assistant = new AiAssistant();
    assistant.start();
  });
})();
