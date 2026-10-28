(() => {
  const EDITOR_ID = "recipe-markdown-editor";

  function createEditor() {
    const dialog = document.createElement("dialog");
    dialog.id = EDITOR_ID;
    dialog.className = "recipe-editor-dialog";

    dialog.innerHTML = `
            <form class="recipe-editor" method="dialog">
                <header class="recipe-editor__header">
                    <h2>Edit Recipe</h2>
                    <button type="button" class="recipe-editor__close"
                        aria-label="Close editor">&times;</button>
                </header>

                <p class="recipe-editor__status" role="status"></p>

                <details class="recipe-editor__details" open>
                    <summary>Recipe Details</summary>

                    <fieldset class="recipe-editor__metadata">
                        <label>
                            Tags
                            <input name="tags" type="text"
                                placeholder="Chocolate, Sweet">
                        </label>

                        <label>
                            Cuisine
                            <input name="cuisine" type="text"
                                placeholder="American">
                        </label>

                        <label>
                            Categories
                            <input name="category" type="text"
                                placeholder="ex. Slow Cooker, Meat">
                        </label>

                        <label>
                            Meals
                            <input name="meals" type="text"
                                placeholder="ex. Dessert, Snack">
                        </label>

                        <div class="recipe-editor__numeric">
                            <label>
                                Makes
                                <input name="makes" type="number"
                                    step="1" placeholder="0">
                            </label>

                            <label>
                                Difficulty
                                <input name="difficulty" type="number"
                                    step="any" placeholder="2.5">
                            </label>
                        </div>
                    </fieldset>
                </details>

                <label class="recipe-editor__markdown-label"
                    for="recipe-editor-source">Markdown</label>

                <textarea id="recipe-editor-source"
                    class="recipe-editor__source"
                    aria-label="Markdown source"
                    spellcheck="false" required></textarea>
                <footer class="recipe-editor__footer">
                    <button type="button" class="recipe-editor__cancel">
                        Cancel
                    </button>
                    <button type="submit" class="recipe-editor__save">
                        Save
                    </button>
                </footer>
            </form>
        `;

    document.body.append(dialog);
    return dialog;
  }

  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));

    return page.replace(/\.html$/i, ".md");
  }

  async function requestEditor(path, payload = null) {
    const url = new URL("/api/recipe-editor", window.location.origin);

    if (payload === null) {
      url.searchParams.set("path", path);
    }

    const response = await fetch(url, {
      method: payload === null ? "GET" : "POST",
      cache: "no-store",
      headers: payload === null ? {} : { "Content-Type": "application/json" },
      body: payload === null ? undefined : JSON.stringify({ path, ...payload }),
    });

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result;
  }

  function listToInput(value) {
    return Array.isArray(value) ? value.join(", ") : "";
  }

  function populateMetadata(form, metadata) {
    for (const field of ["tags", "cuisine", "category", "meals", "makes", "difficulty"]) {
      const input = form.elements.namedItem(field);
      const value = metadata[field];

      if (["tags", "category", "meals", "cuisine"].includes(field)) {
        input.value = listToInput(value);
      } else {
        input.value = value == null ? "" : String(value);
      }
    }
  }

  function readMetadata(form) {
    const get = (field) => form.elements.namedItem(field).value.trim();

    const parseList = (field) => {
      const value = get(field);

      if (!value) return null;

      return value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    };

    const parseNumber = (field, integer = false) => {
      const value = get(field);

      if (!value) return null;

      const number = Number(value);

      if (!Number.isFinite(number) || (integer && !Number.isInteger(number))) {
        throw new Error(
          `${field} must be a valid ${integer ? "integer" : "number"}, or left blank.`,
        );
      }

      return number;
    };

    return {
      tags: parseList("tags"),
      cuisine: parseList("cuisine"),
      category: parseList("category"),
      meals: parseList("meals"),
      makes: parseNumber("makes", true),
      difficulty: parseNumber("difficulty"),
    };
  }

  function initialize() {
    const button = document.querySelector("#edit-recipe");
    if (!button) return;

    const dialog = createEditor();
    const form = dialog.querySelector("form");
    const textarea = dialog.querySelector(".recipe-editor__source");
    const status = dialog.querySelector(".recipe-editor__status");
    const saveButton = dialog.querySelector(".recipe-editor__save");
    const cancelButton = dialog.querySelector(".recipe-editor__cancel");
    const closeButton = dialog.querySelector(".recipe-editor__close");

    let originalContent = "";
    let originalMetadata = "";
    let busy = false;
    let scrollY = 0;

    function lockBackgroundScroll() {
      scrollY = window.scrollY;
      document.body.style.position = "fixed";
      document.body.style.top = `-${scrollY}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.width = "100%";
    }

    function unlockBackgroundScroll() {
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      window.scrollTo(0, scrollY);
    }

    function setBusy(value) {
      busy = value;
      saveButton.disabled = value;
      cancelButton.disabled = value;
      closeButton.disabled = value;
      textarea.readOnly = value;
      button.disabled = value;

      form.querySelectorAll(".recipe-editor__metadata input").forEach((input) => {
        input.disabled = value;
      });
    }

    function closeEditor() {
      if (!busy && dialog.open) dialog.close();
    }

    async function openEditor() {
      if (busy) return;

      document.body.classList.add("recipe-editor-open");
      lockBackgroundScroll();
      dialog.showModal();

      status.textContent = "Loading recipe…";
      textarea.value = "";
      setBusy(true);

      try {
        const result = await requestEditor(getMarkdownPath());

        originalContent = result.content;
        originalMetadata = JSON.stringify(result.metadata);

        textarea.value = result.content;
        populateMetadata(form, result.metadata);

        status.textContent = "";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    }

    dialog.addEventListener("close", () => {
      document.body.classList.remove("recipe-editor-open");
      unlockBackgroundScroll();
    });

    button.addEventListener("click", openEditor);
    cancelButton.addEventListener("click", closeEditor);
    closeButton.addEventListener("click", closeEditor);

    dialog.addEventListener("cancel", (event) => {
      if (busy) event.preventDefault();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy) return;

      let metadata;

      try {
        metadata = readMetadata(form);
      } catch (error) {
        status.textContent = error.message;
        return;
      }

      const content = textarea.value;
      const metadataContent = JSON.stringify(metadata);

      if (content === originalContent && metadataContent === originalMetadata) {
        dialog.close();
        return;
      }

      setBusy(true);
      status.textContent = "Saving recipe…";

      try {
        await requestEditor(getMarkdownPath(), {
          content,
          metadata,
        });

        status.textContent = "Saved! Reloading…";
        window.location.reload();
      } catch (error) {
        status.textContent = error.message;
        setBusy(false);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
