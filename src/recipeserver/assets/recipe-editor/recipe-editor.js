(() => {
  const EDITOR_ID = "recipe-markdown-editor";
  const RECIPE_EDITOR_API = "/api/recipe-editor";
  const BULK_EDITOR_API = "/api/bulk-editor";
  const BULK_DELETE_API = "/api/bulk-delete";
  const RECIPE_API = "/api/recipe";
  const RECIPE_FOLDERS_API = "/api/recipe-folders";
  const AI_STATUS_API = "/api/ai-status";
  const AI_RECIPE_API = "/api/ai-recipe";
  const MAKES_METADATA_API = "/api/metadata/makes";
  const CHEF_HAT_ICON_URL = "/assets/chef-hat.svg";
  const EDITOR_ASSETS_BASE = "/assets/recipe-editor";

  const BULK_FIELD_LABELS = {
    contributor: "Contributor",
    createdOn: "Contribution Date",
    meals: "Meals",
    categories: "Categories",
    cuisine: "Cuisine",
    status: "Status",
    tags: "Tags",
    makes: "Makes",
    difficulty: "Difficulty",
    archived: "Archived",
    source: "Source",
  };

  const NEW_RECIPE_TEMPLATE = `# New Recipe

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

  // ----- Dialog markup ----- //

  async function fetchEditorTemplate(name) {
    const response = await fetch(`${EDITOR_ASSETS_BASE}/${name}.html`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load editor template: ${name} (HTTP ${response.status})`);
    }
    return response.text();
  }

  async function loadEditorMarkup() {
    const [form, files, ai, details, sources, ratings] = await Promise.all([
      fetchEditorTemplate("form"),
      fetchEditorTemplate("files"),
      fetchEditorTemplate("ai"),
      fetchEditorTemplate("details"),
      fetchEditorTemplate("sources"),
      fetchEditorTemplate("ratings"),
    ]);

    return form
      .replace("<!--SECTION:files-->", files)
      .replace("<!--SECTION:ai-->", ai)
      .replace("<!--SECTION:details-->", details)
      .replace("<!--SECTION:sources-->", sources)
      .replace("<!--SECTION:ratings-->", ratings);
  }

  async function createEditor() {
    const dialog = document.createElement("dialog");
    dialog.id = EDITOR_ID;
    dialog.className = "recipe-editor-dialog";
    dialog.innerHTML = await loadEditorMarkup();
    document.body.append(dialog);
    return dialog;
  }

  // ----- Path and fetch helpers ----- //

  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result;
  }

  // ----- API requests ----- //

  async function requestEditor(path, payload = null, images = []) {
    const url = new URL(RECIPE_EDITOR_API, window.location.origin);
    if (payload === null) url.searchParams.set("path", path);

    const requestBody = payload === null ? null : createRequestBody({ path, ...payload }, images);
    return fetchJson(url, {
      method: payload === null ? "GET" : "POST",
      cache: "no-store",
      headers: requestBody?.headers ?? {},
      body: requestBody?.body,
    });
  }

  async function requestBulkEditor(paths) {
    const url = new URL(BULK_EDITOR_API, window.location.origin);
    for (const path of paths) url.searchParams.append("path", path);
    const result = await fetchJson(url, { cache: "no-store" });
    return result.recipes;
  }

  async function requestBulkSave(paths, payload) {
    return fetchJson(new URL(BULK_EDITOR_API, window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, ...payload }),
    });
  }

  async function requestBulkDelete(paths) {
    return fetchJson(new URL(BULK_DELETE_API, window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
  }

  async function requestRecipeFolders() {
    const result = await fetchJson(new URL(RECIPE_FOLDERS_API, window.location.origin), {
      cache: "no-store",
    });
    return result.folders;
  }

  async function requestAiStatus() {
    return fetchJson(new URL(AI_STATUS_API, window.location.origin), { cache: "no-store" });
  }

  async function createRecipe(folder, createFolder, content, metadata, images) {
    const requestBody = createRequestBody({ folder, createFolder, content, metadata }, images);
    return fetchJson(new URL(RECIPE_API, window.location.origin), {
      method: "POST",
      cache: "no-store",
      headers: requestBody.headers ?? {},
      body: requestBody.body,
    });
  }

  async function deleteRecipe(path) {
    const url = new URL(RECIPE_API, window.location.origin);
    url.searchParams.set("path", path);
    return fetchJson(url, { method: "DELETE", cache: "no-store" });
  }

  async function getMakes(path) {
    const url = new URL(MAKES_METADATA_API, window.location.origin);
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
    const result = await fetchJson(new URL(MAKES_METADATA_API, window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, value: makes }),
    });
    if (result.success !== true) {
      throw new Error(result.error || "Unable to save makes count");
    }
  }

  // ----- AI streaming request ----- //

  function buildAiRequest(inputType, input) {
    if (inputType === "image") {
      // `input` is a File for image uploads; send it as multipart form data.
      const body = new FormData();
      body.append("inputType", inputType);
      body.append("stream", "true");
      body.append("image", input, input.name);
      return { headers: {}, body };
    }

    return {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inputType, input, stream: true }),
    };
  }

  async function readAiStream(response, onProgress) {
    if (!response.body) throw new Error("The AI progress stream is unavailable.");

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

      for (const line of lines) await handleLine(line);
      if (done) break;
    }

    await handleLine(buffer);
    if (!result) throw new Error("The AI progress stream ended without a recipe.");
    return result;
  }

  async function requestAiRecipe(inputType, input, onProgress, signal) {
    const request = buildAiRequest(inputType, input);
    const response = await fetch(new URL(AI_RECIPE_API, window.location.origin), {
      method: "POST",
      cache: "no-store",
      headers: request.headers,
      body: request.body,
      signal,
    });

    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return readAiStream(response, onProgress);
  }

  // ----- Data helpers ----- //

  function normalizeMakes(value) {
    // Older recipes may store makes as a list or a numeric string.
    const candidate = Array.isArray(value) ? value[0] : value;
    const number = typeof candidate === "number" ? candidate : Number(candidate);

    if (candidate == null || candidate === "" || !Number.isFinite(number) || number < 0) {
      return 0;
    }

    return Math.floor(number);
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

    const statusValue = Array.isArray(metadata.status) ? metadata.status[0] : metadata.status;
    form.elements.namedItem("status").value = statusValue ?? "";
    form.elements.namedItem("contributor").value = metadata.contributor ?? "";
    form.elements.namedItem("archived").checked = metadata.archived === true;

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
      return value.split(",").map((item) => item.trim()).filter(Boolean);
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
      status: get("status") || null,
      createdOn: get("createdOn") || null,
      archived: Boolean(form.elements.namedItem("archived")?.checked),
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

  // ----- Icon loading ----- //

  async function loadSvgIcon(url) {
    // The chef-hat icon is loaded and inlined so it can inherit currentColor.
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return "";

      const svg = new DOMParser()
        .parseFromString(await response.text(), "image/svg+xml")
        .documentElement;
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      return new XMLSerializer().serializeToString(svg);
    } catch {
      return "";
    }
  }

  // ----- Initialize: DOM refs and state ----- //

  function collectDomRefs(dialog) {
    return {
      dialog,
      form: dialog.querySelector("form"),
      textarea: dialog.querySelector(".recipe-editor__source"),
      status: dialog.querySelector(".recipe-editor__status"),
      saveButton: dialog.querySelector(".recipe-editor__save"),
      cancelButton: dialog.querySelector(".recipe-editor__cancel"),
      closeButton: dialog.querySelector(".recipe-editor__close"),
      deleteButton: dialog.querySelector(".recipe-editor__delete"),
      madeThisButton: dialog.querySelector(".recipe-editor__made-this"),
      madeThisCount: dialog.querySelector(".recipe-editor__makes-count"),
      madeThisValue: dialog.querySelector(".recipe-editor__makes-value"),
      makesIcon: dialog.querySelector(".recipe-editor__makes-icon"),
      markdownDetails: dialog.querySelector(".recipe-editor__markdown-details"),
      header: dialog.querySelector(".recipe-editor__header"),
      heading: dialog.querySelector(".recipe-editor__header h2"),
      location: dialog.querySelector(".recipe-editor__location"),
      folderMode: dialog.querySelector(".recipe-editor__folder-mode"),
      folderSelect: dialog.querySelector(".recipe-editor__folder-select"),
      existingFolder: dialog.querySelector(".recipe-editor__existing-folder"),
      folderPathLabel: dialog.querySelector(".recipe-editor__folder-path"),
      newFolder: dialog.querySelector(".recipe-editor__new-folder"),
      imageInput: dialog.querySelector("#recipe-editor-images"),
      imageDropzone: dialog.querySelector(".recipe-editor__images"),
      selectedImages: dialog.querySelector(".recipe-editor__images-selected"),
      aiSection: dialog.querySelector(".recipe-editor__ai"),
      aiDetails: dialog.querySelector(".recipe-editor__ai-details"),
      aiStatus: dialog.querySelector(".recipe-editor__ai-status"),
      aiText: dialog.querySelector(".recipe-editor__ai-text"),
      aiUrl: dialog.querySelector(".recipe-editor__ai-url"),
      aiImage: dialog.querySelector(".recipe-editor__ai-image"),
      aiTextButton: dialog.querySelector(".recipe-editor__ai-generate-text"),
      aiUrlButton: dialog.querySelector(".recipe-editor__ai-generate-url"),
      aiImageButton: dialog.querySelector(".recipe-editor__ai-generate-image"),
      aiCancelButton: dialog.querySelector(".recipe-editor__ai-cancel"),
      aiControls: null,
      aiImageControls: null,
      bulkFieldSaves: [...dialog.querySelectorAll(".recipe-editor__bulk-field-save")],
      mixedBadges: [...dialog.querySelectorAll(".recipe-editor__mixed")],
      ratingsDetails: dialog.querySelector(".recipe-editor__ratings-details"),
      bulkList: dialog.querySelector(".recipe-editor__bulk-list"),
      filesDetails: dialog.querySelector(".recipe-editor__details"),
    };
  }

  function finalizeDomRefs(refs) {
    refs.aiControls = [refs.aiText, refs.aiUrl, refs.aiTextButton, refs.aiUrlButton];
    refs.aiImageControls = [refs.aiImage, refs.aiImageButton];
    return refs;
  }

  function createState(editButton, createButton) {
    return {
      editButton,
      createButton,
      originalContent: "",
      originalMetadata: "",
      markdownPath: "",
      busy: false,
      scrollY: 0,
      activeButton: null,
      isCreating: false,
      isBulk: false,
      bulkPaths: [],
      bulkRecipes: [],
      aiAvailable: false,
      aiImageAvailable: false,
      aiAbortController: null,
    };
  }

  // ----- UI helpers ----- //

  function createUiActions(refs, state) {
    function setStatus(message) {
      refs.status.textContent = message;
    }

    function updateFolderControls() {
      const creatingInExistingFolder = refs.folderMode.value === "existing";
      const creatingNewFolder = refs.folderMode.value === "new";
      refs.existingFolder.hidden = !creatingInExistingFolder;
      refs.folderPathLabel.hidden = !creatingNewFolder;
    }

    function lockBackgroundScroll() {
      state.scrollY = window.scrollY;
      document.body.style.position = "fixed";
      document.body.style.top = `-${state.scrollY}px`;
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
      window.scrollTo(0, state.scrollY);
    }

    function closeEditor() {
      if (!state.busy && refs.dialog.open) refs.dialog.close();
    }

    function setBusy(value) {
      state.busy = value;
      refs.saveButton.disabled = value;
      refs.cancelButton.disabled = value;
      refs.closeButton.disabled = value;
      refs.madeThisButton.disabled = value;
      refs.textarea.readOnly = value;
      if (state.activeButton) state.activeButton.disabled = value;
      refs.folderMode.disabled = value;
      refs.folderSelect.disabled = value;
      refs.newFolder.disabled = value;
      refs.imageInput.disabled = value;

      refs.form
        .querySelectorAll(".recipe-editor__metadata input, .recipe-editor__metadata select")
        .forEach((input) => {
          input.disabled = value;
        });
      refs.bulkFieldSaves.forEach((button) => {
        button.disabled = value;
      });

      refs.aiControls.forEach((control) => {
        control.disabled = value || !state.aiAvailable;
      });
      refs.aiImageControls.forEach((control) => {
        control.disabled = value || !state.aiImageAvailable;
      });
    }

    return { setStatus, updateFolderControls, lockBackgroundScroll, unlockBackgroundScroll, closeEditor, setBusy };
  }

  // ----- AI helpers ----- //

  function createAiActions(refs, state, ui) {
    function setAiProgress(message) {
      refs.aiStatus.textContent = message;
    }

    function setAiState(configured, available, imageConfigured = available, imageAvailable = imageConfigured) {
      const { aiDetails } = refs;
      const { isCreating } = state;
      state.aiAvailable = configured && available;
      state.aiImageAvailable = configured && imageConfigured && imageAvailable;
      refs.aiSection.hidden = !configured;
      aiDetails.hidden = !configured || !isCreating;

      refs.aiControls.forEach((control) => {
        control.disabled = state.busy || !state.aiAvailable;
      });
      refs.aiImageControls.forEach((control) => {
        control.disabled = state.busy || !state.aiImageAvailable;
      });

      if (!configured) {
        refs.aiStatus.textContent = "";
      } else if (!available) {
        refs.aiStatus.textContent =
          "The configured local model is unavailable. Start it, then reopen this dialog.";
      } else if (!state.aiImageAvailable) {
        refs.aiStatus.textContent =
          "The image analysis model is not configured. From Image is unavailable.";
      } else {
        refs.aiStatus.textContent = "";
      }
    }

    function readAiInput(inputType) {
      if (inputType === "image") {
        const file = refs.aiImage.files?.[0];
        if (!file) return { error: "Choose a recipe image first." };
        return { input: file };
      }

      const input = inputType === "url" ? refs.aiUrl.value.trim() : refs.aiText.value.trim();
      if (!input) {
        return { error: inputType === "url" ? "Paste a URL first." : "Paste recipe text first." };
      }
      return { input };
    }

    function aiStartMessage(inputType, input) {
      if (inputType === "url") return `URL received: ${input}`;
      if (inputType === "image") return `Image received: ${input.name}`;
      return "Recipe text received.";
    }

    async function generateFromAi(inputType) {
      if (state.busy || !state.aiAvailable) return;
      if (inputType === "image" && !state.aiImageAvailable) return;

      const { input, error } = readAiInput(inputType);
      if (error) {
        setAiProgress(error);
        return;
      }

      const controller = new AbortController();
      state.aiAbortController = controller;
      refs.aiCancelButton.hidden = false;
      ui.setBusy(true);
      setAiProgress(aiStartMessage(inputType, input));
      ui.setStatus("");

      try {
        const result = await requestAiRecipe(inputType, input, setAiProgress, controller.signal);
        if (!controller.signal.aborted) {
          refs.textarea.value = result.content || "";
          populateMetadata(refs.form, result.metadata || {});
          setAiProgress("Recipe draft ready. Review it, then create the recipe.");
        }
      } catch (caughtError) {
        if (caughtError.name === "AbortError") {
          setAiProgress("Generation cancelled.");
        } else {
          setAiProgress(`Generation failed: ${caughtError.message}`);
        }
      } finally {
        if (state.aiAbortController === controller) state.aiAbortController = null;
        refs.aiCancelButton.hidden = true;
        ui.setBusy(false);
      }
    }

    return { setAiProgress, setAiState, generateFromAi };
  }

  // ----- "Made this" helpers ----- //

  function createMadeThisActions(refs, state, ui) {
    function updateMadeThisCount(makes) {
      refs.madeThisValue.textContent = makesCountLabel(makes);
      refs.madeThisCount.setAttribute("aria-label", `Made ${makes} times`);
    }

    function syncMadeThisCount(makes) {
      updateMadeThisCount(makes);
      refs.form.elements.namedItem("makes").value = String(makes);

      // Keep the "unsaved changes" baseline in sync for this field only,
      // so a later Save does not clobber or undo the recorded make —
      // without masking other unsaved edits the user may still have.
      try {
        const baseline = JSON.parse(state.originalMetadata);
        if (baseline && typeof baseline === "object" && !Array.isArray(baseline)) {
          baseline.makes = makes;
          state.originalMetadata = JSON.stringify(baseline);
        }
      } catch {
        // Baseline is empty/invalid (e.g. create mode); leave it alone.
      }
    }

    function celebrateMadeThis() {
      refs.madeThisButton.classList.remove("is-celebrating");
      // Restart the CSS animation on repeat clicks.
      void refs.madeThisButton.offsetWidth;
      refs.madeThisButton.classList.add("is-celebrating");

      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const sparkles = ["✨", "⭐", "🎉", "💛"];
      const particles = sparkles.map((glyph, index) => {
        const particle = document.createElement("span");
        particle.className = "recipe-editor__sparkle";
        particle.textContent = glyph;
        particle.setAttribute("aria-hidden", "true");
        particle.style.setProperty("--sparkle-x", `${(index - 1.5) * 18}px`);
        particle.style.setProperty("--sparkle-delay", `${index * 60}ms`);
        refs.header.append(particle);
        return particle;
      });

      window.setTimeout(() => {
        particles.forEach((particle) => particle.remove());
        refs.madeThisButton.classList.remove("is-celebrating");
      }, 1000);
    }

    async function recordMadeThis() {
      if (state.busy || state.isCreating) return;

      ui.setBusy(true);
      ui.setStatus("Recording your make…");

      let makes = 0;
      let savedToFile = false;
      const path = state.markdownPath;

      try {
        makes = (await getMakes(path)) + 1;
        await saveMakes(path, makes);
        savedToFile = true;
        syncMadeThisCount(makes);
        ui.setStatus(`🎉 Nice work! Your make was recorded — makes: ${makes}.`);
        celebrateMadeThis();
      } catch (error) {
        handleMadeThisError(error, makes, savedToFile, syncMadeThisCount, celebrateMadeThis, ui);
      } finally {
        ui.setBusy(false);
      }
    }

    return { updateMadeThisCount, recordMadeThis };
  }

  function handleMadeThisError(error, makes, savedToFile, syncMadeThisCount, celebrateMadeThis, ui) {
    const message = error.message || "Unable to save your make.";
    const savedButNotRefreshed = /saved, but/i.test(message);

    if (savedButNotRefreshed && !savedToFile) {
      // The file was written but regenerating the page failed: the make
      // counts, even though the visible page is stale.
      syncMadeThisCount(makes);
      ui.setStatus(
        `Saved your make (makes: ${makes}), but the page could not be refreshed. ` +
          "Reload the page to see it.",
      );
      celebrateMadeThis();
      return;
    }

    ui.setStatus(`Couldn't record your make — ${message} Please try again.`);
  }

  // ----- Bulk editor helpers ----- //

  function fieldValue(metadata, field) {
    if (field === "source") return firstSource(metadata.source);
    return metadata[field] ?? null;
  }

  function isMixed(recipes, field) {
    if (recipes.length < 2) return false;
    const first = JSON.stringify(fieldValue(recipes[0].metadata, field));
    return recipes.some((recipe) => JSON.stringify(fieldValue(recipe.metadata, field)) !== first);
  }

  function readBulkRating(form, setStatus) {
    const name = form.elements.namedItem("rating.name")?.value.trim();
    const scoreRaw = form.elements.namedItem("rating.score")?.value.trim();
    if (!name || !scoreRaw) {
      setStatus("Enter a rating name and score to save a rating.");
      return null;
    }
    const score = Number(scoreRaw);
    if (!Number.isFinite(score) || score < 0 || score > 10) {
      setStatus("Rating score must be between 0 and 10.");
      return null;
    }
    return { name, rating: score };
  }

  function resetBulkFieldChrome(refs) {
    // MIXED spans and per-field Save buttons live inside their labels,
    // hidden by default; bulk mode reveals them.
    refs.mixedBadges.forEach((badge) => { badge.hidden = true; });
    refs.bulkFieldSaves.forEach((button) => { button.hidden = true; });
    refs.dialog.classList.remove("is-bulk");
    refs.dialog.querySelectorAll("label.is-mixed").forEach((element) => {
      element.classList.remove("is-mixed");
    });
  }

  function setBulkFieldChrome(refs, visible) {
    refs.bulkFieldSaves.forEach((button) => { button.hidden = !visible; });
    refs.dialog.classList.toggle("is-bulk", visible);
    if (!visible) refs.mixedBadges.forEach((badge) => { badge.hidden = true; });
  }

  function showMixed(refs, inputName) {
    const label = refs.form.elements.namedItem(inputName)?.closest("label");
    const badge = label?.querySelector(".recipe-editor__mixed");
    if (!label || !badge) return;
    badge.hidden = false;
    label.classList.add("recipe-editor__field-label", "is-mixed");
  }

  function markMixedSourceFields(refs, state) {
    for (const subfield of ["author", "title", "format", "url"]) {
      const first = JSON.stringify(firstSource(state.bulkRecipes[0].metadata.source)[subfield] ?? null);
      const mixed =
        state.bulkRecipes.length > 1 &&
        state.bulkRecipes.some(
          (recipe) => JSON.stringify(firstSource(recipe.metadata.source)[subfield] ?? null) !== first,
        );
      if (mixed) showMixed(refs, `source.${subfield}`);
    }
  }

  function markMixedFields(refs, state) {
    refs.mixedBadges.forEach((badge) => { badge.hidden = true; });
    refs.dialog.querySelectorAll("label.is-mixed").forEach((element) => {
      element.classList.remove("is-mixed");
    });
    for (const field of Object.keys(BULK_FIELD_LABELS)) {
      if (field === "source") markMixedSourceFields(refs, state);
      else if (isMixed(state.bulkRecipes, field)) showMixed(refs, field);
    }
    const ratingsDiffer =
      state.bulkRecipes.length > 1 &&
      state.bulkRecipes.some(
        (recipe) => JSON.stringify(recipe.ratings) !== JSON.stringify(state.bulkRecipes[0].ratings),
      );
    if (ratingsDiffer) showMixed(refs, "rating.name");
  }

  async function saveBulkField(refs, state, ui, field) {
    if (field === "rating") {
      const rating = readBulkRating(refs.form, ui.setStatus);
      if (!rating) return;
      ui.setBusy(true);
      ui.setStatus(`Saving rating to ${state.bulkPaths.length} recipes...`);
      await requestBulkSave(state.bulkPaths, { rating });
      ui.setStatus(`Rating saved to ${state.bulkPaths.length} recipes! Reloading...`);
      window.location.reload();
      return;
    }
    const label = BULK_FIELD_LABELS[field] || field;
    ui.setBusy(true);
    ui.setStatus(`Saving ${label} to ${state.bulkPaths.length} recipes...`);
    const metadata = readMetadata(refs.form);
    await requestBulkSave(state.bulkPaths, { metadata, fields: [field] });
    ui.setStatus(`${label} saved to ${state.bulkPaths.length} recipes! Reloading...`);
    window.location.reload();
  }

  function setupBulkFieldButtons(refs, state, ui) {
    refs.bulkFieldSaves.forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (state.busy || !state.isBulk) return;
        try {
          await saveBulkField(refs, state, ui, button.dataset.field);
        } catch (error) {
          ui.setStatus(error.message);
          ui.setBusy(false);
        }
      });
    });
  }

  function createBulkActions(refs, state, ui) {
    return {
      resetBulkFieldChrome: () => resetBulkFieldChrome(refs),
      setBulkFieldChrome: (visible) => setBulkFieldChrome(refs, visible),
      markMixedFields: () => markMixedFields(refs, state),
      setupBulkFieldButtons: () => setupBulkFieldButtons(refs, state, ui),
      readBulkRating: () => readBulkRating(refs.form, ui.setStatus),
    };
  }

  // ----- Session/open/save/delete flows ----- //

  function resetCommonOpenState(refs, state, ui) {
    state.activeButton = null;
    document.body.classList.add("recipe-editor-open");
    ui.lockBackgroundScroll();
    if (!refs.dialog.open) refs.dialog.showModal();
    refs.textarea.value = "";
    state.originalContent = "";
    state.originalMetadata = "";
    ui.setStatus("");
  }

  function resetAiOpenState(refs, state) {
    refs.aiSection.hidden = true;
    refs.aiDetails.hidden = true;
    refs.aiDetails.open = false;
    state.aiAvailable = false;
    state.aiImageAvailable = false;
    state.aiAbortController = null;
    refs.aiStatus.textContent = "";
    refs.aiText.value = "";
    refs.aiUrl.value = "";
    refs.aiImage.value = "";
    refs.aiCancelButton.hidden = true;
  }

  async function openBulkEditor(refs, state, ui, bulk, paths) {
    if (state.busy || !paths?.length) return;
    state.isBulk = true;
    state.isCreating = false;
    state.bulkPaths = [...paths];
    state.markdownPath = "";
    resetCommonOpenState(refs, state, ui);
    refs.heading.textContent = `Bulk Edit Recipes (${state.bulkPaths.length} selected)`;
    refs.bulkList.hidden = false;
    refs.bulkList.textContent = state.bulkPaths.join(", ");
    refs.filesDetails.hidden = true;
    refs.aiDetails.hidden = true;
    refs.markdownDetails.hidden = true;
    refs.ratingsDetails.hidden = false;
    refs.ratingsDetails.open = true;
    bulk.resetBulkFieldChrome();
    bulk.setBulkFieldChrome(true);
    refs.madeThisButton.hidden = true;
    refs.madeThisCount.hidden = true;
    refs.location.hidden = true;
    refs.saveButton.textContent = "Save All";
    refs.deleteButton.hidden = false;
    refs.deleteButton.textContent = `Delete ${state.bulkPaths.length} Recipes`;
    ui.setStatus("Loading recipes…");
    ui.setBusy(true);
    try {
      state.bulkRecipes = await requestBulkEditor(state.bulkPaths);
      populateMetadata(refs.form, state.bulkRecipes[0].metadata);
      refs.form.elements.namedItem("rating.name").value = "";
      refs.form.elements.namedItem("rating.score").value = "";
      bulk.markMixedFields();
      ui.setStatus("");
    } catch (error) {
      ui.setStatus(error.message);
    } finally {
      ui.setBusy(false);
    }
  }

  async function loadCreateMode(refs, ui, ai) {
    refs.deleteButton.hidden = true;
    refs.madeThisButton.hidden = true;
    refs.madeThisCount.hidden = true;
    ui.setStatus("Loading folders…");
    const folders = await requestRecipeFolders();
    refs.folderSelect.replaceChildren(
      ...folders.map((folder) => {
        const option = document.createElement("option");
        option.value = folder;
        option.textContent = folder || "Recipe root";
        return option;
      }),
    );
    refs.folderMode.value = "title";
    refs.newFolder.value = "";
    ui.updateFolderControls();
    populateMetadata(refs.form, {});
    refs.textarea.value = NEW_RECIPE_TEMPLATE;
    try {
      const status = await requestAiStatus();
      ai.setAiState(
        Boolean(status.configured),
        Boolean(status.available),
        status.image_configured === undefined ? Boolean(status.configured) : Boolean(status.image_configured),
        status.image_available === undefined ? Boolean(status.available) : Boolean(status.image_available),
      );
    } catch {
      ai.setAiState(false, false);
    }
  }

  async function loadEditMode(refs, state, madeThis) {
    state.markdownPath = getMarkdownPath();
    const result = await requestEditor(state.markdownPath);
    state.originalContent = result.content;
    refs.textarea.value = result.content;
    populateMetadata(refs.form, result.metadata);
    state.originalMetadata = JSON.stringify(readMetadata(refs.form));
    madeThis.updateMadeThisCount(normalizeMakes(result.metadata.makes));
    refs.deleteButton.hidden = false;
    refs.madeThisButton.hidden = false;
    refs.madeThisCount.hidden = false;
  }

  function prepareEditorOpen(refs, state, madeThis, bulk, mode) {
    state.activeButton = mode === "create" ? state.createButton : state.editButton;
    state.isCreating = mode === "create";
    state.isBulk = false;
    state.bulkPaths = [];
    state.bulkRecipes = [];
    state.markdownPath = "";
    bulk.resetBulkFieldChrome();
    refs.ratingsDetails.hidden = true;
    refs.bulkList.hidden = true;
    refs.filesDetails.hidden = false;
    refs.markdownDetails.hidden = false;
    refs.deleteButton.textContent = "Delete";
    refs.heading.textContent = state.isCreating ? "Create Recipe" : "Edit Recipe";
    refs.madeThisButton.hidden = true;
    refs.madeThisCount.hidden = true;
    madeThis.updateMadeThisCount(0);
    refs.madeThisButton.textContent = "I made this!";
    refs.markdownDetails.open = false;
    refs.saveButton.textContent = state.isCreating ? "Create" : "Save";
    refs.location.hidden = !state.isCreating;
    refs.imageInput.value = "";
    refs.selectedImages.textContent = "";
    refs.imageDropzone?.classList.remove("is-dragging");
  }

  async function openEditor(refs, state, ui, ai, madeThis, bulk, mode) {
    if (state.busy) return;
    prepareEditorOpen(refs, state, madeThis, bulk, mode);
    resetCommonOpenState(refs, state, ui);
    resetAiOpenState(refs, state);
    ui.setBusy(true);
    try {
      if (state.isCreating) await loadCreateMode(refs, ui, ai);
      else await loadEditMode(refs, state, madeThis);
      ui.setStatus("");
    } catch (error) {
      ui.setStatus(error.message);
    } finally {
      ui.setBusy(false);
      // Preserve the existing post-load visibility guarantees for edit/create.
      refs.deleteButton.hidden = state.isCreating;
      refs.madeThisButton.hidden = state.isCreating;
      refs.madeThisCount.hidden = state.isCreating;
    }
  }

  function hasUnsavedChanges(state, content, metadataContent, imageCount) {
    return (
      state.isCreating ||
      state.isBulk ||
      content !== state.originalContent ||
      metadataContent !== state.originalMetadata ||
      imageCount > 0
    );
  }

  async function submitBulkSave(refs, state, ui, bulk, metadata) {
    const ratingName = refs.form.elements.namedItem("rating.name")?.value.trim();
    const ratingScore = refs.form.elements.namedItem("rating.score")?.value.trim();
    let rating = null;
    if (ratingName || ratingScore) {
      rating = bulk.readBulkRating();
      if (!rating) { ui.setBusy(false); return false; }
    }
    await requestBulkSave(state.bulkPaths, { metadata, ...(rating ? { rating } : {}) });
    return true;
  }

  async function submitEditorSave(refs, state, ui, bulk, metadata, content, images) {
    if (state.isBulk) return submitBulkSave(refs, state, ui, bulk, metadata);
    if (state.isCreating) {
      let folder = refs.folderMode.value === "new" ? refs.newFolder.value.trim() : refs.folderSelect.value;
      if (refs.folderMode.value === "new" && !folder) {
        ui.setStatus("Enter a folder path.");
        return false;
      }
      if (refs.folderMode.value === "title") folder = "";
      await createRecipe(folder, refs.folderMode.value !== "existing", content, metadata, images);
      return true;
    }
    await requestEditor(state.markdownPath, { content, metadata }, images);
    return true;
  }

  async function handleSubmit(refs, state, ui, bulk, event) {
    event.preventDefault();
    if (state.busy) return;
    let metadata;
    try { metadata = readMetadata(refs.form); } catch (error) { ui.setStatus(error.message); return; }
    const content = refs.textarea.value;
    const metadataContent = JSON.stringify(metadata);
    const images = [...refs.imageInput.files];
    if (!hasUnsavedChanges(state, content, metadataContent, images.length)) {
      refs.dialog.close();
      return;
    }
    ui.setBusy(true);
    ui.setStatus(state.isCreating ? "Creating recipe…" : state.isBulk ? "Saving recipes…" : "Saving recipe…");
    try {
      const completed = await submitEditorSave(refs, state, ui, bulk, metadata, content, images);
      if (!completed) return;
      ui.setStatus(state.isCreating ? "Created! Reloading…" : "Saved! Reloading…");
      window.location.reload();
    } catch (error) {
      ui.setStatus(error.message);
      ui.setBusy(false);
    }
  }

  async function handleDelete(refs, state, ui) {
    if (state.busy) return;
    if (state.isBulk) {
      if (!confirm(`Delete ${state.bulkPaths.length} selected recipes? This cannot be undone.`)) return;
      try {
        ui.setBusy(true);
        ui.setStatus("Deleting recipes…");
        await requestBulkDelete(state.bulkPaths);
        ui.setStatus("Recipes deleted! Reloading…");
        window.location.reload();
      } catch (error) {
        ui.setStatus(error.message);
        ui.setBusy(false);
      }
      return;
    }
    if (!confirm("Are you sure you want to delete this recipe? This action cannot be undone.")) return;
    try {
      ui.setBusy(true);
      ui.setStatus("Deleting recipe…");
      await deleteRecipe(state.markdownPath);
      ui.setStatus("Recipe deleted! Reloading…");
      window.location.reload();
    } catch (error) {
      ui.setStatus(error.message);
      ui.setBusy(false);
    }
  }

  function createSessionActions(refs, state, ui, ai, madeThis, bulk) {
    return {
      openBulkEditor: (paths) => openBulkEditor(refs, state, ui, bulk, paths),
      openEditor: (mode) => openEditor(refs, state, ui, ai, madeThis, bulk, mode),
      handleSubmit: (event) => handleSubmit(refs, state, ui, bulk, event),
      handleDelete: () => handleDelete(refs, state, ui),
    };
  }

  // ----- Event registration ----- //

  function registerDialogDismissListeners(refs, ui, state) {
    let pointerDownTarget = null;

    refs.dialog.addEventListener("close", () => {
      document.body.classList.remove("recipe-editor-open");
      ui.unlockBackgroundScroll();
    });

    // Close dialogue if a full click cycle occurs outside of dialogue.
    refs.dialog.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });
    refs.dialog.addEventListener("click", (event) => {
      if (event.target === refs.dialog && pointerDownTarget === refs.dialog) {
        ui.closeEditor();
      }
      pointerDownTarget = null;
    });

    refs.dialog.addEventListener("cancel", (event) => {
      if (state.busy) event.preventDefault();
    });
  }

  function registerControlListeners(refs, state, ui, ai, madeThis, session) {
    const { madeThisButton, markdownDetails, textarea } = refs;
    const { recordMadeThis } = madeThis;

    if (state.editButton) state.editButton.addEventListener("click", () => session.openEditor("edit"));
    if (state.createButton) state.createButton.addEventListener("click", () => session.openEditor("create"));

    refs.folderMode.addEventListener("change", ui.updateFolderControls);
    refs.imageInput.addEventListener("change", () => {
      refs.selectedImages.textContent = [...refs.imageInput.files].map((image) => image.name).join(", ");
    });

    function appendImages(newFiles) {
      if (!newFiles.length || typeof DataTransfer === "undefined") return false;
      const transfer = new DataTransfer();
      [...refs.imageInput.files, ...newFiles].forEach((file) => transfer.items.add(file));
      refs.imageInput.files = transfer.files;
      refs.selectedImages.textContent = [...refs.imageInput.files].map((image) => image.name).join(", ");
      return true;
    }

    // Paste an image from the clipboard into the image picker.
    const handleImagePaste = (event) => {
      if (state.busy || refs.imageInput.disabled) return;
      const items = event.clipboardData?.items;
      if (!items) return;
      const pasted = [...items]
        .filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!pasted.length) return;
      event.preventDefault();
      appendImages(pasted);
    };
    refs.dialog.addEventListener("paste", handleImagePaste);
    refs.imageInput.addEventListener("paste", handleImagePaste);

    // Drag and drop images into the dropzone; clicking the box also opens
    // the file picker (clicking the native input or its label is left alone
    // so the browser does not open the picker twice).
    refs.imageDropzone?.addEventListener("dragover", (event) => {
      if (state.busy || refs.imageInput.disabled) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      refs.imageDropzone.classList.add("is-dragging");
    });
    refs.imageDropzone?.addEventListener("dragleave", (event) => {
      if (event.currentTarget.contains(event.relatedTarget)) return;
      refs.imageDropzone.classList.remove("is-dragging");
    });
    refs.imageDropzone?.addEventListener("drop", (event) => {
      if (state.busy || refs.imageInput.disabled) return;
      event.preventDefault();
      refs.imageDropzone.classList.remove("is-dragging");
      const files = [...(event.dataTransfer?.files ?? [])].filter((file) =>
        file.type.startsWith("image/"),
      );
      if (files.length) appendImages(files);
    });
    refs.imageDropzone?.addEventListener("click", (event) => {
      if (state.busy || refs.imageInput.disabled) return;
      if (event.target === refs.imageInput || event.target.closest("label")) return;
      refs.imageInput.click();
    });

    refs.cancelButton.addEventListener("click", ui.closeEditor);
    refs.closeButton.addEventListener("click", ui.closeEditor);
    madeThisButton.addEventListener("click", recordMadeThis);

    // A required control inside a closed <details> is not focusable, which
    // would silently block submission. Only require it while it is visible.
    markdownDetails.addEventListener("toggle", () => {
      textarea.required = markdownDetails.open;
    });
    textarea.required = markdownDetails.open;

    refs.aiTextButton.addEventListener("click", () => ai.generateFromAi("text"));
    refs.aiUrlButton.addEventListener("click", () => ai.generateFromAi("url"));
    refs.aiImageButton.addEventListener("click", () => ai.generateFromAi("image"));
    refs.aiCancelButton.addEventListener("click", () => {
      if (state.aiAbortController) state.aiAbortController.abort();
    });

    refs.form.addEventListener("submit", session.handleSubmit);
    refs.deleteButton.addEventListener("click", session.handleDelete);
  }

  function registerListeners(refs, state, ui, ai, madeThis, session) {
    registerDialogDismissListeners(refs, ui, state);
    registerControlListeners(refs, state, ui, ai, madeThis, session);
  }

  // ----- Bootstrap ----- //

  async function initialize() {
    const editButton = document.querySelector("#edit-recipe");
    const createButton = document.querySelector("#create-recipe");
    if (!editButton && !createButton) return;

    const dialog = await createEditor();
    const refs = finalizeDomRefs(collectDomRefs(dialog));
    const state = createState(editButton, createButton);

    if (refs.makesIcon) {
      refs.makesIcon.innerHTML = await loadSvgIcon(CHEF_HAT_ICON_URL);
    }

    const ui = createUiActions(refs, state);
    const ai = createAiActions(refs, state, ui);
    const madeThis = createMadeThisActions(refs, state, ui);
    const bulk = createBulkActions(refs, state, ui);
    const session = createSessionActions(refs, state, ui, ai, madeThis, bulk);

    bulk.setupBulkFieldButtons();
    bulk.resetBulkFieldChrome();
    document.addEventListener("bulk-edit", (event) => {
      session.openBulkEditor(event.detail?.paths);
    });
    registerListeners(refs, state, ui, ai, madeThis, session);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
