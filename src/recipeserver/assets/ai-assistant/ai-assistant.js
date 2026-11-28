// The floating AI assistant bubble, shared by the recipe pages and the index.
// Creates itself from this file (no markup needed), shows a chat panel on
// click, and talks to POST /api/ai-assistant. On a recipe page the current
// recipe's path is sent along so the assistant may edit that one recipe;
// the index page gets read-only answers. The conversation is ephemeral:
// nothing is kept across page loads.
//
// Both the user's and the assistant's messages are rendered as Markdown
// through POST /api/assistant-markdown — the same strategy the recipe pages
// use — with inline-code quantities typeset by KaTeX at 1x scale. KaTeX is
// loaded lazily on first rendered message (the shopping list does the same).
//
// When the model calls the open_recipe tool, the reply's `open` field tells
// the browser which page to redirect to; the assistant cannot navigate
// anywhere else.
//
// When dictation is enabled in the configuration and the page is served over
// HTTPS (the same gate the search speech button uses), the bubble is
// long-pressable: a microphone pops up directly above it while the user
// holds the press, and releasing stops the recording, transcribes it on the
// machine, and sends the transcript as a message.

(() => {
  const AI_STATUS_API = "/api/ai-status";
  const ASSISTANT_API = "/api/ai-assistant";
  const ASSISTANT_MARKDOWN_API = "/api/assistant-markdown";
  const TRANSCRIBE_URL = "/api/transcribe";
  const AI_ICON_URL = "/assets/ai.svg";
  const SEND_ICON_URL = "/assets/send.svg";
  const MICROPHONE_ICON_URL = "/assets/microphone.svg";
  const CHECKMARK_ICON_URL = "/assets/checkmark.svg";
  const KATEX_CSS_URL = "/assets/katex/dist/katex.min.css";
  const KATEX_JS_URL = "/assets/katex/dist/katex.min.js";
  const KATEX_AUTO_RENDER_URL = "/assets/katex/dist/contrib/auto-render.min.js";
  // Give the browser a moment to show the assistant's reply before the
  // open_recipe redirect navigates the page away.
  const OPEN_REDIRECT_DELAY_MS = 1200;
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
    recordingTap: "Listening… tap the mic to stop",
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

  // ----- Markdown rendering (lazy KaTeX) ----- //
  // The recipe pages ship KaTeX on every page; the index does not, so the
  // bubble loads it on first rendered message instead of every page view.

  let katexPromise = null;

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const SCRIPT_LOAD_TIMEOUT_MS = 8000;
      const existing = document.querySelector(`script[src="${url}"]`);
      if (existing && existing.dataset.loaded === "true") {
        resolve();
        return;
      }

      const script = existing ?? document.createElement("script");
      let timeout = 0;
      const cleanup = () => window.clearTimeout(timeout);
      script.addEventListener("load", () => {
        cleanup();
        script.dataset.loaded = "true";
        resolve();
      });
      script.addEventListener("error", () => {
        cleanup();
        reject(new Error(`Unable to load ${url}`));
      });
      timeout = window.setTimeout(() => {
        // The tag exists but its load event already fired (eagerly loaded,
        // e.g. on a recipe page, and failed there). Bounded wait, then fall back.
        reject(new Error(`Timed out loading ${url}`));
      }, SCRIPT_LOAD_TIMEOUT_MS);
      if (!existing) {
        script.src = url;
        script.defer = true;
        document.head.append(script);
      }
    });
  }

  function loadKatex() {
    if (
      typeof window.katex?.render === "function" &&
      typeof window.renderMathInElement === "function"
    ) {
      return Promise.resolve();
    }
    if (katexPromise) {
      return katexPromise;
    }

    katexPromise = (async () => {
      if (!document.querySelector(`link[href="${KATEX_CSS_URL}"]`)) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = KATEX_CSS_URL;
        document.head.append(link);
      }

      if (typeof window.katex?.render !== "function") {
        await loadScript(KATEX_JS_URL);
      }
      if (typeof window.renderMathInElement !== "function") {
        await loadScript(KATEX_AUTO_RENDER_URL);
      }
    })().catch((error) => {
      katexPromise = null;
      throw error;
    });

    return katexPromise;
  }

  // Server-side Markdown rendering (same pipeline as the recipe bodies).
  async function fetchRenderedMarkdown(text) {
    const response = await fetch(ASSISTANT_MARKDOWN_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: text }),
    });

    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result?.error || `Unable to render the message (HTTP ${response.status})`);
    }
    return typeof result?.html === "string" ? result.html : "";
  }

  // Typeset the server-emitted .quantity spans at 1x (the chat has no
  // scaler controls), then the LaTeX math — the same order and the same
  // delimiter set the recipe pages and the shopping list use.
  function renderQuantities(bubble) {
    // Top-level class in recipe-scaler.js: a global binding, not a window
    // property (the same way the shopping list uses it).
    if (typeof RecipeScaler === "undefined") {
      return;
    }

    const scaler = RecipeScaler;

    for (const element of bubble.querySelectorAll(".quantity")) {
      const quantity = parseFloat(element.dataset.quantity);
      const unit = element.dataset.unit ?? "";
      if (!Number.isFinite(quantity)) {
        continue;
      }

      let formatted = scaler.formatQuantity(quantity, unit);
      let text = scaler.formatQuantityText(quantity, unit);
      const endRaw = element.dataset.quantityEnd;
      if (endRaw !== undefined) {
        const end = parseFloat(endRaw);
        if (Number.isFinite(end)) {
          formatted = scaler.formatQuantityRange(quantity, end, 1, unit);
          text = scaler.formatQuantityRangeText(quantity, end, 1, unit);
        }
      }

      element.dataset.scaledText = text;
      element.dataset.scaledQuantity = String(quantity);
      scaler.renderQuantity(element, formatted);
    }
  }

  async function renderMathInBubble(bubble) {
    try {
      await loadKatex();
    } catch (error) {
      // The page still shows the amounts as plain fractions; not fatal.
      console.warn("KaTeX could not be loaded for the chat message.", error);
      return;
    }

    renderQuantities(bubble);

    if (typeof window.renderMathInElement === "function") {
      window.renderMathInElement(bubble, {
        delimiters: [
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        ignoredClasses: ["quantity"],
        throwOnError: false,
      });
    }
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

      // Dictation (long press on the bubble, or the inline mic in the composer).
      this.dictationAvailable = false;
      this.longPressTimer = null;
      this.longPressStart = null;
      // Which press-consuming click to swallow ("bubble" | "field").
      this.suppressClickFor = null;
      this.suppressClickTimer = null;
      this.pillHideTimer = null;
      this.dictating = false;
      this.dictationCancelled = false;
      this.dictationSource = null;
      this.dictationViaHold = false;
      this.pillState = "idle";
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
      this.bindMicButton();
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
      this.setPillIcon("preparing");
      if (this.micButton && micIcon) {
        this.micButton.innerHTML = micIcon;
      }

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

      this.field = createElement("div", "ai-assistant__field");

      this.input = createElement("textarea", "ai-assistant__input");
      this.input.rows = 1;
      this.input.maxLength = MAX_MESSAGE_CHARS;
      this.input.placeholder = this.recipePath
        ? "Ask anything, or request a change to this recipe…"
        : "Ask anything…";
      this.input.setAttribute("aria-label", "Message the assistant");

      this.field.append(this.input);

      // The inline dictation microphone, sitting inside the field. It is
      // only offered under the same conditions as the bubble's long press.
      if (this.dictationAvailable) {
        this.field.classList.add("ai-assistant__field--dictation");
        this.micButton = createElement("button", "ai-assistant__mic-button");
        this.micButton.type = "button";
        this.micButton.setAttribute("aria-label", "Dictate a message");
        this.micButton.title = "Dictate a message";
        this.field.append(this.micButton);
      }

      // The microphone popup for the inline button (the bubble has its own).
      this.fieldStatus = createElement("div", "ai-assistant__field-status");
      this.fieldStatus.setAttribute("role", "status");
      this.fieldStatus.setAttribute("aria-hidden", "true");
      this.fieldStatus.dataset.state = "idle";
      this.fieldStatusIcon = createElement("span", "ai-assistant__mic-icon");
      this.fieldStatusLabel = createElement(
        "span",
        "ai-assistant__mic-label",
        MIC_LABELS.preparing,
      );
      this.fieldStatus.append(this.fieldStatusIcon, this.fieldStatusLabel);
      this.field.append(this.fieldStatus);

      this.sendButton = createElement("button", "ai-assistant__send");
      this.sendButton.type = "submit";
      this.sendButton.setAttribute("aria-label", "Send message");
      this.sendButton.title = "Send";

      form.append(this.field, this.sendButton);

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

    bindPressHandler(element, source) {
      // Shared long-press plumbing for the bubble and the inline mic: hold
      // far enough and dictation starts; otherwise the press falls through
      // to the element's own click behavior.
      element.addEventListener("pointerdown", (event) => {
        if (event.pointerType === "mouse" && event.button !== 0) {
          return;
        }

        if (!this.dictationAvailable || this.busy || this.dictating) {
          return;
        }

        this.dictationViaHold = false;
        this.dictationCancelled = false;
        this.armDictation(source, event);
      });

      element.addEventListener("pointermove", (event) => {
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
    }

    armDictation(source, event) {
      this.longPressStart = { x: event.clientX, y: event.clientY };
      this.longPressTimer = window.setTimeout(() => {
        this.longPressTimer = null;
        this.longPressStart = null;
        this.dictationViaHold = true;
        this.beginDictation(source, true);
      }, LONG_PRESS_MS);
    }

    bindPointerControls() {
      this.bindPressHandler(this.button, "bubble");

      const release = () => this.handlePointerRelease();
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);

      if (this.dictationAvailable) {
        // A long press must not summon the context menu on phones.
        this.button.addEventListener("contextmenu", (event) => event.preventDefault());
      }

      this.button.addEventListener("click", () => {
        if (this.suppressClickFor === "bubble") {
          // The click that ends a dictation press must not toggle the panel.
          this.suppressClickFor = null;
          return;
        }

        this.toggle();
      });
    }

    bindMicButton() {
      if (!this.micButton) {
        return;
      }

      this.bindPressHandler(this.micButton, "field");

      if (this.dictationAvailable) {
        this.micButton.addEventListener("contextmenu", (event) => event.preventDefault());
      }

      this.micButton.addEventListener("click", () => {
        if (this.suppressClickFor === "field") {
          // The click that ends a dictation press must not toggle the mic.
          this.suppressClickFor = null;
          return;
        }

        if (this.dictating) {
          // Tap toggles the recording off; transcription states ignore taps.
          if (this.pillState === "recording") {
            this.stopDictation();
          }
          return;
        }

        this.dictationViaHold = false;
        this.beginDictation("field", false);
      });
    }

    scheduleClickSuppressionReset() {
      window.clearTimeout(this.suppressClickTimer);
      this.suppressClickTimer = window.setTimeout(() => {
        this.suppressClickFor = null;
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

      const capturing =
        this.dictating && (this.pillState === "preparing" || this.pillState === "recording");

      if (capturing) {
        this.stopDictation();
        return;
      }

      if (this.dictating) {
        // Transcribing/complete is already detached from the press; the
        // pill hides itself when it is done.
        return;
      }

      this.cancelLongPress();
    }

    pillParts() {
      if (this.dictationSource === "field" && this.fieldStatus) {
        return {
          container: this.fieldStatus,
          label: this.fieldStatusLabel,
          icon: this.fieldStatusIcon,
          extraClass: "ai-assistant__field-status--visible",
        };
      }

      return {
        container: this.mic,
        label: this.micLabel,
        icon: this.micIcon,
        extraClass: "ai-assistant__mic--visible",
      };
    }

    pillLabelFor(state) {
      if (state === "recording" && !this.dictationViaHold) {
        return MIC_LABELS.recordingTap;
      }

      return MIC_LABELS[state] || MIC_LABELS.preparing;
    }

    setPillIcon(state) {
      const markup = state === "complete" ? this.checkmarkIcon : this.microphoneIcon;
      if (!markup) {
        return;
      }

      const { icon } = this.pillParts();
      if (icon) {
        icon.innerHTML = markup;
      }
    }

    showPill(state, message = "") {
      window.clearTimeout(this.pillHideTimer);
      this.pillState = state;

      const { container, label } = this.pillParts();
      container.dataset.state = state;
      container.classList.add(this.pillParts().extraClass);
      container.setAttribute("aria-hidden", "false");
      label.textContent = message || this.pillLabelFor(state);
      this.setPillIcon(state);
    }

    hidePill(delay = 0) {
      window.clearTimeout(this.pillHideTimer);

      const hide = () => {
        const { container, extraClass } = this.pillParts();
        container.classList.remove(extraClass);
        container.setAttribute("aria-hidden", "true");
        container.dataset.state = "idle";

        this.pillState = "idle";
        this.dictating = false;
        this.dictationSource = null;
        this.wrapper.classList.remove("ai-assistant--dictating");
      };

      if (delay > 0) {
        this.pillHideTimer = window.setTimeout(hide, delay);
      } else {
        hide();
      }
    }

    dictationError(message) {
      this.showPill("error", message);
      this.cancelDictationCapture();
      this.hidePill(ERROR_STATE_MS);
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

    beginDictation(source, viaHold) {
      this.longPressTimer = null;
      this.longPressStart = null;

      this.dictationSource = source;
      this.dictationViaHold = viaHold;
      this.dictating = true;
      this.dictationCancelled = false;
      this.pillState = "preparing";
      // Only a hold produces a trailing click to swallow; a tap toggles and
      // must not eat the next press.
      this.suppressClickFor = viaHold ? source : null;

      if (source === "bubble") {
        this.wrapper.classList.add("ai-assistant--dictating");
        // The press target is now the release of the press; it must not be
        // hidden by the scroll behavior.
        this.wrapper.classList.remove("ai-assistant--hidden");
      }

      this.showPill("preparing");
      this.startRecording();
    }

    async startRecording() {
      const mimeType = supportedMimeType();

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        if (this.dictationCancelled || !this.dictating) {
          // The user already let go before the microphone came up.
          stream.getTracks().forEach((track) => track.stop());
          this.hidePill();
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
        this.pillState = "recording";
        this.showPill("recording");
      } catch (error) {
        console.error("Unable to start recording:", error);
        this.dictationError("Unable to access the microphone.");
      }
    }

    stopDictation() {
      if (this.mediaRecorder?.state === "recording") {
        this.pillState = "transcribing";
        this.showPill("transcribing");
        this.mediaRecorder.stop();
        return;
      }

      // The release happened before the microphone was ready (or the
      // recorder was already gone): cancel quietly. The trailing click is
      // still swallowed because the press was a dictation press.
      this.cancelDictationCapture();
      this.hidePill();
    }

    async transcribeDictation(blob) {
      if (!blob.size) {
        this.dictationError("Nothing was heard. Try again.");
        return;
      }

      this.pillState = "transcribing";
      this.showPill("transcribing");

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

      this.pillState = "complete";
      this.showPill("complete");
      this.hidePill(COMPLETE_STATE_MS);

      this.send();
    }

    // ----- Conversation ----- //

    async appendMessage(role, text) {
      this.messages.querySelector(".ai-assistant__message--intro")?.remove();

      const className =
        role === "user"
          ? "ai-assistant__message ai-assistant__message--user"
          : role === "error"
            ? "ai-assistant__message ai-assistant__message--error"
            : "ai-assistant__message ai-assistant__message--assistant";

      const bubble = createElement("div", className);
      this.messages.append(bubble);

      if (role === "user" || role === "assistant") {
        // Messages are rendered as Markdown (the same strategy the recipe
        // pages use). If rendering fails we show the raw text instead so a
        // failed request never swallows a message.
        bubble.classList.add("ai-assistant__message--rendered");
        try {
          const html = await fetchRenderedMarkdown(text);
          if (html) {
            bubble.innerHTML = html;
            await renderMathInBubble(bubble);
          } else {
            bubble.classList.remove("ai-assistant__message--rendered");
            bubble.textContent = text;
          }
        } catch (error) {
          console.warn("Unable to render the message as Markdown; showing plain text.", error);
          bubble.classList.remove("ai-assistant__message--rendered");
          bubble.textContent = text;
        }
      } else {
        bubble.textContent = text;
      }

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

      await this.appendMessage("user", message);
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
        await this.appendMessage(
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
      await window.RecipeSSE.readEventStream(body, (event) => this.handleEventBlock(event));
    }

    async handleEventBlock(data) {
      const event = data.type;

      if (event === "status") {
        this.setStatus(data?.message || "", true);
        return;
      }

      if (event === "result") {
        await this.handleResult(data);
        return;
      }

      if (event === "error") {
        this.appendMessage("error", data?.message || "The assistant ran into a problem.");
        this.setStatus("", false);
      }
    }

    async handleResult(data) {
      const result = data?.result ?? {};
      const reply =
        typeof result.reply === "string" && result.reply.trim()
          ? result.reply
          : "(The assistant returned an empty reply.)";
      await this.appendMessage("assistant", reply);
      this.rememberTurn("assistant", reply);
      if (result.edited === true) {
        this.appendReloadNotice(result.path);
      }

      // open_recipe asked for a redirect to the closest-matching recipe.
      // Only same-origin absolute paths are honored — the URL comes from
      // the server, but validate it anyway.
      const open = result.open;
      const url = typeof open?.url === "string" ? open.url : "";
      if (url.startsWith("/") && !url.startsWith("//")) {
        const title = typeof open?.title === "string" && open.title ? open.title : "the recipe";
        this.setStatus(`Opening ${title}…`, false);
        window.setTimeout(() => {
          window.location.assign(url);
        }, OPEN_REDIRECT_DELAY_MS);
        return;
      }

      this.setStatus("", false);
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
