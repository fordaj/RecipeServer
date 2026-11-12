(() => {
  // Tracks the normalized events from /api/ai-recipe and renders the
  // generation status and final metrics. The generated Markdown is written to
  // the editor when the result event arrives.

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
    constructor(root) {
      this.root = root;
      this.status = root.querySelector(".recipe-editor__ai-status");
      this.progress = root.querySelector(".recipe-editor__ai-progress");
      this.metrics = root.querySelector(".recipe-editor__ai-metrics");
      this.metricValues = {
        model_load_seconds: root.querySelector(".recipe-editor__ai-metric-model-load"),
        generation_seconds: root.querySelector(".recipe-editor__ai-metric-generation"),
        token_count: root.querySelector(".recipe-editor__ai-metric-tokens"),
        tokens_per_second: root.querySelector(".recipe-editor__ai-metric-rate"),
      };

      this.state = "idle";
      this.reset();
    }

    reset() {
      this.state = "idle";
      if (this.progress) this.progress.hidden = true;
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
        return;
      }

      if (event.type === "metrics") {
        this.renderMetrics(event.metrics);
        return;
      }

      if (event.type === "error") {
        this.setStatus(event.message || STATUS_MESSAGES.error, "error");
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

  function createProgress(root) {
    return new AiProgress(root);
  }

  window.RecipeAIProgress = { createProgress };
})();
