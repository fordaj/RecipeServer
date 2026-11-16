(() => {
  // ----- Name dropdowns ----- //
  // The comment/rating forms offer every name that is already used in the
  // library as a dropdown (plus "Add new…"), the same widget the recipe
  // editor uses. The options are re-read from the server every time a form
  // opens, so a name that was just used on another recipe shows up right
  // away.

  function fetchMetadataOptions() {
    return fetch("/api/metadata-options", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load metadata options (HTTP ${response.status})`);
        }
        return response.json();
      })
      .then((data) => data?.options ?? {})
      .catch((error) => {
        // Without the library values the dropdowns only offer "Add new…".
        console.error("Unable to load metadata options:", error);
        return {};
      });
  }

  // Build the dropdown for a .recipe-editor__picker element that holds
  // library names. Options are applied by refreshNameOptions, usually when
  // the surrounding form opens.
  function createNamePicker(element) {
    if (!window.RecipeMetadataPicker?.MetadataPicker) {
      throw new Error("metadata-picker.js must load before the feedback scripts");
    }
    return new window.RecipeMetadataPicker.MetadataPicker(element);
  }

  function refreshNameOptions(picker, field) {
    return fetchMetadataOptions().then((options) => picker.setOptions(options?.[field] ?? []));
  }

  // ----- Remembering who this device is ----- //
  // The last name used on this device is kept in localStorage so the device
  // remembers who it is talking to. Storage may be unavailable (private
  // mode, quota), so read and write are best-effort.
  function getStoredName(storageKey) {
    try {
      return String(window.localStorage?.getItem(storageKey) ?? "").trim();
    } catch {
      return "";
    }
  }

  function setStoredName(storageKey, name) {
    try {
      window.localStorage?.setItem(storageKey, String(name));
    } catch {
      // Remembering the name is best-effort.
    }
  }

  // ----- Path helpers ----- //
  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  // ----- Identity helpers ----- //
  function createId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }

    // UUID v4 fallback for browsers or contexts without randomUUID().
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
      const random = (Math.random() * 16) | 0;
      const value = character === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }

  // ----- Name and date helpers ----- //
  function getInitials(name) {
    return String(name || "")
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase())
      .join("");
  }

  function formatDateText(timestamp) {
    if (typeof timestamp !== "string" || !timestamp) {
      return "";
    }

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
      return timestamp;
    }

    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }

  function createDateElement(timestamp, className) {
    const dateElement = document.createElement("time");
    if (className) {
      dateElement.className = className;
    }
    if (typeof timestamp === "string" && timestamp) {
      dateElement.dateTime = timestamp;
      dateElement.textContent = formatDateText(timestamp);
    }
    return dateElement;
  }

  function sortByUpdatedDesc(items) {
    return [...items].sort((a, b) => {
      const timestampA = Date.parse((a && (a.updated || a.created)) || "") || 0;
      const timestampB = Date.parse((b && (b.updated || b.created)) || "") || 0;
      return timestampB - timestampA;
    });
  }

  // ----- Network helpers ----- //
  async function fetchMetadata(field, recipePath) {
    const params = new URLSearchParams({ path: recipePath });
    const response = await fetch(`/api/metadata/${field}?${params}`);

    if (!response.ok) {
      throw new Error(`Failed to load ${field} (HTTP ${response.status})`);
    }

    const data = await response.json();
    if (!Array.isArray(data.value)) {
      throw new Error(`Invalid ${field} response`);
    }

    return data.value;
  }

  async function saveMetadata(field, recipePath, value) {
    const response = await fetch(`/api/metadata/${field}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: recipePath, value }),
    });
    const result = await response.json().catch(() => ({}));

    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save ${field} (HTTP ${response.status})`);
    }
  }

  // ----- Busy state and inline errors ----- //
  // One busy-state convention for the feedback features: while an operation
  // is in flight, every button, input, select, and textarea inside the
  // container is disabled so it cannot be used twice.
  function setBusy(container, busy) {
    container.querySelectorAll("button, input, select, textarea").forEach((element) => {
      element.disabled = busy;
    });
  }

  // Errors are shown inline, next to the comment/rating or form they belong
  // to, instead of with blocking alert() dialogs. Reuses the form's own
  // status element when one is present.
  function showInlineError(container, errorMessage, className) {
    let message = container.querySelector(`.${className}`);
    if (!message) {
      message = document.createElement("p");
      message.className = className;
      message.setAttribute("role", "status");
      container.append(message);
    }
    message.textContent = errorMessage;
  }

  // ----- Feedback list skeleton ----- //
  // Shared CRUD wiring for the user-entry lists (comments, ratings): list
  // click delegation, render-with-empty-toggle, confirm-then-delete, and the
  // edit-form scaffold. Feature-specific rendering, validation, and inputs
  // are supplied by the caller.
  function createFeedbackList({
    root,
    list,
    kind,
    confirmDeleteMessage,
    fetchItems,
    saveItems,
    createItem,
    buildEditForm,
    submitEdit,
    onRender,
  }) {
    const contentSelector = `.recipe-${kind}__content`;
    const statusClass = `recipe-${kind}__status`;
    const noun = kind.charAt(0).toUpperCase() + kind.slice(1);

    function articleContent(article) {
      return article.querySelector(contentSelector) || article;
    }

    function renderAll(items) {
      list.replaceChildren(...sortByUpdatedDesc(items).map((item) => createItem(item)));
      root.classList.toggle("is-empty", items.length === 0);
      if (onRender) {
        onRender(items);
      }
    }

    async function editItem(article) {
      const itemId = article.dataset.feedbackId;
      const items = await fetchItems();
      const index = items.findIndex((item) => item.id === itemId);
      if (index === -1) {
        throw new Error(`${noun} no longer exists. Reload the page.`);
      }

      const item = items[index];
      const content = articleContent(article);
      const controls = buildEditForm(item);
      content.replaceChildren(controls.form);

      controls.cancel.addEventListener("click", () => {
        article.replaceWith(createItem(item));
      });

      controls.form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBusy(article, true);
        try {
          const updated = await submitEdit({ item, index, items, controls });
          if (updated == null) {
            // Submit handler chose not to proceed (e.g. invalid input that
            // was reported through reportValidity()).
            setBusy(article, false);
            return;
          }
          await saveItems(updated);
          renderAll(updated);
        } catch (error) {
          console.error(`Unable to edit ${kind}:`, error);
          setBusy(article, false);
          showInlineError(
            controls.form,
            error.message || `Unable to save this ${kind}.`,
            statusClass,
          );
        }
      });

      if (controls.focus) {
        controls.focus();
      }
    }

    async function deleteItem(article) {
      if (!window.confirm(confirmDeleteMessage)) {
        return;
      }

      setBusy(article, true);
      try {
        const items = await fetchItems();
        const itemId = article.dataset.feedbackId;
        const updated = items.filter((item) => item.id !== itemId);
        if (updated.length === items.length) {
          throw new Error(`${noun} no longer exists.`);
        }
        await saveItems(updated);
        renderAll(updated);
      } catch (error) {
        console.error(`Unable to delete ${kind}:`, error);
        setBusy(article, false);
        showInlineError(
          articleContent(article),
          error.message || `Unable to delete this ${kind}.`,
          statusClass,
        );
      }
    }

    list.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button || !list.contains(button)) return;

      const article = button.closest(`.recipe-${kind}`);
      if (!article) return;

      if (button.dataset.action === "edit") {
        try {
          await editItem(article);
        } catch (error) {
          console.error(`Unable to edit ${kind}:`, error);
          showInlineError(
            articleContent(article),
            error.message || `Unable to edit this ${kind}.`,
            statusClass,
          );
        }
      } else if (button.dataset.action === "delete") {
        await deleteItem(article);
      }
    });

    return { renderAll, articleContent };
  }

  window.RecipeFeedback = {
    getMarkdownPath,
    createId,
    getInitials,
    formatDateText,
    createDateElement,
    sortByUpdatedDesc,
    fetchMetadata,
    saveMetadata,
    fetchMetadataOptions,
    createNamePicker,
    refreshNameOptions,
    getStoredName,
    setStoredName,
    setBusy,
    showInlineError,
    createFeedbackList,
  };
})();
