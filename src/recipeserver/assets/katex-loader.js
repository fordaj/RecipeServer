// One lazy KaTeX loader for the assistant chat and the shopping list.
//
// Recipe pages load KaTeX eagerly; these two dialogs load it on demand. The
// assistant also needs auto-render, while the shopping list typesets scaled
// quantities directly through RecipeScaler. One loader handles both, retries
// after a failed load, and never keeps a rejected promise cached.

(function () {
  "use strict";

  const CSS_URL = "/assets/katex/dist/katex.min.css";
  const JS_URL = "/assets/katex/dist/katex.min.js";
  const AUTO_RENDER_URL = "/assets/katex/dist/contrib/auto-render.min.js";
  const SCRIPT_LOAD_TIMEOUT_MS = 8000;

  let pending = null;

  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${url}"]`);
      if (existing && existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      // A tag that failed (or timed out) cannot fire load again; drop it so a
      // later call can retry with a fresh request.
      if (existing && existing.dataset.loaded === "false") existing.remove?.();

      const script =
        existing && existing.dataset.loaded !== "false"
          ? existing
          : document.createElement("script");
      let timeout = 0;
      const cleanup = () => window.clearTimeout(timeout);
      const fail = (message) => {
        cleanup();
        script.dataset.loaded = "false";
        script.remove?.();
        reject(new Error(message));
      };

      script.addEventListener("load", () => {
        cleanup();
        script.dataset.loaded = "true";
        resolve();
      });
      script.addEventListener("error", () => fail(`Unable to load ${url}`));
      timeout = window.setTimeout(() => {
        // The tag may have loaded eagerly (and failed) before this dialog ever
        // opened; bound the wait so the loader can retry.
        fail(`Timed out loading ${url}`);
      }, SCRIPT_LOAD_TIMEOUT_MS);

      const needsAppend =
        script !== existing || (existing !== null && existing.dataset.loaded === "false");
      if (needsAppend) {
        script.src = url;
        script.defer = true;
        document.head.append(script);
      }
    });
  }

  function ensureStylesheet() {
    if (document.querySelector(`link[href="${CSS_URL}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = CSS_URL;
    document.head.append(link);
  }

  function ready(autoRender) {
    return (
      typeof window.katex?.render === "function" &&
      (!autoRender || typeof window.renderMathInElement === "function")
    );
  }

  function ensureKatex(options = {}) {
    const autoRender = options.autoRender === true;
    if (ready(autoRender)) return Promise.resolve();
    if (pending) return pending;

    pending = (async () => {
      ensureStylesheet();
      if (typeof window.katex?.render !== "function") await loadScript(JS_URL);
      if (autoRender && typeof window.renderMathInElement !== "function")
        await loadScript(AUTO_RENDER_URL);
    })().catch((error) => {
      pending = null;
      throw error;
    });

    return pending;
  }

  window.RecipeKatexLoader = { ensureKatex };
})();
