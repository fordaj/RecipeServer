(() => {
  const EDITOR_ID = "recipe-markdown-editor";
  const RECIPE_EDITOR_API = "/api/recipe-editor";
  const BULK_EDITOR_API = "/api/bulk-editor";
  const BULK_DELETE_API = "/api/bulk-delete";
  const RECIPE_API = "/api/recipe";
  const RECIPE_FOLDERS_API = "/api/recipe-folders";
  const AI_STATUS_API = "/api/ai-status";
  const AI_RECIPE_API = "/api/ai-recipe";
  const RECIPE_IMAGES_RENAME_API = "/api/recipe-images/rename";
  const RECIPE_IMAGES_UPLOAD_API = "/api/recipe-images/upload";
  const RECIPE_IMAGES_DELETE_API = "/api/recipe-images/delete";
  const MAKES_METADATA_API = "/api/metadata/makes";
  const METADATA_OPTIONS_API = "/api/metadata-options";
  const CHEF_HAT_ICON_URL = "/assets/chef-hat.svg";
  const EDITOR_ASSETS_BASE = "/assets/recipe-editor";

  // The pages that load this file also load these scripts before it (see
  // index_html_generator.py and markdown_to_html.py). Destructure them once
  // so the external dependencies are explicit.
  const { RecipeAIProgress, RecipeMetadataPicker, RecipeIcons } = window;

  // The "I made this!" celebration: a row of sparkles arcs outward from the
  // button, staggered, then is removed together.
  const SPARKLE_GLYPHS = ["✨", "⭐", "🎉", "💛"];
  const SPARKLE_SPREAD_PX = 18;
  const SPARKLE_STAGGER_MS = 60;
  const SPARKLE_LIFETIME_MS = 1000;
  const SPARKLE_CENTER_INDEX = (SPARKLE_GLYPHS.length - 1) / 2;

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

  async function requestMetadataOptions() {
    const result = await fetchJson(new URL(METADATA_OPTIONS_API, window.location.origin), {
      cache: "no-store",
    });
    return result.options ?? {};
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

  async function requestImageRename(path, from, to) {
    return fetchJson(new URL(RECIPE_IMAGES_RENAME_API, window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, from, to }),
    });
  }

  async function requestImageDelete(path, name) {
    return fetchJson(new URL(RECIPE_IMAGES_DELETE_API, window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, name }),
    });
  }

  async function requestImageUpload(path, file) {
    const requestBody = createRequestBody({ path }, [file]);
    return fetchJson(new URL(RECIPE_IMAGES_UPLOAD_API, window.location.origin), {
      method: "POST",
      cache: "no-store",
      headers: requestBody.headers ?? {},
      body: requestBody.body,
    });
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
      // `input` is a list of Files for image uploads; send them in the order
      // they were chosen so the transcriptions stay in that order too.
      const body = new FormData();
      body.append("inputType", inputType);
      body.append("stream", "true");
      input.forEach((file) => body.append("images", file, file.name));
      return { headers: {}, body };
    }

    return {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inputType, input, stream: true }),
    };
  }

  function parseAiEvent(block) {
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("data:")) data += line.slice(5).trimStart();
    }
    if (!data) return null;
    return JSON.parse(data);
  }

  async function readAiStream(response, onEvent) {
    if (!response.body) throw new Error("The AI progress stream is unavailable.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result;
    let streamError;

    function handleBlock(block) {
      const event = parseAiEvent(block);
      if (!event) return;

      onEvent?.(event);

      if (event.type === "error") {
        streamError = new Error(event.message || "Generation failed.");
      } else if (event.type === "result" && event.result) {
        result = event.result;
      }
    }

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });

      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        handleBlock(buffer.slice(0, separator));
        buffer = buffer.slice(separator + 2);
        separator = buffer.indexOf("\n\n");
      }

      if (done) break;
    }

    if (buffer.trim()) handleBlock(buffer);
    if (streamError) throw streamError;
    if (!result) throw new Error("The AI progress stream ended without a recipe.");
    return result;
  }

  async function requestAiRecipe(inputType, input, onEvent, signal) {
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

    return readAiStream(response, onEvent);
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

  // Metadata values arrive as a list, as a single string, or as a
  // comma-separated string. They are always shown as a list of values.
  function metadataValues(value) {
    if (Array.isArray(value)) {
      return value.map((item) => String(item ?? "").trim()).filter(Boolean);
    }
    if (typeof value === "string" && value.trim()) {
      return value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    return [];
  }

  function firstSource(source) {
    if (Array.isArray(source)) {
      return source.find((item) => item && typeof item === "object") || {};
    }
    return source && typeof source === "object" ? source : {};
  }

  function populateMetadata(refs, metadata) {
    for (const field of ["makes", "difficulty"]) {
      const input = refs.form.elements.namedItem(field);
      const value = metadata[field];

      input.value = value == null ? "" : String(value);
    }

    for (const field of ["tags", "cuisine", "categories", "meals", "status", "contributor"]) {
      refs.pickers.setValues(field, metadataValues(metadata[field]));
    }

    refs.form.elements.namedItem("archived").checked = metadata.archived === true;

    const createdOn = metadata.createdOn;
    refs.form.elements.namedItem("createdOn").value =
      typeof createdOn === "string" ? createdOn.slice(0, 10) : "";

    const source = firstSource(metadata.source);
    for (const field of ["author", "title", "format", "url"]) {
      refs.form.elements.namedItem(`source.${field}`).value = source[field] ?? "";
    }
  }

  function readMetadata(refs) {
    const get = (field) => refs.form.elements.namedItem(field).value.trim();

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

    const readList = (field) => {
      const values = refs.pickers.values(field);
      return values.length ? values : null;
    };

    const readSingle = (field) => refs.pickers.values(field)[0] || null;

    return {
      tags: readList("tags"),
      cuisine: readList("cuisine"),
      categories: readList("categories"),
      meals: readList("meals"),
      makes: parseNumber("makes", true),
      difficulty: parseNumber("difficulty"),
      contributor: readSingle("contributor"),
      status: readSingle("status"),
      createdOn: get("createdOn") || null,
      archived: Boolean(refs.form.elements.namedItem("archived")?.checked),
      source: readSource(refs.form),
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

  // ----- Image pickers ----- //

  function clipboardImageFiles(event) {
    const items = event.clipboardData?.items;
    if (!items) return [];
    return [...items]
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
  }

  function imageFilesFromList(list) {
    return [...(list ?? [])].filter((file) => file.type.startsWith("image/"));
  }

  // A picker wraps a multiple file input, its dashed dropzone, and the line
  // that lists the chosen files. Files can be chosen, dragged in, or pasted
  // from the clipboard, and they are appended so the upload order is kept.
  // `onChange` fires after every change to the input's file list (chosen,
  // pasted, dropped, appended, or reset).
  function createImagePicker({ input, dropzone, selected, isDisabled, onChange }) {
    function showSelected() {
      if (selected) {
        selected.textContent = [...input.files].map((file) => file.name).join(", ");
      }
      onChange?.();
    }

    function append(files) {
      if (!files.length || typeof DataTransfer === "undefined") return false;
      const transfer = new DataTransfer();
      [...input.files, ...files].forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
      showSelected();
      return true;
    }

    function handlePaste(event) {
      // The handler closest to the paste target runs first and marks the
      // event handled, so a paste never lands in two pickers at once.
      if (event.defaultPrevented || isDisabled()) return;
      const pasted = clipboardImageFiles(event);
      if (!pasted.length) return;
      event.preventDefault();
      append(pasted);
    }

    input.addEventListener("change", showSelected);
    input.addEventListener("paste", handlePaste);

    dropzone?.addEventListener("dragover", (event) => {
      if (isDisabled()) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      dropzone.classList.add("is-dragging");
    });
    dropzone?.addEventListener("dragleave", (event) => {
      if (event.currentTarget.contains(event.relatedTarget)) return;
      dropzone.classList.remove("is-dragging");
    });
    dropzone?.addEventListener("drop", (event) => {
      if (isDisabled()) return;
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
      const files = imageFilesFromList(event.dataTransfer?.files);
      if (files.length) append(files);
    });
    // Clicking anywhere in the box opens the file picker; the native input
    // and its label are left alone so the browser does not open it twice.
    dropzone?.addEventListener("click", (event) => {
      if (isDisabled()) return;
      if (event.target === input || event.target.closest("label")) return;
      input.click();
    });

    function reset() {
      input.value = "";
      dropzone?.classList.remove("is-dragging");
      showSelected();
    }

    return { append, handlePaste, reset, showSelected };
  }

  // ----- Existing images and main image ----- //
  //
  // The Files section lists the images that sit next to the recipe Markdown
  // (edit mode only) and offers two controls on top of them:
  //
  // - A "Main image" dropdown that reports the first image link in the
  //   Markdown — the image the recipe page renders as its hero. Picking a
  //   different option rewrites that first link; "None" removes it.
  // - An inline rename field per image. Renaming renames the file on the
  //   server and updates every reference to it (including the hero), so a
  //   pasted image with a generated name can get a sensible one.
  //
  // Both controls edit the Markdown \textarea contents; they never touch the
  // file on disk by themselves (except rename, which the server applies
  // immediately because it changes the directory listing).

  const MARKDOWN_IMAGE_PATTERN = /(!\[[^\]]*\]\()(\s*)(<[^>\n]*>|[^)\s>]+)((?:\s+"[^"]*")?\s*\))/g;
  const HTML_IMAGE_PATTERN = /(<img\b[^>]*?\bsrc\s*=\s*["'])([^"']+)(["'])/gi;
  const CLIENT_IMAGE_EXTENSIONS = new Set([
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".svg",
    ".avif",
  ]);

  function safeDecode(text) {
    try {
      return decodeURIComponent(text);
    } catch {
      return text;
    }
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function stemOf(name) {
    return name.replace(/\.[^.]+$/, "");
  }

  function basenameOf(src) {
    const clean = String(src)
      .split(/[?#]/)[0]
      .replace(/&amp;/g, "&")
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">");
    const segments = clean.split("/").filter(Boolean);
    return segments.length ? safeDecode(segments[segments.length - 1]) : "";
  }

  // Root-absolute paths point at the site copy of an image; anything with a
  // scheme (http:, data:, ...) is an external reference, not a local file.
  function isExternalSrc(src) {
    return /^[a-z][a-z0-9+.-]*:/i.test(src);
  }

  // Strips the angle brackets from a Markdown src token, if present.
  function parseMarkdownSrc(raw) {
    if (raw.startsWith("<") && raw.endsWith(">")) return raw.slice(1, -1);
    return raw;
  }

  // Locates the first image in the document, whether it is written as a
  // Markdown image or an HTML <img> tag. The returned span covers the whole
  // image (for removal) and the src within it (for rewriting).
  function findFirstImageReference(content) {
    let best = null;
    const consider = (spanStart, spanEnd, srcStart, srcEnd, src, kind) => {
      if (best && spanStart >= best.spanStart) return;
      best = { spanStart, spanEnd, srcStart, srcEnd, src, kind };
    };

    MARKDOWN_IMAGE_PATTERN.lastIndex = 0;
    let match;
    while ((match = MARKDOWN_IMAGE_PATTERN.exec(content))) {
      const srcStart = match.index + match[1].length + match[2].length;
      consider(
        match.index,
        match.index + match[0].length,
        srcStart,
        srcStart + match[3].length,
        parseMarkdownSrc(match[3]),
        "markdown",
      );
    }

    HTML_IMAGE_PATTERN.lastIndex = 0;
    while ((match = HTML_IMAGE_PATTERN.exec(content))) {
      const srcStart = match.index + match[1].length;
      consider(
        match.index,
        match.index + match[0].length,
        srcStart,
        srcStart + match[2].length,
        match[2],
        "html",
      );
    }

    return best;
  }

  function needsAngleBrackets(name) {
    return /[\s<>()]/.test(name);
  }

  function markdownSrcFor(name) {
    return needsAngleBrackets(name) ? `<${name}>` : name;
  }

  function htmlSrcFor(name) {
    return name.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  }

  function replacementForSrc(name, kind) {
    return kind === "html" ? htmlSrcFor(name) : markdownSrcFor(name);
  }

  // Replaces every reference to `source` that is not glued to more filename
  // characters. Mirrors the server-side rewrite used by the rename endpoint.
  function renameOccurrences(content, source, target) {
    const pattern = new RegExp(`(^|[^A-Za-z0-9_.-])${escapeRegExp(source)}(?![A-Za-z0-9_.-])`, "g");
    let updated = content.replace(pattern, (_match, prefix) => prefix + target);
    const quoted = encodeURIComponent(source);
    if (quoted !== source) {
      const quotedPattern = new RegExp(
        `(^|[^A-Za-z0-9_.-])${escapeRegExp(quoted)}(?![A-Za-z0-9_.-])`,
        "g",
      );
      updated = updated.replace(
        quotedPattern,
        (_match, prefix) => prefix + encodeURIComponent(target),
      );
    }
    return updated;
  }

  // Removes the image's whole span; when the image sits alone on its line the
  // line goes with it so no blank scaffolding is left behind.
  function removeImageSpan(content, first) {
    const lineStart = content.lastIndexOf("\n", first.spanStart - 1) + 1;
    const lineEndIndex = content.indexOf("\n", first.spanEnd);
    const lineEnd = lineEndIndex === -1 ? content.length : lineEndIndex;
    const before = content.slice(lineStart, first.spanStart);
    const after = content.slice(first.spanEnd, lineEnd);
    if (/^\s*$/.test(before + after)) {
      const removeEnd =
        lineEnd < content.length && content[lineEnd] === "\n" ? lineEnd + 1 : lineEnd;
      return content.slice(0, lineStart) + content.slice(removeEnd);
    }
    return content.slice(0, first.spanStart) + content.slice(first.spanEnd);
  }

  function insertImageIntoMarkdown(content, name) {
    const image = `![${stemOf(name)}](${markdownSrcFor(name)})`;
    const heading = /^#[^\n]*$/m.exec(content);
    if (heading) {
      const insertAt = heading.index + heading[0].length;
      return `${content.slice(0, insertAt)}\n\n${image}${content.slice(insertAt)}`;
    }
    return `${image}\n\n${content}`;
  }

  // Computes which image (if any) is currently the main image: the first
  // image link in the Markdown, as long as it points at a staged or
  // existing image. Returns the image's filename, or "".
  function currentMainImageName(refs, state, content) {
    const first = findFirstImageReference(content);
    if (!first || isExternalSrc(first.src)) return "";
    const basename = basenameOf(first.src);
    const known =
      state.existingImages.some((image) => image.name === basename) ||
      [...(refs.imageInput.files ?? [])].some((file) => file.name === basename);
    return known ? basename : "";
  }

  // Points the first image link at `name` (inserting one after the first
  // heading when the Markdown has none). When `remove` is true the first
  // image link is deleted instead. Returns the textarea's new content.
  function writeMainImage(content, first, name, remove) {
    if (remove) {
      return first ? removeImageSpan(content, first) : content;
    }
    if (!first) {
      return insertImageIntoMarkdown(content, name);
    }
    const replacement = replacementForSrc(name, first.kind);
    return content.slice(0, first.srcStart) + replacement + content.slice(first.srcEnd);
  }

  // Clicking a thumbnail toggles that image as the main image: the first
  // image link in the Markdown is rewritten to point at it (or inserted when
  // there is none). Clicking the current main image removes the link, which
  // is how the hero is cleared.
  function setMainImage(ctx, name) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    const content = refs.textarea.value;
    const first = findFirstImageReference(content);
    const isMain = currentMainImageName(refs, state, content) === name;

    refs.textarea.value = writeMainImage(content, first, name, isMain);
    updateMainImageUi(ctx);
    ui.setStatus(isMain ? `Removed the main image (${name}).` : `"${name}" is now the main image.`);
  }

  // After a delete, check that the main image is still available. If the
  // deleted file was the main image, fall back to the first image in the
  // folder (the list is alphabetical); when no images remain, remove the
  // dangling first image link. Mutates the Markdown buffer; the disk file is
  // updated by the server-side half of this check.
  function applyMainImageFallback(ctx, deletedName, remainingImages) {
    const { refs, state } = ctx;
    const content = refs.textarea.value;
    const first = findFirstImageReference(content);
    if (!first || isExternalSrc(first.src) || basenameOf(first.src) !== deletedName) return null;
    if (remainingImages.length) {
      const target = remainingImages[0].name;
      refs.textarea.value = writeMainImage(content, first, target, false);
      return { replaced: target };
    }
    refs.textarea.value = writeMainImage(content, first, deletedName, true);
    return { removed: true };
  }

  function updateMainImageUi(ctx) {
    const { refs, state } = ctx;
    const selected = currentMainImageName(refs, state, refs.textarea.value);
    const toggles = [
      ...refs.imageList.querySelectorAll(".recipe-editor__image-main"),
      ...refs.stagedList.querySelectorAll(".recipe-editor__image-main"),
    ];
    toggles.forEach((button) => {
      const isMain = button.dataset.name === selected;
      button.classList.toggle("is-main", isMain);
      button.setAttribute("aria-pressed", String(isMain));
      button.title = isMain ? "Remove as main image" : "Set as main image";
    });
  }

  function isRenameCandidate(value) {
    const name = value.trim();
    if (!name || /[\\/<>:"|?*]/.test(name)) return false;
    const dot = name.lastIndexOf(".");
    if (dot <= 0) return false;
    return CLIENT_IMAGE_EXTENSIONS.has(name.slice(dot).toLowerCase());
  }

  function refreshExistingImageControls(ctx) {
    const { refs, state } = ctx;
    refs.imageList.querySelectorAll(".recipe-editor__image-main").forEach((button) => {
      button.disabled = state.busy;
    });
    refs.imageList.querySelectorAll(".recipe-editor__image-item").forEach((item) => {
      const input = item.querySelector(".recipe-editor__image-name");
      const button = item.querySelector(".recipe-editor__image-rename");
      input.disabled = state.busy;
      button.disabled =
        state.busy ||
        input.value.trim() === input.dataset.original ||
        !isRenameCandidate(input.value);
    });
    refs.imageList.querySelectorAll(".recipe-editor__image-remove").forEach((button) => {
      button.disabled = state.busy;
    });
    refs.stagedList.querySelectorAll("button").forEach((button) => {
      button.disabled = state.busy;
    });
  }

  // Shared toggle button for the main image: a thumbnail with a subtle MAIN
  // badge in its upper-left corner; toggling it rewrites the hero link in the
  // Markdown (see setMainImage).
  function createMainToggle(ctx, name, thumbSrc) {
    const mainButton = document.createElement("button");
    mainButton.type = "button";
    mainButton.className = "recipe-editor__image-main";
    mainButton.dataset.name = name;
    mainButton.setAttribute("aria-label", `Set ${name} as the main image`);
    mainButton.setAttribute("aria-pressed", "false");
    mainButton.title = "Set as main image";

    const thumb = document.createElement("img");
    thumb.className = "recipe-editor__image-thumb";
    thumb.src = thumbSrc;
    thumb.alt = "";
    thumb.loading = "lazy";

    const badge = document.createElement("span");
    badge.className = "recipe-editor__main-badge";
    badge.textContent = "MAIN";
    badge.setAttribute("aria-hidden", "true");

    mainButton.append(thumb, badge);
    mainButton.addEventListener("click", () => setMainImage(ctx, name));
    return mainButton;
  }

  // Rename field: the text input with a small Rename button attached inside
  // the right edge of the field. `onSubmit` receives the trimmed new name; it
  // is wired to the server rename for existing images and to a client-side
  // rename of the staged File for new ones.
  function createRenameControls(ctx, name, onSubmit) {
    const { state } = ctx;

    const field = document.createElement("span");
    field.className = "recipe-editor__rename-field";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "recipe-editor__image-name";
    input.value = name;
    input.spellcheck = false;
    input.dataset.original = name;
    input.setAttribute("aria-label", `Rename ${name}`);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "recipe-editor__image-rename";
    button.textContent = "Rename";
    button.disabled = true;

    const syncButton = () => {
      button.disabled =
        state.busy || input.value.trim() === name || !isRenameCandidate(input.value);
    };
    const submit = () => {
      if (button.disabled) return;
      onSubmit(input.value.trim(), input, button);
    };
    input.addEventListener("input", syncButton);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        // Rename, and keep the dialog's implicit submission (the form is
        // method="dialog") from closing or saving the recipe.
        event.preventDefault();
        event.stopPropagation();
        submit();
      }
    });
    button.addEventListener("click", submit);
    field.append(input, button);
    return field;
  }

  function createImageRow(ctx, image) {
    const mainButton = createMainToggle(ctx, image.name, image.url);
    const field = createRenameControls(ctx, image.name, (newName, inputEl, buttonEl) =>
      renameExistingImage(ctx, image.name, inputEl, buttonEl),
    );

    const item = document.createElement("li");
    item.className = "recipe-editor__image-item";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "recipe-editor__image-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Delete ${image.name}`);
    remove.addEventListener("click", () => deleteExistingImage(ctx, image.name, remove));

    item.append(mainButton, field, remove);
    return item;
  }

  function createEmptyImageRow(message) {
    const item = document.createElement("li");
    item.className = "recipe-editor__image-empty";
    item.textContent = message;
    return item;
  }

  function renderExistingImages(ctx) {
    const { refs, state } = ctx;
    const images = Array.isArray(state.existingImages) ? state.existingImages : [];
    refs.imageList.replaceChildren(
      ...(images.length
        ? images.map((image) => createImageRow(ctx, image))
        : [createEmptyImageRow("No images in this folder yet.")]),
    );
    updateMainImageUi(ctx);
    refreshExistingImageControls(ctx);
  }

  function resetExistingImages(ctx) {
    const { refs, state } = ctx;
    state.existingImages = [];
    revokeStagedUrls(state);
    refs.existingImagesBlock.hidden = true;
    refs.imageList.replaceChildren();
    refs.stagedList.hidden = true;
    refs.stagedList.replaceChildren();
  }

  function revokeStagedUrls(state) {
    for (const url of state.stagedUrls) URL.revokeObjectURL(url);
    state.stagedUrls = [];
  }

  function setInputFiles(input, files) {
    if (typeof DataTransfer === "undefined") return false;
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    return true;
  }

  function replaceStagedFile(input, target, replacement) {
    return setInputFiles(
      input,
      [...input.files].map((file) => (file === target ? replacement : file)),
    );
  }

  function removeStagedFile(input, fileToRemove) {
    return setInputFiles(
      input,
      [...input.files].filter((file) => file !== fileToRemove),
    );
  }

  // Renames a staged (not yet uploaded) File in place and fixes Markdown
  // references to the old name, mirroring the server-side rename for
  // images that are already in the folder.
  function renameStagedImage(ctx, file, newName) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    if (!isRenameCandidate(newName)) {
      ui.setStatus(
        "Enter a file name with an image extension (jpg, png, svg, ...) and no path characters.",
      );
      return;
    }
    const renamed = new File([file], newName, { type: file.type, lastModified: file.lastModified });
    if (!replaceStagedFile(refs.imageInput, file, renamed)) {
      ui.setStatus("Renaming staged images is not supported in this browser.");
      return;
    }
    refs.textarea.value = renameOccurrences(refs.textarea.value, file.name, newName);
    renderStagedImages(ctx);
    ui.setStatus(`Renamed "${file.name}" to "${newName}".`);
  }

  function createStagedRow(ctx, file) {
    const { state } = ctx;
    const item = document.createElement("li");
    item.className = "recipe-editor__image-item recipe-editor__staged-item";

    const url = URL.createObjectURL(file);
    state.stagedUrls.push(url);
    const mainButton = createMainToggle(ctx, file.name, url);

    const field = createRenameControls(ctx, file.name, (newName) =>
      renameStagedImage(ctx, file, newName),
    );

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "recipe-editor__image-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Discard staged image ${file.name}`);
    remove.addEventListener("click", () => removeStagedImage(ctx, file));

    const row = [mainButton, field];
    if (!state.isCreating) {
      const upload = document.createElement("button");
      upload.type = "button";
      upload.className = "recipe-editor__image-upload";
      upload.textContent = "Upload";
      upload.setAttribute("aria-label", `Upload ${file.name} to the folder`);
      upload.addEventListener("click", () => uploadStagedImage(ctx, file));
      row.push(upload);
    }
    row.push(remove);

    item.append(...row);
    return item;
  }

  // Re-renders the staged list from the input's file list. In Create mode
  // staged images are saved with the recipe; in Edit Recipe they can also be
  // uploaded one at a time with the Upload button.
  function renderStagedImages(ctx) {
    const { refs, state } = ctx;
    const files = [...(refs.imageInput.files ?? [])];
    revokeStagedUrls(state);
    refs.stagedList.hidden = files.length === 0;
    refs.stagedList.replaceChildren(...files.map((file) => createStagedRow(ctx, file)));
    updateMainImageUi(ctx);
    refreshExistingImageControls(ctx);
  }

  function removeStagedImage(ctx, file) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    removeStagedFile(refs.imageInput, file);
    renderStagedImages(ctx);
    ui.setStatus(`Discarded staged image "${file.name}".`);
  }

  async function uploadStagedImage(ctx, file) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    ui.setBusy(true);
    ui.setStatus(`Uploading "${file.name}"...`);
    try {
      const result = await requestImageUpload(state.markdownPath, file);
      removeStagedFile(refs.imageInput, file);
      state.existingImages = Array.isArray(result.images) ? result.images : state.existingImages;
      renderStagedImages(ctx);
      renderExistingImages(ctx);
      ui.setStatus(`Saved "${file.name}" to the folder.`);
    } catch (error) {
      ui.setStatus(error.message);
    } finally {
      ui.setBusy(false);
    }
  }

  async function deleteExistingImage(ctx, imageName, button) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    if (!confirm(`Delete "${imageName}" from the folder? This cannot be undone.`)) return;
    ui.setBusy(true);
    ui.setStatus(`Deleting "${imageName}"...`);
    try {
      const result = await requestImageDelete(state.markdownPath, imageName);
      const remaining = Array.isArray(result.images) ? result.images : [];
      state.existingImages = remaining;
      // The server has already fallen back the on-disk Markdown; do the same
      // to the buffer so the user sees the change.
      const fallback = applyMainImageFallback(ctx, imageName, remaining);
      renderExistingImages(ctx);
      let message = `Deleted "${imageName}".`;
      if (fallback?.replaced) {
        message += ` Main image is now "${fallback.replaced}".`;
      } else if (fallback?.removed) {
        message += " The main image was removed because no images remain.";
      } else if (result.referenced) {
        message += ` The Markdown still references "${imageName}" — edit the page to fix.`;
      }
      ui.setStatus(message);
    } catch (error) {
      ui.setStatus(error.message);
      button.disabled = false;
    } finally {
      ui.setBusy(false);
    }
  }

  async function renameExistingImage(ctx, oldName, input, button) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    const newName = input.value.trim();
    if (newName === oldName) return;
    if (!isRenameCandidate(newName)) {
      ui.setStatus(
        "Enter a file name with an image extension (jpg, png, svg, ...) and no path characters.",
      );
      return;
    }
    ui.setBusy(true);
    ui.setStatus(`Renaming "${oldName}"...`);
    try {
      const result = await requestImageRename(state.markdownPath, oldName, newName);
      refs.textarea.value = renameOccurrences(refs.textarea.value, oldName, newName);
      state.existingImages = Array.isArray(result.images) ? result.images : [];
      renderExistingImages(ctx);
      ui.setStatus(`Renamed "${oldName}" to "${newName}".`);
    } catch (error) {
      ui.setStatus(error.message);
      button.disabled = false;
    } finally {
      ui.setBusy(false);
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
      imageDropzone: dialog.querySelector(".recipe-editor__recipe-images"),
      stagedList: dialog.querySelector(".recipe-editor__staged-images"),
      imagesHelpEdit: dialog.querySelector(".recipe-editor__images-help--edit"),
      imagesHelpCreate: dialog.querySelector(".recipe-editor__images-help--create"),
      existingImagesBlock: dialog.querySelector(".recipe-editor__existing-images"),
      imageList: dialog.querySelector(".recipe-editor__image-list"),
      aiSection: dialog.querySelector(".recipe-editor__ai"),
      aiDetails: dialog.querySelector(".recipe-editor__ai-details"),
      aiStatus: dialog.querySelector(".recipe-editor__ai-status"),
      aiText: dialog.querySelector(".recipe-editor__ai-text"),
      aiUrl: dialog.querySelector(".recipe-editor__ai-url"),
      aiImage: dialog.querySelector(".recipe-editor__ai-image"),
      aiImageDropzone: dialog.querySelector(".recipe-editor__ai-images"),
      aiImageSelected: dialog.querySelector(
        ".recipe-editor__ai-images .recipe-editor__images-selected",
      ),
      aiTextButton: dialog.querySelector(".recipe-editor__ai-generate-text"),
      aiUrlButton: dialog.querySelector(".recipe-editor__ai-generate-url"),
      aiImageButton: dialog.querySelector(".recipe-editor__ai-generate-image"),
      aiCancelButton: dialog.querySelector(".recipe-editor__ai-cancel"),
      aiControls: null,
      aiImageControls: null,
      aiProgress: null,
      bulkFieldSaves: [...dialog.querySelectorAll(".recipe-editor__bulk-field-save")],
      mixedBadges: [...dialog.querySelectorAll(".recipe-editor__mixed")],
      ratingsDetails: dialog.querySelector(".recipe-editor__ratings-details"),
      bulkList: dialog.querySelector(".recipe-editor__bulk-list"),
      filesDetails: dialog.querySelector(".recipe-editor__details"),
      pickers: null,
    };
  }

  function finalizeDomRefs(refs, state) {
    refs.aiControls = [refs.aiText, refs.aiUrl, refs.aiTextButton, refs.aiUrlButton];
    refs.aiImageControls = [refs.aiImage, refs.aiImageButton];
    refs.aiProgress = RecipeAIProgress.createProgress(refs.aiSection);
    refs.pickers = RecipeMetadataPicker.createPickers(refs.dialog);
    refs.stagedChangeHandler = null;
    refs.recipeImages = createImagePicker({
      input: refs.imageInput,
      dropzone: refs.imageDropzone,
      isDisabled: () => refs.imageInput.disabled,
      onChange: () => refs.stagedChangeHandler?.(),
    });
    refs.aiImages = createImagePicker({
      input: refs.aiImage,
      dropzone: refs.aiImageDropzone,
      selected: refs.aiImageSelected,
      isDisabled: () => refs.aiImage.disabled,
    });
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
      existingImages: [],
      stagedUrls: [],
      aiAvailable: false,
      aiImageAvailable: false,
      aiAbortController: null,
    };
  }

  // ----- UI helpers ----- //

  function createUiActions(ctx) {
    const { refs, state } = ctx;

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

    // Busy rules per subsystem. The AI controls additionally require the
    // configured model to be available, so their rule combines both.
    function setDialogControlsBusy(value) {
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
    }

    function setMetadataBusy(value) {
      refs.form
        .querySelectorAll(".recipe-editor__metadata input, .recipe-editor__metadata select")
        .forEach((input) => {
          input.disabled = value;
        });
      refs.pickers.setDisabled(value);
    }

    function setBulkSaveButtonsBusy(value) {
      refs.bulkFieldSaves.forEach((button) => {
        button.disabled = value;
      });
    }

    function setAiControlsBusy(value) {
      refs.aiControls.forEach((control) => {
        control.disabled = value || !state.aiAvailable;
      });
      refs.aiImageControls.forEach((control) => {
        control.disabled = value || !state.aiImageAvailable;
      });
    }

    function setBusy(value) {
      state.busy = value;
      setDialogControlsBusy(value);
      setMetadataBusy(value);
      setBulkSaveButtonsBusy(value);
      setAiControlsBusy(value);
      refreshExistingImageControls(ctx);
    }

    return {
      setStatus,
      updateFolderControls,
      lockBackgroundScroll,
      unlockBackgroundScroll,
      closeEditor,
      setBusy,
    };
  }

  // ----- AI helpers ----- //

  function createAiActions(ctx) {
    const { refs, state, ui } = ctx;

    function setAiProgress(message) {
      refs.aiProgress.setStatus(message);
    }

    function setAiState(
      configured,
      available,
      imageConfigured = available,
      imageAvailable = imageConfigured,
    ) {
      const { aiDetails } = refs;
      const { isCreating } = state;
      state.aiAvailable = configured && available;
      state.aiImageAvailable = configured && imageConfigured && imageAvailable;
      refs.aiSection.hidden = !configured;
      aiDetails.hidden = !configured || !isCreating;
      if (!state.busy) refs.aiProgress.reset();

      refs.aiControls.forEach((control) => {
        control.disabled = state.busy || !state.aiAvailable;
      });
      refs.aiImageControls.forEach((control) => {
        control.disabled = state.busy || !state.aiImageAvailable;
      });

      if (!configured) {
        setAiProgress("");
      } else if (!available) {
        setAiProgress(
          "The configured local model is unavailable. Start it, then reopen this dialog.",
        );
      } else if (!state.aiImageAvailable) {
        setAiProgress("The image analysis model is not configured. From Images is unavailable.");
      } else {
        setAiProgress("");
      }
    }

    function readAiInput(inputType) {
      if (inputType === "image") {
        const files = [...(refs.aiImage.files ?? [])];
        if (!files.length) return { error: "Choose at least one recipe image first." };
        return { input: files };
      }

      const input = inputType === "url" ? refs.aiUrl.value.trim() : refs.aiText.value.trim();
      if (!input) {
        return { error: inputType === "url" ? "Paste a URL first." : "Paste recipe text first." };
      }
      return { input };
    }

    function aiStartMessage(inputType, input) {
      if (inputType === "url") return `URL received: ${input}`;
      if (inputType === "image") {
        const names = input.map((file) => file.name).join(", ");
        if (input.length === 1) return `Image received: ${names}`;
        return `${input.length} images received: ${names}`;
      }
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
      refs.aiProgress.start(aiStartMessage(inputType, input));
      ui.setStatus("");

      try {
        const result = await requestAiRecipe(
          inputType,
          input,
          (event) => refs.aiProgress.handle(event),
          controller.signal,
        );
        if (!controller.signal.aborted) {
          refs.aiProgress.setStatus(
            "Recipe draft ready. Review it, then create the recipe.",
            "complete",
          );
          refs.textarea.value = result.content || "";
          populateMetadata(refs, result.metadata || {});
        }
      } catch (caughtError) {
        if (caughtError.name === "AbortError") {
          refs.aiProgress.setStatus("Generation cancelled.", "idle");
        } else {
          refs.aiProgress.setStatus(`Generation failed: ${caughtError.message}`, "error");
        }
      } finally {
        if (state.aiAbortController === controller) state.aiAbortController = null;
        refs.aiCancelButton.hidden = true;
        ui.setBusy(false);
      }
    }

    return { setAiProgress, setAiState, generateFromAi };
  }

  // Plays the "I made this!" celebration on `element`: the element replays
  // its CSS animation and a row of sparkles arcs inside `container`. Skipped
  // entirely when the user prefers reduced motion.
  function celebrate(element, container) {
    element.classList.remove("is-celebrating");
    // Restart the CSS animation on repeat clicks.
    void element.offsetWidth;
    element.classList.add("is-celebrating");

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const particles = SPARKLE_GLYPHS.map((glyph, index) => {
      const particle = document.createElement("span");
      particle.className = "recipe-editor__sparkle";
      particle.textContent = glyph;
      particle.setAttribute("aria-hidden", "true");
      particle.style.setProperty(
        "--sparkle-x",
        `${(index - SPARKLE_CENTER_INDEX) * SPARKLE_SPREAD_PX}px`,
      );
      particle.style.setProperty("--sparkle-delay", `${index * SPARKLE_STAGGER_MS}ms`);
      container.append(particle);
      return particle;
    });

    window.setTimeout(() => {
      particles.forEach((particle) => particle.remove());
      element.classList.remove("is-celebrating");
    }, SPARKLE_LIFETIME_MS);
  }

  // ----- "Made this" helpers ----- //

  function createMadeThisActions(ctx) {
    const { refs, state, ui } = ctx;

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
        celebrate(refs.madeThisButton, refs.header);
      } catch (error) {
        handleMadeThisError(error, makes, savedToFile);
      } finally {
        ui.setBusy(false);
      }
    }

    function handleMadeThisError(error, makes, savedToFile) {
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
        celebrate(refs.madeThisButton, refs.header);
        return;
      }

      ui.setStatus(`Couldn't record your make — ${message} Please try again.`);
    }

    return { updateMadeThisCount, recordMadeThis };
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
    refs.mixedBadges.forEach((badge) => {
      badge.hidden = true;
    });
    refs.bulkFieldSaves.forEach((button) => {
      button.hidden = true;
    });
    refs.dialog.classList.remove("is-bulk");
    refs.dialog.querySelectorAll("label.is-mixed").forEach((element) => {
      element.classList.remove("is-mixed");
    });
  }

  function setBulkFieldChrome(refs, visible) {
    refs.bulkFieldSaves.forEach((button) => {
      button.hidden = !visible;
    });
    refs.dialog.classList.toggle("is-bulk", visible);
    if (!visible)
      refs.mixedBadges.forEach((badge) => {
        badge.hidden = true;
      });
  }

  function findFieldLabel(refs, field) {
    const picker = refs.pickers.get(field);
    if (picker) return picker.element.closest("label");
    return refs.form.elements.namedItem(field)?.closest("label");
  }

  function showMixed(refs, inputName) {
    const label = findFieldLabel(refs, inputName);
    const badge = label?.querySelector(".recipe-editor__mixed");
    if (!label || !badge) return;
    badge.hidden = false;
    label.classList.add("recipe-editor__field-label", "is-mixed");
  }

  function markMixedSourceFields(ctx) {
    const { refs, state } = ctx;
    for (const subfield of ["author", "title", "format", "url"]) {
      const first = JSON.stringify(
        firstSource(state.bulkRecipes[0].metadata.source)[subfield] ?? null,
      );
      const mixed =
        state.bulkRecipes.length > 1 &&
        state.bulkRecipes.some(
          (recipe) =>
            JSON.stringify(firstSource(recipe.metadata.source)[subfield] ?? null) !== first,
        );
      if (mixed) showMixed(refs, `source.${subfield}`);
    }
  }

  function markMixedFields(ctx) {
    const { refs, state } = ctx;
    refs.mixedBadges.forEach((badge) => {
      badge.hidden = true;
    });
    refs.dialog.querySelectorAll("label.is-mixed").forEach((element) => {
      element.classList.remove("is-mixed");
    });
    for (const field of Object.keys(BULK_FIELD_LABELS)) {
      if (field === "source") markMixedSourceFields(ctx);
      else if (isMixed(state.bulkRecipes, field)) showMixed(refs, field);
    }
    const ratingsDiffer =
      state.bulkRecipes.length > 1 &&
      state.bulkRecipes.some(
        (recipe) => JSON.stringify(recipe.ratings) !== JSON.stringify(state.bulkRecipes[0].ratings),
      );
    if (ratingsDiffer) showMixed(refs, "rating.name");
  }

  async function saveBulkField(ctx, field) {
    const { refs, state, ui } = ctx;
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
    const metadata = readMetadata(refs);
    await requestBulkSave(state.bulkPaths, { metadata, fields: [field] });
    ui.setStatus(`${label} saved to ${state.bulkPaths.length} recipes! Reloading...`);
    window.location.reload();
  }

  function setupBulkFieldButtons(ctx) {
    const { refs, state, ui } = ctx;
    refs.bulkFieldSaves.forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (state.busy || !state.isBulk) return;
        try {
          await saveBulkField(ctx, button.dataset.field);
        } catch (error) {
          ui.setStatus(error.message);
          ui.setBusy(false);
        }
      });
    });
  }

  function createBulkActions(ctx) {
    return {
      resetBulkFieldChrome: () => resetBulkFieldChrome(ctx.refs),
      setBulkFieldChrome: (visible) => setBulkFieldChrome(ctx.refs, visible),
      markMixedFields: () => markMixedFields(ctx),
      setupBulkFieldButtons: () => setupBulkFieldButtons(ctx),
      readBulkRating: () => readBulkRating(ctx.refs.form, ctx.ui.setStatus),
    };
  }

  // ----- Session/open/save/delete flows ----- //

  // Shared reset for opening the dialog, used by both the single-recipe and
  // the bulk path. Each helper sets one slice of the chrome.
  function hideMadeThisControls(refs) {
    refs.madeThisButton.hidden = true;
    refs.madeThisCount.hidden = true;
  }

  function setDetailsVisibility(refs, { ratings, bulkList, files, markdown }) {
    refs.ratingsDetails.hidden = !ratings;
    refs.bulkList.hidden = !bulkList;
    refs.filesDetails.hidden = !files;
    refs.markdownDetails.hidden = !markdown;
  }

  function setActionLabels(refs, { heading, saveLabel, deleteLabel, locationVisible }) {
    refs.heading.textContent = heading;
    refs.saveButton.textContent = saveLabel;
    refs.deleteButton.textContent = deleteLabel;
    refs.location.hidden = !locationVisible;
  }

  function resetCommonOpenState(ctx) {
    const { refs, state, ui } = ctx;
    state.activeButton = null;
    document.body.classList.add("recipe-editor-open");
    ui.lockBackgroundScroll();
    if (!refs.dialog.open) refs.dialog.showModal();
    refs.textarea.value = "";
    state.originalContent = "";
    state.originalMetadata = "";
    ui.setStatus("");
  }

  function resetAiOpenState(ctx) {
    const { refs, state } = ctx;
    refs.aiSection.hidden = true;
    refs.aiDetails.hidden = true;
    refs.aiDetails.open = false;
    state.aiAvailable = false;
    state.aiImageAvailable = false;
    state.aiAbortController = null;
    refs.aiProgress.reset();
    refs.aiText.value = "";
    refs.aiUrl.value = "";
    refs.aiImages.reset();
    refs.aiCancelButton.hidden = true;
  }

  // The dropdown options come from the recipes that are already in the
  // library. They are read from the server on every open so a value that was
  // just added to another recipe shows up right away.
  async function refreshMetadataOptions(ctx) {
    const { refs } = ctx;
    try {
      const options = await requestMetadataOptions();
      Object.entries(options).forEach(([field, values]) => {
        refs.pickers.setOptions(field, values);
      });
    } catch {
      // Without the library values the dropdowns only offer "Add new".
    }
  }

  async function openBulkEditor(ctx, paths) {
    const { refs, state, ui, bulk } = ctx;
    if (state.busy || !paths?.length) return;
    state.isBulk = true;
    state.isCreating = false;
    state.bulkPaths = [...paths];
    state.markdownPath = "";
    resetCommonOpenState(ctx);
    setActionLabels(refs, {
      heading: `Bulk Edit Recipes (${state.bulkPaths.length} selected)`,
      saveLabel: "Save All",
      deleteLabel: `Delete ${state.bulkPaths.length} Recipes`,
      locationVisible: false,
    });
    setDetailsVisibility(refs, { ratings: true, bulkList: true, files: false, markdown: false });
    refs.existingImagesBlock.hidden = true;
    refs.bulkList.textContent = state.bulkPaths.join(", ");
    refs.ratingsDetails.open = true;
    refs.aiDetails.hidden = true;
    refs.deleteButton.hidden = false;
    hideMadeThisControls(refs);
    bulk.resetBulkFieldChrome();
    bulk.setBulkFieldChrome(true);
    ui.setStatus("Loading recipes…");
    ui.setBusy(true);
    try {
      await refreshMetadataOptions(ctx);
      state.bulkRecipes = await requestBulkEditor(state.bulkPaths);
      populateMetadata(refs, state.bulkRecipes[0].metadata);
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

  async function loadCreateMode(ctx) {
    const { refs, ui, ai } = ctx;
    refs.deleteButton.hidden = true;
    hideMadeThisControls(refs);
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
    populateMetadata(refs, {});
    refs.textarea.value = NEW_RECIPE_TEMPLATE;
    try {
      const status = await requestAiStatus();
      const configured = Boolean(status.configured);
      const available = Boolean(status.available);
      const imageConfigured =
        status.image_configured === undefined ? configured : Boolean(status.image_configured);
      const imageAvailable =
        status.image_available === undefined ? available : Boolean(status.image_available);
      ai.setAiState(configured, available, imageConfigured, imageAvailable);
    } catch {
      ai.setAiState(false, false);
    }
  }

  async function loadEditMode(ctx) {
    const { refs, state, madeThis } = ctx;
    state.markdownPath = getMarkdownPath();
    const result = await requestEditor(state.markdownPath);
    state.originalContent = result.content;
    refs.textarea.value = result.content;
    populateMetadata(refs, result.metadata);
    state.originalMetadata = JSON.stringify(readMetadata(refs));
    madeThis.updateMadeThisCount(normalizeMakes(result.metadata.makes));
    state.existingImages = Array.isArray(result.images) ? result.images : [];
    renderExistingImages(ctx);
    refs.existingImagesBlock.hidden = false;
    refs.deleteButton.hidden = false;
    refs.madeThisButton.hidden = false;
    refs.madeThisCount.hidden = false;
  }

  function prepareEditorOpen(ctx, mode) {
    const { refs, state, madeThis, bulk } = ctx;
    state.activeButton = mode === "create" ? state.createButton : state.editButton;
    state.isCreating = mode === "create";
    state.isBulk = false;
    state.bulkPaths = [];
    state.bulkRecipes = [];
    state.markdownPath = "";
    bulk.resetBulkFieldChrome();
    setDetailsVisibility(refs, { ratings: false, bulkList: false, files: true, markdown: true });
    refs.markdownDetails.open = false;
    setActionLabels(refs, {
      heading: state.isCreating ? "Create Recipe" : "Edit Recipe",
      saveLabel: state.isCreating ? "Create" : "Save",
      deleteLabel: "Delete",
      locationVisible: state.isCreating,
    });
    hideMadeThisControls(refs);
    madeThis.updateMadeThisCount(0);
    refs.madeThisButton.textContent = "I made this!";
    refs.recipeImages.reset();
    refs.imagesHelpEdit.hidden = state.isCreating;
    refs.imagesHelpCreate.hidden = !state.isCreating;
    resetExistingImages(ctx);
  }

  async function openEditor(ctx, mode) {
    const { refs, state, ui } = ctx;
    if (state.busy) return;
    prepareEditorOpen(ctx, mode);
    resetCommonOpenState(ctx);
    resetAiOpenState(ctx);
    ui.setBusy(true);
    try {
      await refreshMetadataOptions(ctx);
      if (state.isCreating) await loadCreateMode(ctx);
      else await loadEditMode(ctx);
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

  async function submitBulkSave(ctx, metadata) {
    const { refs, state, ui, bulk } = ctx;
    const ratingName = refs.form.elements.namedItem("rating.name")?.value.trim();
    const ratingScore = refs.form.elements.namedItem("rating.score")?.value.trim();
    let rating = null;
    if (ratingName || ratingScore) {
      rating = bulk.readBulkRating();
      if (!rating) {
        ui.setBusy(false);
        return false;
      }
    }
    await requestBulkSave(state.bulkPaths, { metadata, ...(rating ? { rating } : {}) });
    return true;
  }

  async function submitEditorSave(ctx, metadata, content, images) {
    const { refs, state, ui } = ctx;
    if (state.isBulk) return submitBulkSave(ctx, metadata);
    if (state.isCreating) {
      let folder =
        refs.folderMode.value === "new" ? refs.newFolder.value.trim() : refs.folderSelect.value;
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

  async function handleSubmit(ctx, event) {
    const { refs, state, ui } = ctx;
    event.preventDefault();
    if (state.busy) return;
    let metadata;
    try {
      metadata = readMetadata(refs);
    } catch (error) {
      ui.setStatus(error.message);
      return;
    }
    const content = refs.textarea.value;
    const metadataContent = JSON.stringify(metadata);
    const images = [...refs.imageInput.files];
    if (!hasUnsavedChanges(state, content, metadataContent, images.length)) {
      refs.dialog.close();
      return;
    }
    ui.setBusy(true);
    ui.setStatus(
      state.isCreating ? "Creating recipe…" : state.isBulk ? "Saving recipes…" : "Saving recipe…",
    );
    try {
      const completed = await submitEditorSave(ctx, metadata, content, images);
      if (!completed) return;
      ui.setStatus(state.isCreating ? "Created! Reloading…" : "Saved! Reloading…");
      window.location.reload();
    } catch (error) {
      ui.setStatus(error.message);
      ui.setBusy(false);
    }
  }

  // The two delete paths (bulk and single recipe) differ only in the confirm
  // text, the endpoint, and the redirect message.
  function deletePlan(state) {
    return state.isBulk
      ? {
          question: `Delete ${state.bulkPaths.length} selected recipes? This cannot be undone.`,
          pendingStatus: "Deleting recipes…",
          doneStatus: "Recipes deleted! Redirecting to the index…",
          execute: () => requestBulkDelete(state.bulkPaths),
        }
      : {
          question: "Are you sure you want to delete this recipe? This action cannot be undone.",
          pendingStatus: "Deleting recipe…",
          doneStatus: "Recipe deleted! Redirecting to the index…",
          execute: () => deleteRecipe(state.markdownPath),
        };
  }

  async function handleDelete(ctx) {
    const { state, ui } = ctx;
    if (state.busy) return;
    const plan = deletePlan(state);
    if (!confirm(plan.question)) return;
    try {
      ui.setBusy(true);
      ui.setStatus(plan.pendingStatus);
      await plan.execute();
      ui.setStatus(plan.doneStatus);
      window.location.href = "/index.html";
    } catch (error) {
      ui.setStatus(error.message);
      ui.setBusy(false);
    }
  }

  function createSessionActions(ctx) {
    return {
      openBulkEditor: (paths) => openBulkEditor(ctx, paths),
      openEditor: (mode) => openEditor(ctx, mode),
      handleSubmit: (event) => handleSubmit(ctx, event),
      handleDelete: () => handleDelete(ctx),
    };
  }

  // ----- Event registration ----- //

  function registerDialogDismissListeners(ctx) {
    const { refs, state, ui } = ctx;
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

  function registerControlListeners(ctx) {
    const { refs, state, ui, ai, madeThis, session } = ctx;
    const { madeThisButton, markdownDetails, textarea } = refs;
    const { recordMadeThis } = madeThis;

    if (state.editButton)
      state.editButton.addEventListener("click", () => session.openEditor("edit"));
    if (state.createButton)
      state.createButton.addEventListener("click", () => session.openEditor("create"));

    refs.folderMode.addEventListener("change", ui.updateFolderControls);
    textarea.addEventListener("input", () => {
      if (state.isCreating) return;
      updateMainImageUi(ctx);
    });

    // Pasting anywhere in the dialog adds the image to the recipe images.
    // The AI image picker handles its own paste first and marks it handled.
    refs.dialog.addEventListener("paste", refs.recipeImages.handlePaste);

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

  function registerListeners(ctx) {
    registerDialogDismissListeners(ctx);
    registerControlListeners(ctx);
  }

  function initPageMadeThis() {
    const button = document.querySelector(".recipe-overview__makes");
    if (!button) return;

    let busy = false;
    const markdownPath = getMarkdownPath();
    const valueElement = button.querySelector(".recipe-overview__value");

    button.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      button.disabled = true;

      try {
        const current = normalizeMakes(button.dataset.makes);
        const makes = (await getMakes(markdownPath)) + 1;
        await saveMakes(markdownPath, makes);
        button.dataset.makes = String(makes);
        if (valueElement) valueElement.textContent = makesCountLabel(makes);
        celebrate(button, button);
      } catch (error) {
        // Keep the page responsive even if the save fails.
        console.error(error);
      } finally {
        button.disabled = false;
        busy = false;
      }
    });
  }

  // ----- Bootstrap ----- //

  async function initialize() {
    initPageMadeThis();

    const editButton = document.querySelector("#edit-recipe");
    const createButton = document.querySelector("#create-recipe");
    if (!editButton && !createButton) return;

    const dialog = await createEditor();
    const state = createState(editButton, createButton);

    // The collaborators are bundled into a single context object that is
    // threaded through the flows below, instead of passing each of them
    // positionally.
    const ctx = {
      refs: finalizeDomRefs(collectDomRefs(dialog), state),
      state,
    };

    if (ctx.refs.makesIcon) {
      // The chef-hat icon is inlined so it can inherit currentColor.
      ctx.refs.makesIcon.innerHTML = await RecipeIcons.loadSvgIcon(CHEF_HAT_ICON_URL);
    }

    ctx.ui = createUiActions(ctx);
    ctx.ai = createAiActions(ctx);
    ctx.madeThis = createMadeThisActions(ctx);
    ctx.bulk = createBulkActions(ctx);
    ctx.session = createSessionActions(ctx);

    ctx.bulk.setupBulkFieldButtons();
    ctx.bulk.resetBulkFieldChrome();

    // The staged-images refresh runs with the assembled context so the
    // rows it creates reach the UI collaborators (status, busy state).
    ctx.refs.stagedChangeHandler = () => renderStagedImages(ctx);

    document.addEventListener("bulk-edit", (event) => {
      ctx.session.openBulkEditor(event.detail?.paths);
    });
    registerListeners(ctx);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
