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

                <div class="recipe-editor__location" hidden>
                    <label>
                        Folder
                        <select class="recipe-editor__folder-mode" aria-label="Folder location">
                            <option value="existing">Existing folder</option>
                            <option value="new">New folder</option>
                        </select>
                    </label>
                    <label class="recipe-editor__existing-folder">
                        Choose folder
                        <select class="recipe-editor__folder-select"></select>
                    </label>
                    <label class="recipe-editor__folder-path" hidden>
                        New folder path
                        <input type="text" class="recipe-editor__new-folder"
                            placeholder="Desserts/Chocolate">
                    </label>
                </div>

                <section class="recipe-editor__images" aria-label="Recipe images">
                    <label for="recipe-editor-images">Recipe images</label>
                    <input id="recipe-editor-images" type="file" multiple
                        accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif,.svg,.avif">
                    <p class="recipe-editor__images-help">
                        Images are saved beside the recipe. Up to 20 files and 25 MB per save.
                    </p>
                    <p class="recipe-editor__images-selected" aria-live="polite"></p>
                </section>

                <details class="recipe-editor__details" open>
                    <summary>Details</summary>

                    <fieldset class="recipe-editor__metadata">
                        <label>
                            Contributor
                            <input name="contributor" type="text"
                                placeholder="Andy Ford">
                        </label>

                        <label>
                            Contribution Date
                            <input name="createdOn" type="date">
                        </label>

                        <label>
                            Meals
                            <input name="meals" type="text"
                                placeholder="ex. Breakfast, Dessert">
                        </label>

                        <label>
                            Categories
                            <input name="categories" type="text"
                                placeholder="ex. Slow Cooker, Meat">
                        </label>

                        <label>
                            Cuisine
                            <input name="cuisine" type="text"
                                placeholder="American">
                        </label>

                        <label>
                            Tags
                            <input name="tags" type="text"
                                placeholder="Chocolate, Sweet">
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
                                    step="any" placeholder="5">
                            </label>
                        </div>

                    </fieldset>
                </details>
                    
                    <details class="recipe-editor__details" open>
                        <summary>Sources</summary>

                          <fieldset class="recipe-editor__metadata">

                              <label>
                                  Source Author
                                  <input name="source.author" type="text"
                                      placeholder="FirstName LastName">
                              </label>

                              <label>
                                  Source Title
                                  <input name="source.title" type="text"
                                      placeholder="Book Title, Website Name, AI Model, etc.">
                              </label>

                              <label>
                                  Source Format
                                  <select name="source.format">
                                      <option value="">Select format</option>
                                      <option value="Website">Website</option>
                                      <option value="AI">AI</option>
                                      <option value="Book">Book</option>
                                      <option value="Other">Other</option>
                                  </select>
                              </label>

                              <label>
                                  Source URL
                                  <input name="source.url" type="url"
                                      placeholder="https://example.com">
                              </label>
                          </fieldset>
                </details>

                <label class="recipe-editor__markdown-label"
                    for="recipe-editor-source">Markdown</label>

                <textarea id="recipe-editor-source"
                    class="recipe-editor__source"
                    aria-label="Markdown source"
                    spellcheck="false" required></textarea>
                    

                <p class="recipe-editor__status" role="status"></p>
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

  async function requestEditor(path, payload = null, images = []) {
    const url = new URL("/api/recipe-editor", window.location.origin);

    if (payload === null) {
      url.searchParams.set("path", path);
    }

    const requestBody = payload === null ? null : createRequestBody({ path, ...payload }, images);

    const response = await fetch(url, {
      method: payload === null ? "GET" : "POST",
      cache: "no-store",
      headers: requestBody?.headers ?? {},
      body: requestBody?.body,
    });

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result;
  }

  async function requestRecipeFolders() {
    const response = await fetch(new URL("/api/recipe-folders", window.location.origin), {
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result.folders;
  }

  function createRequestBody(payload, images) {
    if (images.length) {
      const body = new FormData();
      Object.entries(payload).forEach(([key, value]) => {
        body.append(key, typeof value === "string" ? value : JSON.stringify(value));
      });
      images.forEach((image) => body.append("images", image, image.name));
      return { body };
    }

    return {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
  }

  async function createRecipe(folder, createFolder, content, metadata, images) {
    const requestBody = createRequestBody({ folder, createFolder, content, metadata }, images);
    const response = await fetch(new URL("/api/recipe", window.location.origin), {
      method: "POST",
      cache: "no-store",
      headers: requestBody.headers ?? {},
      body: requestBody.body,
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

  function firstSource(source) {
    if (Array.isArray(source)) {
      return source.find((item) => item && typeof item === "object") || {};
    }

    return source && typeof source === "object" ? source : {};
  }

  function populateMetadata(form, metadata) {
    for (const field of ["tags", "cuisine", "categories", "meals", "makes", "difficulty"]) {
      const input = form.elements.namedItem(field);
      const value = metadata[field];

      if (["tags", "categories", "meals", "cuisine"].includes(field)) {
        input.value = listToInput(value);
      } else {
        input.value = value == null ? "" : String(value);
      }
    }

    form.elements.namedItem("contributor").value = metadata.contributor ?? "";

    const createdOn = metadata.createdOn;
    form.elements.namedItem("createdOn").value =
      typeof createdOn === "string" ? createdOn.slice(0, 10) : "";

    const source = firstSource(metadata.source);

    for (const field of ["author", "title", "format", "url"]) {
      form.elements.namedItem(`source.${field}`).value = source[field] ?? "";
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
      categories: parseList("categories"),
      meals: parseList("meals"),
      makes: parseNumber("makes", true),
      difficulty: parseNumber("difficulty"),

      contributor: get("contributor") || null,

      createdOn: get("createdOn") ? `${get("createdOn")}T00:00:00.000Z` : null,

      source: readSource(form),
    };
  }

  function readSource(form) {
    const get = (field) => form.elements.namedItem(field).value.trim();

    const source = {
      author: get("source.author") || null,
      title: get("source.title") || null,
      format: get("source.format") || null,
      url: get("source.url") || null,
    };

    return Object.values(source).some((value) => value !== null) ? source : null;
  }

  function initialize() {
    const editButton = document.querySelector("#edit-recipe");
    const createButton = document.querySelector("#create-recipe");
    if (!editButton && !createButton) return;

    const dialog = createEditor();
    const form = dialog.querySelector("form");
    const textarea = dialog.querySelector(".recipe-editor__source");
    const status = dialog.querySelector(".recipe-editor__status");
    const saveButton = dialog.querySelector(".recipe-editor__save");
    const cancelButton = dialog.querySelector(".recipe-editor__cancel");
    const closeButton = dialog.querySelector(".recipe-editor__close");
    const heading = dialog.querySelector(".recipe-editor__header h2");
    const location = dialog.querySelector(".recipe-editor__location");
    const folderMode = dialog.querySelector(".recipe-editor__folder-mode");
    const folderSelect = dialog.querySelector(".recipe-editor__folder-select");
    const existingFolder = dialog.querySelector(".recipe-editor__existing-folder");
    const folderPathLabel = dialog.querySelector(".recipe-editor__folder-path");
    const newFolder = dialog.querySelector(".recipe-editor__new-folder");
    const imageInput = dialog.querySelector("#recipe-editor-images");
    const selectedImages = dialog.querySelector(".recipe-editor__images-selected");

    let originalContent = "";
    let originalMetadata = "";
    let busy = false;
    let scrollY = 0;
    let activeButton = null;
    let isCreating = false;

    function updateFolderControls() {
      const creatingNewFolder = folderMode.value === "new";
      existingFolder.hidden = creatingNewFolder;
      folderPathLabel.hidden = !creatingNewFolder;
    }

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
      if (activeButton) activeButton.disabled = value;
      folderMode.disabled = value;
      folderSelect.disabled = value;
      newFolder.disabled = value;
      imageInput.disabled = value;

      form
        .querySelectorAll(".recipe-editor__metadata input, .recipe-editor__metadata select")
        .forEach((input) => {
          input.disabled = value;
        });
    }

    function closeEditor() {
      if (!busy && dialog.open) dialog.close();
    }

    async function openEditor(mode) {
      if (busy) return;

      activeButton = mode === "create" ? createButton : editButton;
      isCreating = mode === "create";
      document.body.classList.add("recipe-editor-open");
      lockBackgroundScroll();
      dialog.showModal();

      heading.textContent = isCreating ? "Create Recipe" : "Edit Recipe";
      saveButton.textContent = isCreating ? "Create" : "Save";
      location.hidden = !isCreating;
      status.textContent = isCreating ? "Loading folders…" : "Loading recipe…";
      textarea.value = "";
      originalContent = "";
      originalMetadata = "";
      imageInput.value = "";
      selectedImages.textContent = "";
      setBusy(true);

      try {
        if (isCreating) {
          const folders = await requestRecipeFolders();
          folderSelect.replaceChildren(
            ...folders.map((folder) => {
              const option = document.createElement("option");
              option.value = folder;
              option.textContent = folder || "Recipe root";
              return option;
            }),
          );
          folderMode.value = "existing";
          newFolder.value = "";
          updateFolderControls();
          populateMetadata(form, {});
          textarea.value = `# New Recipe

![Alt Text](image.png)

/// html | div.recipe-meta

Prep Time
: 30 minutes

Cook Time
: 30 minutes

Servings
: \`6 portions\`

/// <!-- recipe-meta -->

## Ingredients

- [ ] \`1/2 cup\` of something

## Preparation

1. Do something

## Tips

Try this
          `;
        } else {
          const result = await requestEditor(getMarkdownPath());
          originalContent = result.content;
          textarea.value = result.content;
          populateMetadata(form, result.metadata);
          originalMetadata = JSON.stringify(readMetadata(form));
        }
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

    dialog.addEventListener("click", (event) => {
      // Close when clicking the backdrop, but not the dialog itself.
      if (event.target === dialog) {
        closeEditor();
      }
    });

    if (editButton) editButton.addEventListener("click", () => openEditor("edit"));
    if (createButton) createButton.addEventListener("click", () => openEditor("create"));
    folderMode.addEventListener("change", updateFolderControls);
    imageInput.addEventListener("change", () => {
      selectedImages.textContent = [...imageInput.files].map((image) => image.name).join(", ");
    });
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
      const images = [...imageInput.files];

      if (
        !isCreating &&
        content === originalContent &&
        metadataContent === originalMetadata &&
        images.length === 0
      ) {
        dialog.close();
        return;
      }

      let folder;
      if (isCreating) {
        folder = folderMode.value === "new" ? newFolder.value.trim() : folderSelect.value;
        if (folderMode.value === "new" && !folder) {
          status.textContent = "Enter a folder path.";
          return;
        }
      }

      setBusy(true);
      status.textContent = isCreating ? "Creating recipe…" : "Saving recipe…";

      try {
        if (isCreating) {
          await createRecipe(folder, folderMode.value === "new", content, metadata, images);
        } else {
          await requestEditor(getMarkdownPath(), { content, metadata }, images);
        }

        status.textContent = isCreating ? "Created! Reloading…" : "Saved! Reloading…";
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
