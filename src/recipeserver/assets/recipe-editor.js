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
                    <span class="recipe-editor__makes-count" hidden>
                        <span class="recipe-editor__makes-icon" aria-hidden="true" focusable="false"></span><span class="recipe-editor__makes-value">x0</span>
                    </span>
                    <button type="button" class="recipe-editor__made-this" hidden>
                        I made this!
                    </button>
                    <button type="button" class="recipe-editor__close"
                        aria-label="Close editor">&times;</button>
                </header>

                <details class="recipe-editor__details">
                    <summary>Files</summary>

                      <fieldset class="recipe-editor__section">
                <div class="recipe-editor__location" hidden>
                    <label>
                        Folder
                        <select class="recipe-editor__folder-mode" aria-label="Folder location">
                            <option value="title">Use recipe title (recommended)</option>
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
 
                    <label for="recipe-editor-images">Recipe images</label>
                    <input id="recipe-editor-images" type="file" multiple
                        accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif,.svg,.avif">
                    <p class="recipe-editor__images-help">
                        Images are saved beside the recipe. Up to 20 files and 25 MB per save.
                    </p>
                    <p class="recipe-editor__images-selected" aria-live="polite"></p> 

                    </fieldset>
                </details>

                
                <details class="recipe-editor__details recipe-editor__ai-details">
                    <summary>Auto-Generate</summary>

                      <fieldset class="recipe-editor__section recipe-editor__ai">
                    <h3>Create from source</h3>
                    <p class="recipe-editor__ai-status" role="status"></p>

                    <button type="button" class="recipe-editor__ai-cancel" hidden>
                        Cancel generation
                    </button>

                    <div class="recipe-editor__ai-field">
                        <label for="recipe-editor-ai-text">From text</label>
                        <textarea id="recipe-editor-ai-text"
                            class="recipe-editor__ai-text" rows="5"
                            placeholder="Paste recipe text here"></textarea>
                        <button type="button" class="recipe-editor__ai-generate-text">
                            Generate from text
                        </button>
                    </div>

                    <div class="recipe-editor__ai-field">
                        <label for="recipe-editor-ai-url">From URL</label>
                        <input id="recipe-editor-ai-url" type="url"
                            class="recipe-editor__ai-url"
                            placeholder="https://example.com/recipe">
                        <button type="button" class="recipe-editor__ai-generate-url">
                            Generate from URL
                        </button>
                    </div>

                    <div class="recipe-editor__ai-field">
                        <label for="recipe-editor-ai-image">From Image</label>
                        <input id="recipe-editor-ai-image" type="file"
                            class="recipe-editor__ai-image"
                            accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.tiff,.tif">
                        <button type="button" class="recipe-editor__ai-generate-image">
                            Generate from image
                        </button>
                    </div> 

                    </fieldset>
                </details>

                <details class="recipe-editor__details">
                    <summary>Details</summary>

                    <fieldset class="recipe-editor__metadata">
                        <label>
                            Contributor
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="contributor" type="text" placeholder="Andy Ford">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="contributor" aria-label="Save contributor to all selected recipes" hidden>Save</button>
                            </span>
                        </label>

                        <label>
                            Contribution Date
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="createdOn" type="date">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="createdOn" aria-label="Save contribution date to all selected recipes" hidden>Save</button>
                            </span>
                        </label>

                        <label>
                            Meals
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="meals" type="text" placeholder="ex. Breakfast, Dessert">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="meals" aria-label="Save meals to all selected recipes" hidden>Save</button>
                            </span>
                        </label>

                        <label>
                            Categories
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="categories" type="text" placeholder="ex. Slow Cooker, Meat">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="categories" aria-label="Save categories to all selected recipes" hidden>Save</button>
                            </span>
                        </label>

                        <label>
                            Cuisine
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="cuisine" type="text" placeholder="American">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="cuisine" aria-label="Save cuisine to all selected recipes" hidden>Save</button>
                            </span>
                        </label>

                        <label>
                            Tags
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="tags" type="text" placeholder="Chocolate, Sweet">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="tags" aria-label="Save tags to all selected recipes" hidden>Save</button>
                            </span>
                        </label>


                        <div class="recipe-editor__numeric">
                            <label>
                                Makes
                                <span class="recipe-editor__mixed" hidden>* MIXED</span>
                                <span class="recipe-editor__field-control">
                                    <input name="makes" type="number" step="1" placeholder="0">
                                    <button type="button" class="recipe-editor__bulk-field-save" data-field="makes" aria-label="Save makes to all selected recipes" hidden>Save</button>
                                </span>
                            </label>

                            <label>
                                Difficulty
                                <span class="recipe-editor__mixed" hidden>* MIXED</span>
                                <span class="recipe-editor__field-control">
                                    <input name="difficulty" type="number" step="any" placeholder="5">
                                    <button type="button" class="recipe-editor__bulk-field-save" data-field="difficulty" aria-label="Save difficulty to all selected recipes" hidden>Save</button>
                                </span>
                            </label>
                        </div>

                    </fieldset>
                </details>
                    
                <details class="recipe-editor__details">
                    <summary>Sources</summary>

                      <fieldset class="recipe-editor__metadata">

                          <label>
                              Source Author
                              <span class="recipe-editor__mixed" hidden>* MIXED</span>
                              <span class="recipe-editor__field-control">
                                  <input name="source.author" type="text" placeholder="First Last">
                                  <button type="button" class="recipe-editor__bulk-field-save" data-field="source" aria-label="Save source to all selected recipes" hidden>Save</button>
                              </span>
                          </label>

                          <label>
                              Source Title
                              <span class="recipe-editor__mixed" hidden>* MIXED</span>
                              <span class="recipe-editor__field-control">
                                  <input name="source.title" type="text" placeholder="Book Title, Website Name, AI Model, etc.">
                                  <button type="button" class="recipe-editor__bulk-field-save" data-field="source" aria-label="Save source to all selected recipes" hidden>Save</button>
                              </span>
                          </label>

                          <label>
                              Source Format
                              <span class="recipe-editor__mixed" hidden>* MIXED</span>
                              <span class="recipe-editor__field-control">
                                  <select name="source.format">
                                      <option value="">Select format</option>
                                      <option value="Website">Website</option>
                                      <option value="AI">AI</option>
                                      <option value="Book">Book</option>
                                      <option value="Other">Other</option>
                                  </select>
                                  <button type="button" class="recipe-editor__bulk-field-save" data-field="source" aria-label="Save source to all selected recipes" hidden>Save</button>
                              </span>
                          </label>

                          <label>
                              Source URL
                              <span class="recipe-editor__mixed" hidden>* MIXED</span>
                              <span class="recipe-editor__field-control">
                                  <input name="source.url" type="url" placeholder="https://example.com">
                                  <button type="button" class="recipe-editor__bulk-field-save" data-field="source" aria-label="Save source to all selected recipes" hidden>Save</button>
                              </span>
                          </label>
                      </fieldset>
                </details>

                <details class="recipe-editor__details recipe-editor__ratings-details" hidden>
                    <summary>Ratings</summary>
                    <fieldset class="recipe-editor__metadata recipe-editor__bulk-rating">
                        <label>
                            Rating name
                            <span class="recipe-editor__mixed" hidden>* MIXED</span>
                            <span class="recipe-editor__field-control">
                                <input name="rating.name" type="text" placeholder="Andy Ford">
                                <button type="button" class="recipe-editor__bulk-field-save" data-field="rating" aria-label="Save rating to all selected recipes" hidden>Save</button>
                            </span>
                        </label>
                        <label>
                            Rating score (0-10)
                            <span class="recipe-editor__field-control">
                                <input name="rating.score" type="number" step="any" min="0" max="10" placeholder="8">
                            </span>
                        </label>
                        <p class="recipe-editor__bulk-help">Saving adds this named rating to every selected recipe, overriding any existing rating with the same name. Use the Save button inside the rating field to save only the rating.</p>
                    </fieldset>
                </details>

                <p class="recipe-editor__bulk-list" hidden></p>

                <details class="recipe-editor__details recipe-editor__markdown-details">
                    <summary>Markdown</summary>

                    <label class="recipe-editor__markdown-label"
                        for="recipe-editor-source">Markdown</label>

                    <textarea id="recipe-editor-source"
                        class="recipe-editor__source"
                        aria-label="Markdown source"
                        spellcheck="false" required></textarea>
                </details>
                    

                <p class="recipe-editor__status" role="status"></p>
                <footer class="recipe-editor__footer">
                    <button type="button" class="recipe-editor__cancel">
                        Cancel
                    </button>
                    <button type="button" class="recipe-editor__delete" hidden>
                        Delete
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

  async function requestBulkEditor(paths) {
    const url = new URL("/api/bulk-editor", window.location.origin);
    for (const path of paths) url.searchParams.append("path", path);
    const response = await fetch(url, { cache: "no-store" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    return result.recipes;
  }

  async function requestBulkSave(paths, payload) {
    const response = await fetch(new URL("/api/bulk-editor", window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, ...payload }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }
    return result;
  }

  async function requestBulkDelete(paths) {
    const response = await fetch(new URL("/api/bulk-delete", window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
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

  async function requestAiStatus() {
    const response = await fetch(new URL("/api/ai-status", window.location.origin), {
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result;
  }

  async function requestAiRecipe(inputType, input, onProgress, signal) {
    let headers = { "Content-Type": "application/json" };
    let body = JSON.stringify({ inputType, input, stream: true });

    if (inputType === "image") {
      // `input` is a File for image uploads; send it as multipart form data.
      body = new FormData();
      body.append("inputType", inputType);
      body.append("stream", "true");
      body.append("image", input, input.name);
      headers = {};
    }

    const response = await fetch(new URL("/api/ai-recipe", window.location.origin), {
      method: "POST",
      cache: "no-store",
      headers,
      body,
      signal,
    });

    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    if (!response.body) {
      throw new Error("The AI progress stream is unavailable.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result;

    async function handleLine(line) {
      if (!line.trim()) return;

      const event = JSON.parse(line);
      if (event.type === "progress" && typeof event.message === "string") {
        onProgress(event.message);
      } else if (event.type === "error" && typeof event.message === "string") {
        throw new Error(event.message);
      } else if (event.type === "result" && event.result) {
        result = event.result;
      } else {
        throw new Error("The AI progress stream returned an invalid event.");
      }
    }

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        await handleLine(line);
      }

      if (done) break;
    }

    await handleLine(buffer);
    if (!result) {
      throw new Error("The AI progress stream ended without a recipe.");
    }

    return result;
  }

  function normalizeMakes(value) {
    // Older recipes may store makes as a list or a numeric string.
    const candidate = Array.isArray(value) ? value[0] : value;
    const number = typeof candidate === "number" ? candidate : Number(candidate);

    if (candidate == null || candidate === "" || !Number.isFinite(number) || number < 0) {
      return 0;
    }

    return Math.floor(number);
  }

  async function getMakes(path) {
    const url = new URL("/api/metadata/makes", window.location.origin);
    url.searchParams.set("path", path);
    const response = await fetch(url, { cache: "no-store" });

    if (response.status === 404) return 0;

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Unable to load makes count (HTTP ${response.status})`);
    }

    return normalizeMakes(result.value);
  }

  async function saveMakes(path, makes) {
    const response = await fetch(new URL("/api/metadata/makes", window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, value: makes }),
    });
    const result = await response.json().catch(() => ({}));

    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save makes count (HTTP ${response.status})`);
    }
  }

  function makesCountLabel(makes) {
    return `x${makes}`;
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

      createdOn: get("createdOn") || null,

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

  // The chef-hat icon lives in assets/chef-hat.svg; load it once and
  // inline it so it can inherit the count's colour via currentColor.
  async function loadSvgIcon(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return "";
      const svg = new DOMParser().parseFromString(
        await response.text(),
        "image/svg+xml",
      ).documentElement;
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      return new XMLSerializer().serializeToString(svg);
    } catch {
      return "";
    }
  }

  async function initialize() {
    const editButton = document.querySelector("#edit-recipe");
    const createButton = document.querySelector("#create-recipe");
    if (!editButton && !createButton) return;

    const dialog = createEditor();
    const makesIcon = dialog.querySelector(".recipe-editor__makes-icon");
    if (makesIcon) {
      makesIcon.innerHTML = await loadSvgIcon("/assets/chef-hat.svg");
    }
    const form = dialog.querySelector("form");
    const textarea = dialog.querySelector(".recipe-editor__source");
    const status = dialog.querySelector(".recipe-editor__status");
    const saveButton = dialog.querySelector(".recipe-editor__save");
    const cancelButton = dialog.querySelector(".recipe-editor__cancel");
    const closeButton = dialog.querySelector(".recipe-editor__close");
    const deleteButton = dialog.querySelector(".recipe-editor__delete");
    const madeThisButton = dialog.querySelector(".recipe-editor__made-this");
    const madeThisCount = dialog.querySelector(".recipe-editor__makes-count");
    const madeThisValue = dialog.querySelector(".recipe-editor__makes-value");
    const markdownDetails = dialog.querySelector(".recipe-editor__markdown-details");
    const header = dialog.querySelector(".recipe-editor__header");
    const heading = dialog.querySelector(".recipe-editor__header h2");
    const location = dialog.querySelector(".recipe-editor__location");
    const folderMode = dialog.querySelector(".recipe-editor__folder-mode");
    const folderSelect = dialog.querySelector(".recipe-editor__folder-select");
    const existingFolder = dialog.querySelector(".recipe-editor__existing-folder");
    const folderPathLabel = dialog.querySelector(".recipe-editor__folder-path");
    const newFolder = dialog.querySelector(".recipe-editor__new-folder");
    const imageInput = dialog.querySelector("#recipe-editor-images");
    const selectedImages = dialog.querySelector(".recipe-editor__images-selected");
    const aiSection = dialog.querySelector(".recipe-editor__ai");
    const aiDetails = dialog.querySelector(".recipe-editor__ai-details");
    const aiStatus = dialog.querySelector(".recipe-editor__ai-status");
    const aiText = dialog.querySelector(".recipe-editor__ai-text");
    const aiUrl = dialog.querySelector(".recipe-editor__ai-url");
    const aiImage = dialog.querySelector(".recipe-editor__ai-image");
    const aiTextButton = dialog.querySelector(".recipe-editor__ai-generate-text");
    const aiUrlButton = dialog.querySelector(".recipe-editor__ai-generate-url");
    const aiImageButton = dialog.querySelector(".recipe-editor__ai-generate-image");
    const aiCancelButton = dialog.querySelector(".recipe-editor__ai-cancel");
    const aiControls = [aiText, aiUrl, aiTextButton, aiUrlButton];
    const aiImageControls = [aiImage, aiImageButton];
    const bulkFieldSaves = [...dialog.querySelectorAll(".recipe-editor__bulk-field-save")];
    const mixedBadges = [...dialog.querySelectorAll(".recipe-editor__mixed")];
    const ratingsDetails = dialog.querySelector(".recipe-editor__ratings-details");
    const bulkList = dialog.querySelector(".recipe-editor__bulk-list");
    const filesDetails = dialog.querySelector(".recipe-editor__details");

    let originalContent = "";
    let originalMetadata = "";
    let busy = false;
    let scrollY = 0;
    let activeButton = null;
    let isCreating = false;
    let isBulk = false;
    let bulkPaths = [];
    let bulkRecipes = [];
    let aiAvailable = false;
    let aiImageAvailable = false;
    let aiAbortController = null;

    function setAiProgress(message) {
      aiStatus.textContent = message;
    }

    function setAiState(
      configured,
      available,
      imageConfigured = available,
      imageAvailable = imageConfigured,
    ) {
      aiAvailable = configured && available;
      aiImageAvailable = configured && imageConfigured && imageAvailable;
      aiSection.hidden = !configured;
      aiDetails.hidden = !configured || !isCreating;
      aiControls.forEach((control) => {
        control.disabled = busy || !aiAvailable;
      });
      aiImageControls.forEach((control) => {
        control.disabled = busy || !aiImageAvailable;
      });

      if (!configured) {
        aiStatus.textContent = "";
      } else if (!available) {
        aiStatus.textContent =
          "The configured local model is unavailable. Start it, then reopen this dialog.";
      } else if (!aiImageAvailable) {
        aiStatus.textContent =
          "The image analysis model is not configured. From Image is unavailable.";
      } else {
        aiStatus.textContent = "";
      }
    }

    function updateFolderControls() {
      const creatingInExistingFolder = folderMode.value === "existing";
      const creatingNewFolder = folderMode.value === "new";
      existingFolder.hidden = !creatingInExistingFolder;
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
      madeThisButton.disabled = value;
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
      bulkFieldSaves.forEach((button) => { button.disabled = value; });

      aiControls.forEach((control) => {
        control.disabled = value || !aiAvailable;
      });
      aiImageControls.forEach((control) => {
        control.disabled = value || !aiImageAvailable;
      });
    }

    function celebrateMadeThis() {
      madeThisButton.classList.remove("is-celebrating");
      // Restart the CSS animation on repeat clicks.
      void madeThisButton.offsetWidth;
      madeThisButton.classList.add("is-celebrating");

      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const sparkles = ["✨", "⭐", "🎉", "💛"];
      const particles = sparkles.map((glyph, index) => {
        const particle = document.createElement("span");
        particle.className = "recipe-editor__sparkle";
        particle.textContent = glyph;
        particle.setAttribute("aria-hidden", "true");
        particle.style.setProperty("--sparkle-x", `${(index - 1.5) * 18}px`);
        particle.style.setProperty("--sparkle-delay", `${index * 60}ms`);
        header.append(particle);
        return particle;
      });

      window.setTimeout(() => {
        particles.forEach((particle) => particle.remove());
        madeThisButton.classList.remove("is-celebrating");
      }, 1000);
    }

    function updateMadeThisCount(makes) {
      madeThisValue.textContent = makesCountLabel(makes);
      madeThisCount.setAttribute("aria-label", `Made ${makes} times`);
    }

    function syncMadeThisCount(makes) {
      updateMadeThisCount(makes);
      form.elements.namedItem("makes").value = String(makes);

      // Keep the "unsaved changes" baseline in sync for this field only,
      // so a later Save does not clobber or undo the recorded make —
      // without masking other unsaved edits the user may still have.
      try {
        const baseline = JSON.parse(originalMetadata);
        if (baseline && typeof baseline === "object" && !Array.isArray(baseline)) {
          baseline.makes = makes;
          originalMetadata = JSON.stringify(baseline);
        }
      } catch {
        // Baseline is empty/invalid (e.g. create mode); leave it alone.
      }
    }

    async function recordMadeThis() {
      if (busy || isCreating) return;

      const path = getMarkdownPath();
      setBusy(true);
      status.textContent = "Recording your make…";

      let makes = 0;
      let savedToFile = false;

      try {
        makes = (await getMakes(path)) + 1;
        await saveMakes(path, makes);
        savedToFile = true;
        syncMadeThisCount(makes);
        status.textContent = `🎉 Nice work! Your make was recorded — makes: ${makes}.`;
        celebrateMadeThis();
      } catch (error) {
        const message = error.message || "Unable to save your make.";
        const savedButNotRefreshed = /saved, but/i.test(message);

        if (savedButNotRefreshed && !savedToFile) {
          // The file was written but regenerating the page failed: the
          // make counts, even though the visible page is stale.
          savedToFile = true;
          syncMadeThisCount(makes);
          status.textContent =
            `Saved your make (makes: ${makes}), but the page could not be refreshed. ` +
            "Reload the page to see it.";
          celebrateMadeThis();
        } else {
          status.textContent = `Couldn't record your make — ${message} Please try again.`;
        }
      } finally {
        setBusy(false);
      }
    }

    function closeEditor() {
      if (!busy && dialog.open) dialog.close();
    }

    const BULK_FIELD_LABELS = {
      contributor: "Contributor",
      createdOn: "Contribution Date",
      meals: "Meals",
      categories: "Categories",
      cuisine: "Cuisine",
      tags: "Tags",
      makes: "Makes",
      difficulty: "Difficulty",
      source: "Source",
    };

    function fieldValue(metadata, field) {
      if (field === "source") return firstSource(metadata.source);
      return metadata[field] ?? null;
    }

    function isMixed(recipes, field) {
      if (recipes.length < 2) return false;
      const first = JSON.stringify(fieldValue(recipes[0].metadata, field));
      return recipes.some((r) => JSON.stringify(fieldValue(r.metadata, field)) !== first);
    }

    function resetBulkFieldChrome() {
      // MIXED spans and per-field Save buttons live inside their labels,
      // hidden by default; bulk mode reveals them.
      mixedBadges.forEach((badge) => { badge.hidden = true; });
      bulkFieldSaves.forEach((button) => { button.hidden = true; });
      dialog.classList.remove('is-bulk');
      dialog.querySelectorAll('label.is-mixed').forEach((el) => el.classList.remove('is-mixed'));
    }

    function setBulkFieldChrome(visible) {
      bulkFieldSaves.forEach((button) => { button.hidden = !visible; });
      dialog.classList.toggle('is-bulk', visible);
      if (!visible) mixedBadges.forEach((badge) => { badge.hidden = true; });
    }

    function showMixed(inputName) {
      const label = form.elements.namedItem(inputName)?.closest('label');
      const badge = label?.querySelector('.recipe-editor__mixed');
      if (!label || !badge) return;
      badge.hidden = false;
      label.classList.add('recipe-editor__field-label', 'is-mixed');
    }

    function markMixedFields() {
      mixedBadges.forEach((badge) => { badge.hidden = true; });
      dialog.querySelectorAll('label.is-mixed').forEach((el) => el.classList.remove('is-mixed'));
      for (const field of Object.keys(BULK_FIELD_LABELS)) {
        if (field === 'source') {
          for (const sub of ['author', 'title', 'format', 'url']) {
            const first = JSON.stringify(firstSource(bulkRecipes[0].metadata.source)[sub] ?? null);
            if (bulkRecipes.length > 1 && bulkRecipes.some((r) => JSON.stringify(firstSource(r.metadata.source)[sub] ?? null) !== first)) {
              showMixed('source.' + sub);
            }
          }
        } else if (isMixed(bulkRecipes, field)) {
          showMixed(field);
        }
      }
      if (bulkRecipes.length > 1 && bulkRecipes.some((r) => JSON.stringify(r.ratings) !== JSON.stringify(bulkRecipes[0].ratings))) {
        showMixed('rating.name');
      }
    }

    function setupBulkFieldButtons() {
      bulkFieldSaves.forEach((button) => {
        button.addEventListener('click', async (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (busy || !isBulk) return;
          const field = button.dataset.field;
          if (field === 'rating') {
            const rating = readBulkRating();
            if (!rating) return;
            setBusy(true);
            status.textContent = 'Saving rating to ' + bulkPaths.length + ' recipes...';
            try {
              await requestBulkSave(bulkPaths, { rating });
              status.textContent = 'Rating saved to ' + bulkPaths.length + ' recipes! Reloading...';
              window.location.reload();
            } catch (error) {
              status.textContent = error.message;
              setBusy(false);
            }
            return;
          }
          const label = BULK_FIELD_LABELS[field] || field;
          setBusy(true);
          status.textContent = 'Saving ' + label + ' to ' + bulkPaths.length + ' recipes...';
          try {
            const metadata = readMetadata(form);
            await requestBulkSave(bulkPaths, { metadata, fields: [field] });
            status.textContent = label + ' saved to ' + bulkPaths.length + ' recipes! Reloading...';
            window.location.reload();
          } catch (error) {
            status.textContent = error.message;
            setBusy(false);
          }
        });
      });
    }

    function readBulkRating() {
      const name = form.elements.namedItem("rating.name")?.value.trim();
      const scoreRaw = form.elements.namedItem("rating.score")?.value.trim();
      if (!name || !scoreRaw) {
        status.textContent = "Enter a rating name and score to save a rating.";
        return null;
      }
      const score = Number(scoreRaw);
      if (!Number.isFinite(score) || score < 0 || score > 10) {
        status.textContent = "Rating score must be between 0 and 10.";
        return null;
      }
      return { name, rating: score };
    }

    async function openBulkEditor(paths) {
      if (busy || !paths?.length) return;
      isBulk = true;
      isCreating = false;
      bulkPaths = [...paths];
      activeButton = null;
      document.body.classList.add("recipe-editor-open");
      lockBackgroundScroll();
      if (!dialog.open) dialog.showModal();
      heading.textContent = `Bulk Edit Recipes (${bulkPaths.length} selected)`;
      bulkList.hidden = false;
      bulkList.textContent = bulkPaths.join(", ");
      filesDetails.hidden = true;
      aiDetails.hidden = true;
      markdownDetails.hidden = true;
      ratingsDetails.hidden = false;
      ratingsDetails.open = true;
      resetBulkFieldChrome();
      setBulkFieldChrome(true);
      madeThisButton.hidden = true;
      madeThisCount.hidden = true;
      location.hidden = true;
      textarea.value = "";
      originalContent = "";
      originalMetadata = "";
      status.textContent = "Loading recipes…";
      saveButton.textContent = "Save All";
      deleteButton.hidden = false;
      deleteButton.textContent = `Delete ${bulkPaths.length} Recipes`;
      setBusy(true);
      try {
        bulkRecipes = await requestBulkEditor(bulkPaths);
        populateMetadata(form, bulkRecipes[0].metadata);
        form.elements.namedItem("rating.name").value = "";
        form.elements.namedItem("rating.score").value = "";
        markMixedFields();
        status.textContent = "";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
      }
    }

    document.addEventListener("bulk-edit", (event) => {
      openBulkEditor(event.detail?.paths);
    });

    async function openEditor(mode) {
      if (busy) return;

      activeButton = mode === "create" ? createButton : editButton;
      isCreating = mode === "create";
      isBulk = false;
      bulkPaths = [];
      bulkRecipes = [];
      resetBulkFieldChrome();
      ratingsDetails.hidden = true;
      bulkList.hidden = true;
      filesDetails.hidden = false;
      markdownDetails.hidden = false;
      deleteButton.textContent = "Delete";
      document.body.classList.add("recipe-editor-open");
      lockBackgroundScroll();
      dialog.showModal();

      heading.textContent = isCreating ? "Create Recipe" : "Edit Recipe";
      madeThisButton.hidden = true;
      madeThisCount.hidden = true;
      updateMadeThisCount(0);
      madeThisButton.textContent = "I made this!";
      markdownDetails.open = false;
      saveButton.textContent = isCreating ? "Create" : "Save";
      location.hidden = !isCreating;
      resetBulkFieldChrome();
      status.textContent = isCreating ? "Loading folders…" : "Loading recipe…";
      textarea.value = "";
      originalContent = "";
      originalMetadata = "";
      imageInput.value = "";
      selectedImages.textContent = "";
      aiSection.hidden = true;
      aiDetails.hidden = true;
      aiDetails.open = false;
      aiAvailable = false;
      aiImageAvailable = false;
      aiAbortController = null;
      aiStatus.textContent = "";
      aiText.value = "";
      aiUrl.value = "";
      aiImage.value = "";
      aiCancelButton.hidden = true;
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
          folderMode.value = "title";
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

          try {
            const ai = await requestAiStatus();
            setAiState(
              Boolean(ai.configured),
              Boolean(ai.available),
              ai.image_configured === undefined
                ? Boolean(ai.configured)
                : Boolean(ai.image_configured),
              ai.image_available === undefined
                ? Boolean(ai.available)
                : Boolean(ai.image_available),
            );
          } catch {
            setAiState(false, false);
          }
        } else {
          const result = await requestEditor(getMarkdownPath());
          originalContent = result.content;
          textarea.value = result.content;
          populateMetadata(form, result.metadata);
          originalMetadata = JSON.stringify(readMetadata(form));
          updateMadeThisCount(normalizeMakes(result.metadata.makes));

          // Show delete button for existing recipes
          deleteButton.hidden = false;
          madeThisButton.hidden = false;
          madeThisCount.hidden = false;
        }
        status.textContent = "";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        setBusy(false);
        // Hide delete button for new recipes and show for existing ones
        // This is already handled by the logic above, but let's be sure
        if (isCreating) {
          deleteButton.hidden = true;
          madeThisButton.hidden = true;
          madeThisCount.hidden = true;
        } else {
          deleteButton.hidden = false;
          madeThisButton.hidden = false;
          madeThisCount.hidden = false;
        }
      }
    }

    async function generateFromAi(inputType) {
      if (busy || !aiAvailable) return;
      if (inputType === "image" && !aiImageAvailable) return;

      let input;
      if (inputType === "image") {
        input = aiImage.files?.[0];
        if (!input) {
          aiStatus.textContent = "Choose a recipe image first.";
          return;
        }
      } else {
        input = inputType === "url" ? aiUrl.value.trim() : aiText.value.trim();
        if (!input) {
          aiStatus.textContent =
            inputType === "url" ? "Paste a URL first." : "Paste recipe text first.";
          return;
        }
      }

      const controller = new AbortController();
      aiAbortController = controller;
      aiCancelButton.hidden = false;
      setBusy(true);
      setAiProgress(
        inputType === "url"
          ? `URL received: ${input}`
          : inputType === "image"
            ? `Image received: ${input.name}`
            : "Recipe text received.",
      );
      status.textContent = "";

      try {
        const result = await requestAiRecipe(inputType, input, setAiProgress, controller.signal);

        if (!controller.signal.aborted) {
          textarea.value = result.content || "";
          populateMetadata(form, result.metadata || {});
          setAiProgress("Recipe draft ready. Review it, then create the recipe.");
        }
      } catch (error) {
        if (error.name === "AbortError") {
          setAiProgress("Generation cancelled.");
        } else {
          setAiProgress(`Generation failed: ${error.message}`);
        }
      } finally {
        if (aiAbortController === controller) aiAbortController = null;
        aiCancelButton.hidden = true;
        setBusy(false);
      }
    }

    dialog.addEventListener("close", () => {
      document.body.classList.remove("recipe-editor-open");
      unlockBackgroundScroll();
    });

    // BEGIN Close dialogue if a full click cycle occurs outside of dialogue
    let pointerDownTarget = null;

    dialog.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && pointerDownTarget === dialog) {
        closeEditor();
      }
      pointerDownTarget = null;
    });
    // END Close dialogue if a full click cycle occurs outside of dialogue

    setupBulkFieldButtons();
    resetBulkFieldChrome();
    if (editButton) editButton.addEventListener("click", () => openEditor("edit"));
    if (createButton) createButton.addEventListener("click", () => openEditor("create"));
    folderMode.addEventListener("change", updateFolderControls);
    imageInput.addEventListener("change", () => {
      selectedImages.textContent = [...imageInput.files].map((image) => image.name).join(", ");
    });
    cancelButton.addEventListener("click", closeEditor);
    closeButton.addEventListener("click", closeEditor);
    madeThisButton.addEventListener("click", recordMadeThis);
    // A required control inside a closed <details> is not focusable, which
    // would silently block submission. Only require it while it is visible.
    markdownDetails.addEventListener("toggle", () => {
      textarea.required = markdownDetails.open;
    });
    textarea.required = markdownDetails.open;
    aiTextButton.addEventListener("click", () => generateFromAi("text"));
    aiUrlButton.addEventListener("click", () => generateFromAi("url"));
    aiImageButton.addEventListener("click", () => generateFromAi("image"));
    aiCancelButton.addEventListener("click", () => {
      if (aiAbortController) aiAbortController.abort();
    });

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
        !isBulk &&
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
        if (folderMode.value === "title") folder = "";
      }

      setBusy(true);
      status.textContent = isCreating ? "Creating recipe…" : isBulk ? "Saving recipes…" : "Saving recipe…";

      try {
        if (isBulk) {
          const ratingName = form.elements.namedItem("rating.name")?.value.trim();
          const ratingScore = form.elements.namedItem("rating.score")?.value.trim();
          let rating = null;
          if (ratingName || ratingScore) {
            rating = readBulkRating();
            if (!rating) { setBusy(false); return; }
          }
          await requestBulkSave(bulkPaths, { metadata, ...(rating ? { rating } : {}) });
        } else if (isCreating) {
          await createRecipe(folder, folderMode.value !== "existing", content, metadata, images);
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

    deleteButton.addEventListener("click", async () => {
      if (busy) return;

      if (isBulk) {
        if (!confirm(`Delete ${bulkPaths.length} selected recipes? This cannot be undone.`)) return;
        try {
          setBusy(true);
          status.textContent = "Deleting recipes…";
          await requestBulkDelete(bulkPaths);
          status.textContent = "Recipes deleted! Reloading…";
          window.location.reload();
        } catch (error) {
          status.textContent = error.message;
          setBusy(false);
        }
        return;
      }

      // Confirm deletion
      const confirmation = confirm(
        "Are you sure you want to delete this recipe? This action cannot be undone.",
      );
      if (!confirmation) return;

      try {
        setBusy(true);
        status.textContent = "Deleting recipe…";

        // Get the path of the current recipe
        const path = getMarkdownPath();
        const url = new URL("/api/recipe", window.location.origin);
        url.searchParams.set("path", path);

        const response = await fetch(url, {
          method: "DELETE",
          cache: "no-store",
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(result.error || `Request failed (HTTP ${response.status})`);
        }

        status.textContent = "Recipe deleted! Reloading…";
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
