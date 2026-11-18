// Version History (Timeline). A dialog listing the recipe's previous
// versions in reverse chronological order, with a preview (rendered through
// the server's existing Markdown pipeline), a line-based diff against the
// current version, and a reversible restore. Opened via window.RecipeTimeline.
(() => {
  const LIST_API = "/api/history";
  const PREVIEW_API = "/api/history/preview";
  const COMPARE_API = "/api/history/compare";
  const RESTORE_API = "/api/history/restore";
  const TIMELINE_CSS_URL = "/assets/recipe-history/timeline.css";
  const TIMELINE_CSS_ID = "recipe-history-timeline-css";
  const RESTORE_CONFIRM_WINDOW_MS = 4000;

  // The recipe this page renders; the markdown path is the page URL with the
  // extension swapped, matching the other page scripts.
  function markdownPathFromLocation() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  function ensureStylesheet() {
    if (document.getElementById(TIMELINE_CSS_ID)) return;
    const link = document.createElement("link");
    link.id = TIMELINE_CSS_ID;
    link.rel = "stylesheet";
    link.href = TIMELINE_CSS_URL;
    document.head.appendChild(link);
  }

  function formatSize(bytes) {
    if (!Number.isFinite(bytes)) return "";
    if (bytes < 1024) return `${bytes} B`;
    const kilobytes = bytes / 1024;
    if (kilobytes < 1024) return `${kilobytes.toFixed(1)} KB`;
    return `${(kilobytes / 1024).toFixed(1)} MB`;
  }

  function fullDate(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
  }

  function dateLabel(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return { date: iso, time: "" };
    const currentYear = new Date().getFullYear();
    const dateOptions = { month: "short", day: "numeric" };
    if (date.getFullYear() !== currentYear) dateOptions.year = "numeric";
    const timeOptions = { hour: "numeric", minute: "2-digit" };
    return {
      date: date.toLocaleDateString(undefined, dateOptions),
      time: date.toLocaleTimeString(undefined, timeOptions),
    };
  }

  function fetchJson(url, options) {
    return fetch(url, options).then((response) =>
      response
        .json()
        .catch(() => ({}))
        .then((body) => {
          if (!response.ok) {
            throw new Error(body.error || `Request failed (HTTP ${response.status})`);
          }
          return body;
        }),
    );
  }

  function buildDialog() {
    const dialog = document.createElement("dialog");
    dialog.className = "recipe-history-dialog";
    dialog.setAttribute("aria-labelledby", "recipe-history-title");
    dialog.innerHTML = `
      <div class="recipe-history">
      <header class="recipe-history__header">
        <h2 id="recipe-history-title">Version History</h2>
        <button type="button" class="recipe-history__close" aria-label="Close version history">&times;</button>
      </header>
      <div class="recipe-history__body">
        <nav class="recipe-history__rail" aria-label="Previous versions">
          <h3>Timeline</h3>
          <ul class="recipe-history__list"></ul>
        </nav>
        <section class="recipe-history__viewer" aria-label="Selected version">
          <div class="recipe-history__toolbar">
            <span class="recipe-history__toolbar-title"></span>
            <button type="button" class="recipe-history__action recipe-history__mode" data-mode="preview" aria-pressed="true">Preview</button>
            <button type="button" class="recipe-history__action recipe-history__mode" data-mode="compare" aria-pressed="false">Compare</button>
            <button type="button" class="recipe-history__action recipe-history__restore">Restore</button>
          </div>
          <div class="recipe-history__content">
            <iframe class="recipe-history__preview" title="Historical recipe preview" sandbox="allow-same-origin"></iframe>
            <pre class="recipe-history__diff" hidden></pre>
            <div class="recipe-history__empty" hidden>
              <p><strong>No previous versions yet.</strong></p>
              <p>Every time RecipeServer changes this recipe it keeps the previous version here, so you can recover from edits at any time.</p>
            </div>
          </div>
        </section>
      </div>
      <p class="recipe-history__status" role="status"></p>
      </div>
    `;
    document.body.appendChild(dialog);
    return dialog;
  }

  // Colourise a unified diff for readability. Lines are added as DOM nodes
  // with textContent, so no markup from the recipe can leak into the page.
  function renderDiff(diffElement, diffText) {
    diffElement.replaceChildren();
    const fragment = document.createDocumentFragment();
    for (const line of diffText.split("\n")) {
      const span = document.createElement("span");
      if (line.startsWith("@@")) {
        span.className = "recipe-history__diff-line--hunk";
      } else if (line.startsWith("+") && !line.startsWith("+++")) {
        span.className = "recipe-history__diff-line--add";
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        span.className = "recipe-history__diff-line--del";
      }
      span.textContent = `${line}\n`;
      fragment.appendChild(span);
    }
    diffElement.appendChild(fragment);
  }

  function createTimeline() {
    const dialog = buildDialog();
    const list = dialog.querySelector(".recipe-history__list");
    const toolbarTitle = dialog.querySelector(".recipe-history__toolbar-title");
    const modeButtons = [...dialog.querySelectorAll(".recipe-history__mode")];
    const restoreButton = dialog.querySelector(".recipe-history__restore");
    const previewFrame = dialog.querySelector(".recipe-history__preview");
    const diffElement = dialog.querySelector(".recipe-history__diff");
    const emptyState = dialog.querySelector(".recipe-history__empty");
    const status = dialog.querySelector(".recipe-history__status");
    const markdownPath = markdownPathFromLocation();

    const state = {
      snapshots: [],
      selected: null,
      mode: "preview",
      restoreArmedUntil: 0,
    };

    const setStatus = (message) => {
      status.textContent = message || "";
    };

    const selectedSnapshot = () =>
      state.snapshots.find((snapshot) => snapshot.id === state.selected) || null;

    const disarmRestore = () => {
      state.restoreArmedUntil = 0;
      restoreButton.textContent = "Restore";
      restoreButton.classList.remove("recipe-history__restore--confirm");
    };

    const applyMode = () => {
      for (const button of modeButtons) {
        const active = button.dataset.mode === state.mode;
        button.setAttribute("aria-pressed", String(active));
        button.classList.toggle("recipe-history__action--pressed", active);
      }
      previewFrame.hidden = state.mode !== "preview";
      diffElement.hidden = state.mode !== "compare";
    };

    const showViewer = () => {
      const snapshot = selectedSnapshot();
      const hasSelection = Boolean(snapshot);
      emptyState.hidden = hasSelection || state.snapshots.length > 0;
      previewFrame.hidden = !hasSelection || state.mode !== "preview";
      diffElement.hidden = !hasSelection || state.mode !== "compare";
      for (const button of modeButtons) button.disabled = !hasSelection;
      restoreButton.disabled = !hasSelection;

      if (!hasSelection) {
        toolbarTitle.textContent = state.snapshots.length ? "Current version" : "No versions yet";
        toolbarTitle.title = "";
        return;
      }

      toolbarTitle.textContent = fullDate(snapshot.created);
      toolbarTitle.title = `Snapshot ${snapshot.id} · ${formatSize(snapshot.size)}`;
      if (state.mode === "preview") {
        previewFrame.src = `${PREVIEW_API}?path=${encodeURIComponent(markdownPath)}&snapshot=${encodeURIComponent(snapshot.id)}`;
      }
    };

    const renderList = () => {
      list.replaceChildren();

      // The current version always heads the timeline, clearly marked.
      const currentItem = document.createElement("li");
      currentItem.className = "recipe-history__entry recipe-history__entry--current";
      const currentButton = document.createElement("div");
      currentButton.className = "recipe-history__item recipe-history__item--current";
      const badge = document.createElement("span");
      badge.className = "recipe-history__current-badge";
      badge.textContent = "Current";
      const currentMeta = document.createElement("span");
      currentMeta.className = "recipe-history__meta";
      currentMeta.textContent = "This is the live version of the recipe";
      currentButton.append(badge, currentMeta);
      currentItem.appendChild(currentButton);
      list.appendChild(currentItem);

      for (const snapshot of state.snapshots) {
        const labels = dateLabel(snapshot.created);
        const item = document.createElement("li");
        item.className = "recipe-history__entry";
        if (snapshot.id === state.selected) item.classList.add("recipe-history__entry--selected");

        const button = document.createElement("button");
        button.type = "button";
        button.className = "recipe-history__item";
        button.dataset.snapshotId = snapshot.id;
        button.setAttribute("aria-pressed", String(snapshot.id === state.selected));
        button.title = fullDate(snapshot.created);
        const dateChip = document.createElement("span");
        dateChip.className = "recipe-history__date";
        dateChip.append(labels.date);
        if (labels.time) {
          const small = document.createElement("small");
          small.textContent = labels.time;
          dateChip.appendChild(small);
        }
        const meta = document.createElement("span");
        meta.className = "recipe-history__meta";
        meta.textContent = formatSize(snapshot.size);
        button.append(dateChip, meta);
        button.addEventListener("click", () => {
          state.selected = snapshot.id;
          disarmRestore();
          renderList();
          showViewer();
          if (state.mode === "compare") loadCompare();
        });
        item.appendChild(button);
        list.appendChild(item);
      }
    };

    const loadCompare = async () => {
      const snapshot = selectedSnapshot();
      if (!snapshot) return;
      setStatus("Building the diff…");
      try {
        const result = await fetchJson(
          `${COMPARE_API}?path=${encodeURIComponent(markdownPath)}&snapshot=${encodeURIComponent(snapshot.id)}`,
        );
        renderDiff(diffElement, result.diff || "");
        setStatus("Additions are highlighted green, removals red, relative to the current recipe.");
      } catch (error) {
        diffElement.replaceChildren();
        const line = document.createElement("span");
        line.textContent = `Unable to build the diff: ${error.message}`;
        diffElement.appendChild(line);
        setStatus("");
      }
    };

    const refresh = async () => {
      setStatus("Loading versions…");
      try {
        const result = await fetchJson(`${LIST_API}?path=${encodeURIComponent(markdownPath)}`);
        state.snapshots = Array.isArray(result.snapshots) ? result.snapshots : [];
        if (state.selected && !state.snapshots.some((snapshot) => snapshot.id === state.selected)) {
          state.selected = null;
        }
        if (!state.selected && state.snapshots.length > 0) {
          state.selected = state.snapshots[0].id;
        }
        renderList();
        showViewer();
        setStatus(
          state.snapshots.length
            ? `${state.snapshots.length} previous version${state.snapshots.length === 1 ? "" : "s"} available.`
            : "",
        );
        if (state.mode === "compare" && state.selected) loadCompare();
      } catch (error) {
        state.snapshots = [];
        state.selected = null;
        renderList();
        showViewer();
        emptyState.hidden = true;
        setStatus(`Unable to load version history: ${error.message}`);
      }
    };

    for (const button of modeButtons) {
      button.addEventListener("click", () => {
        if (button.dataset.mode === state.mode) return;
        state.mode = button.dataset.mode;
        applyMode();
        showViewer();
        if (state.mode === "compare") loadCompare();
        else setStatus("");
      });
    }

    restoreButton.addEventListener("click", async () => {
      const snapshot = selectedSnapshot();
      if (!snapshot) return;

      // Two-step confirm: first click arms, second click restores.
      if (Date.now() > state.restoreArmedUntil) {
        state.restoreArmedUntil = Date.now() + RESTORE_CONFIRM_WINDOW_MS;
        restoreButton.textContent = "Confirm restore";
        restoreButton.classList.add("recipe-history__restore--confirm");
        setStatus("Restoring keeps the current version as a new snapshot, so this is reversible.");
        return;
      }

      restoreButton.disabled = true;
      setStatus("Restoring…");
      try {
        await fetchJson(RESTORE_API, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: markdownPath, snapshot: snapshot.id }),
        });
        setStatus("Restored. Reloading…");
        window.setTimeout(() => window.location.reload(), 350);
      } catch (error) {
        disarmRestore();
        restoreButton.disabled = false;
        setStatus(`Unable to restore: ${error.message}`);
      }
    });

    dialog.querySelector(".recipe-history__close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      // A full press on the backdrop closes the dialog.
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dialog.close();
    });

    return { dialog, refresh };
  }

  let instance = null;

  function open() {
    ensureStylesheet();
    if (!instance) instance = createTimeline();
    instance.refresh();
    if (!instance.dialog.open) instance.dialog.showModal();
  }

  // Bind the sandwich-menu "Timeline" entry (rendered on recipe pages by
  // menu.py with data-timeline="open"). The menu closes behind the dialog,
  // like the Edit Recipe entry closes before the editor opens.
  function bindMenuEntry() {
    document.querySelectorAll('[data-timeline="open"]').forEach((entry) => {
      entry.addEventListener("click", () => {
        const menu = entry.closest(".sandwich-menu");
        if (menu) {
          const panel = menu.querySelector(".sandwich-menu__panel");
          const toggle = menu.querySelector(".sandwich-menu__toggle");
          if (panel) panel.hidden = true;
          if (toggle) toggle.setAttribute("aria-expanded", "false");
        }
        open();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindMenuEntry);
  } else {
    bindMenuEntry();
  }

  function close() {
    if (instance?.dialog.open) instance.dialog.close();
  }

  window.RecipeTimeline = { open, close };
})();
