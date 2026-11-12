(() => {
  // Tracks the normalized events from /api/ai-recipe and renders the
  // generation status, streamed Markdown, optional thinking output, and final
  // metrics. Content is batched to keep the preview from re-rendering on every
  // token, while status transitions are applied immediately.

  const DEFAULT_FLUSH_INTERVAL = 400;

  const STATUS_MESSAGES = {
    checking_model: "Checking model status...",
    loading_model: "Loading model into memory...",
    preparing: "Preparing the recipe...",
    thinking: "Thinking...",
    generating: "Generating...",
    complete: "Generation complete.",
    error: "Generation failed.",
  };

  function formatSeconds(value) {
    return `${Number(value).toFixed(2)} s`;
  }

  function formatTokenCount(value) {
    return `${Number(value).toLocaleString()} tokens`;
  }

  function formatRate(value) {
    return `${Number(value).toFixed(1)} tok/s`;
  }

  class AiProgress {
    constructor(root, options = {}) {
      this.root = root;
      this.flushInterval = options.flushInterval ?? DEFAULT_FLUSH_INTERVAL;
      this.schedule = options.schedule ?? ((callback, delay) => setTimeout(callback, delay));
      this.cancel = options.cancel ?? ((handle) => clearTimeout(handle));

      this.status = root.querySelector(".recipe-editor__ai-status");
      this.progress = root.querySelector(".recipe-editor__ai-progress");
      this.preview = root.querySelector(".recipe-editor__ai-preview");
      this.thinkingDetails = root.querySelector(".recipe-editor__ai-thinking");
      this.thinkingText = root.querySelector(".recipe-editor__ai-thinking-text");
      this.metrics = root.querySelector(".recipe-editor__ai-metrics");
      this.metricValues = {
        model_load_seconds: root.querySelector(".recipe-editor__ai-metric-model-load"),
        generation_seconds: root.querySelector(".recipe-editor__ai-metric-generation"),
        token_count: root.querySelector(".recipe-editor__ai-metric-tokens"),
        tokens_per_second: root.querySelector(".recipe-editor__ai-metric-rate"),
      };

      this.state = "idle";
      this.contentBuffer = "";
      this.contentRendered = "";
      this.thinkingBuffer = "";
      this.thinkingRendered = "";
      this.timer = null;

      this.reset();
    }

    cancelTimer() {
      if (this.timer !== null) {
        this.cancel(this.timer);
        this.timer = null;
      }
    }

    reset() {
      this.cancelTimer();
      this.state = "idle";
      this.contentBuffer = "";
      this.contentRendered = "";
      this.thinkingBuffer = "";
      this.thinkingRendered = "";

      if (this.progress) this.progress.hidden = true;
      if (this.preview) {
        this.preview.textContent = "";
        this.preview.hidden = true;
      }
      if (this.thinkingDetails) {
        this.thinkingDetails.hidden = true;
        this.thinkingDetails.open = false;
      }
      if (this.thinkingText) this.thinkingText.textContent = "";
      if (this.metrics) this.metrics.hidden = true;
      for (const element of Object.values(this.metricValues)) {
        if (element) element.textContent = "";
      }
      this.setStatus("");
    }

    showProgress() {
      if (this.progress) this.progress.hidden = false;
    }

    setStatus(message, state = this.state) {
      this.state = state;
      if (this.status && this.status.textContent !== message) {
        this.status.textContent = message;
      }
    }

    start(message) {
      this.reset();
      this.showProgress();
      this.setStatus(message, "preparing");
    }

    handle(event) {
      if (!event || typeof event.type !== "string") return;

      if (event.type === "status") {
        const message =
          typeof event.message === "string" ? event.message : (STATUS_MESSAGES[event.state] ?? "");
        this.setStatus(message, event.state ?? this.state);
        if (event.state === "complete" || event.state === "error") this.flush();
        return;
      }

      if (event.type === "content") {
        this.appendContent(event.text);
        return;
      }

      if (event.type === "thinking") {
        this.appendThinking(event.text);
        return;
      }

      if (event.type === "metrics") {
        this.renderMetrics(event.metrics);
        return;
      }

      if (event.type === "error") {
        this.flush();
        this.setStatus(event.message || STATUS_MESSAGES.error, "error");
        return;
      }

      if (event.type === "result") {
        this.flush();
      }
    }

    appendContent(text) {
      if (typeof text !== "string" || !text) return;
      this.contentBuffer += text;
      if (this.state !== "generating") {
        this.setStatus(STATUS_MESSAGES.generating, "generating");
      }
      this.showProgress();
      this.scheduleFlush();
    }

    appendThinking(text) {
      if (typeof text !== "string" || !text) return;
      this.thinkingBuffer += text;
      if (this.thinkingDetails) this.thinkingDetails.hidden = false;
      if (this.state !== "thinking" && this.state !== "generating") {
        this.setStatus(STATUS_MESSAGES.thinking, "thinking");
      }
      this.showProgress();
      this.scheduleFlush();
    }

    scheduleFlush() {
      if (this.timer !== null) return;
      this.timer = this.schedule(() => {
        this.timer = null;
        this.flush();
      }, this.flushInterval);
    }

    flush() {
      this.cancelTimer();

      if (this.preview && this.contentBuffer !== this.contentRendered) {
        this.contentRendered = this.contentBuffer;
        this.preview.textContent = this.contentRendered;
        this.preview.hidden = !this.contentRendered;
      }

      if (this.thinkingText && this.thinkingBuffer !== this.thinkingRendered) {
        this.thinkingRendered = this.thinkingBuffer;
        this.thinkingText.textContent = this.thinkingRendered;
      }
      if (this.thinkingDetails) {
        this.thinkingDetails.hidden = !this.thinkingRendered;
      }
    }

    renderMetrics(metrics) {
      if (!metrics || typeof metrics !== "object") return;

      const formatters = {
        model_load_seconds: formatSeconds,
        generation_seconds: formatSeconds,
        token_count: formatTokenCount,
        tokens_per_second: formatRate,
      };

      let hasValue = false;
      for (const [key, element] of Object.entries(this.metricValues)) {
        if (!element) continue;
        const value = metrics[key];
        if (value === undefined || value === null || !Number.isFinite(Number(value))) {
          element.textContent = "";
          continue;
        }
        element.textContent = formatters[key](value);
        hasValue = true;
      }

      if (this.metrics) this.metrics.hidden = !hasValue;
      if (hasValue) this.showProgress();
    }
  }

  function createProgress(root, options) {
    return new AiProgress(root, options);
  }

  window.RecipeAIProgress = { createProgress, DEFAULT_FLUSH_INTERVAL };
})();
