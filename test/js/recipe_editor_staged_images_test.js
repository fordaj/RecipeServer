"use strict";

// Behavioural checks for the staged-images UI. The recipe editor's image
// section is loaded from recipe-editor.js into the DOM stub, wired the way
// initialize() wires it (the picker's onChange goes through
// refs.stagedChangeHandler with the fully assembled context), and the
// staged-upload, delete, and main-image flows are driven from clicks.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const EDITOR_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "recipe-editor",
  "recipe-editor.js",
);

function loadImageSection() {
  const source = fs.readFileSync(EDITOR_JS, "utf8");
  const start = source.indexOf("  // ----- Existing images and main image ----- //");
  const end = source.indexOf("  // ----- Initialize: DOM refs and state ----- //");
  assert.notEqual(start, -1, "image section marker not found");
  assert.notEqual(end, -1, "initialize marker not found");
  return source
    .slice(start, end)
    .split("\n")
    .map((line) => line.slice(2))
    .join("\n");
}

const document = createDocument();
const fetchCalls = [];
const statuses = [];
const confirms = [];

class Option {
  constructor(text, value) {
    this.textContent = text;
    this.value = value ?? text;
  }
}

global.document = document;
global.Option = Option;
global.confirm = (message) => {
  confirms.push(message);
  return true;
};
global.URL.createObjectURL = (file) => `blob:${file.name}`;
global.URL.revokeObjectURL = () => {};
global.DataTransfer = class DataTransfer {
  constructor() {
    this._files = [];
  }

  get items() {
    const self = this;
    return {
      add(file) {
        self._files.push(file);
      },
    };
  }

  set files(value) {
    this._files = [...value];
  }

  get files() {
    return this._files;
  }
};
global.requestImageUpload = async (path, file) => {
  fetchCalls.push({ path, file: file.name });
  return { success: true, images: [{ name: "keep.jpg", url: "/Dinner/keep.jpg" }] };
};
global.requestImageDelete = async (path, name) => {
  fetchCalls.push({ path, name });
  if (name === "keep.jpg") {
    return { success: true, images: [], referenced: true };
  }
  return {
    success: true,
    images: [{ name: "keep.jpg", url: "/Dinner/keep.jpg" }],
    referenced: false,
  };
};

const moduleInstance = new module.constructor();
moduleInstance._compile(
  `${loadImageSection()}\nmodule.exports = { renderStagedImages, renderExistingImages };`,
  "recipe-editor-images.js",
);
const { renderStagedImages, renderExistingImages } = moduleInstance.exports;

function element(tagName, className) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  return node;
}

const refs = {
  imageInput: element("input"),
  stagedList: element("ul"),
  selectedImages: element("p"),
  existingImagesBlock: element("div"),
  imageList: element("ul"),
  textarea: element("textarea"),
  stagedChangeHandler: null,
};
refs.textarea.value = "# Soup\n\n![Hero](keep.jpg)\n";
document.body.append(refs.imageInput, refs.stagedList, refs.imageList, refs.selectedImages);

const state = {
  isCreating: false,
  busy: false,
  existingImages: [{ name: "keep.jpg", url: "/Dinner/keep.jpg" }],
  stagedUrls: [],
  markdownPath: "Dinner/recipe.md",
};
const ctx = {
  refs,
  state,
  ui: { setStatus: (message) => statuses.push(message), setBusy: () => {} },
};

// Wire the refresh like initialize() does: through stagedChangeHandler with
// the fully assembled context, not a partial { refs, state } object.
refs.stagedChangeHandler = () => renderStagedImages(ctx);

async function tick(times = 4) {
  for (let index = 0; index < times; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

function mainButton(row) {
  return row.querySelector(".recipe-editor__image-main");
}

(async () => {
  // Two images are staged; rows appear when the refresh runs.
  refs.imageInput.files = [{ name: "saved.png" }, { name: "another.png" }];
  refs.stagedChangeHandler();
  assert.equal(refs.stagedList.hidden, false);
  assert.equal(refs.stagedList.childNodes.length, 2);
  assert.equal(refs.selectedImages.textContent, "2 image(s) staged for upload.");

  // Existing image rows carry a MAIN toggle button and mark the hero.
  state.existingImages = [{ name: "keep.jpg", url: "/Dinner/keep.jpg" }];
  renderExistingImages(ctx);
  assert.equal(refs.imageList.childNodes.length, 1);
  const keepButton = mainButton(refs.imageList.childNodes[0]);
  assert.equal(keepButton.getAttribute("aria-pressed"), "true");
  assert.ok(keepButton.classList.contains("is-main"));
  assert.ok(keepButton.querySelector(".recipe-editor__main-badge"));

  // Uploading a staged image saves it, refreshes the UI, and removes it
  // from the pending-upload list.
  refs.stagedList.childNodes[0].querySelector(".recipe-editor__image-upload").click();
  await tick();
  assert.deepEqual(
    [...refs.imageInput.files].map((file) => file.name),
    ["another.png"],
  );
  assert.equal(fetchCalls[0].file, "saved.png");
  assert.equal(refs.selectedImages.textContent, "1 image(s) staged for upload.");
  assert.ok(statuses.some((message) => message.includes('Saved "saved.png"')));

  // The X on a staged row discards it without a confirm.
  refs.stagedList.childNodes[0].querySelector(".recipe-editor__image-remove").click();
  assert.deepEqual(
    [...refs.imageInput.files].map((file) => file.name),
    [],
  );
  assert.equal(refs.stagedList.hidden, true);
  assert.equal(confirms.length, 0);

  // Deleting the hero falls back to the alphabetically-first remaining
  // image (none remain here, so the dangling link is removed).
  refs.imageList.childNodes[0].querySelector(".recipe-editor__image-remove").click();
  await tick();
  assert.equal(fetchCalls[1].name, "keep.jpg");
  assert.equal(refs.imageList.childNodes.length, 1); // empty-state row
  assert.equal(confirms.length, 1);
  assert.equal(refs.textarea.value.includes("![Hero](keep.jpg)"), false);
  assert.ok(statuses.some((message) => message.includes('Deleted "keep.jpg"')));

  // Mark a new hero by clicking its thumbnail's main-image toggle.
  state.existingImages = [
    { name: "a.jpg", url: "/Dinner/a.jpg" },
    { name: "b.jpg", url: "/Dinner/b.jpg" },
  ];
  refs.textarea.value = "# Soup\n\n![Hero](a.jpg)\n";
  renderExistingImages(ctx);
  const bButton = mainButton(refs.imageList.childNodes[1]);
  const aButton = mainButton(refs.imageList.childNodes[0]);
  assert.equal(aButton.getAttribute("aria-pressed"), "true");
  assert.equal(bButton.getAttribute("aria-pressed"), "false");
  bButton.click();
  assert.equal(refs.textarea.value, "# Soup\n\n![Hero](b.jpg)\n");
  assert.equal(bButton.getAttribute("aria-pressed"), "true");
  assert.equal(aButton.getAttribute("aria-pressed"), "false");

  // Clicking the current main image clears the hero again.
  bButton.click();
  assert.equal(refs.textarea.value.includes("![Hero]"), false);
  assert.equal(bButton.getAttribute("aria-pressed"), "false");

  // Create Recipe: staged rows are below the dropzone, have a main-image
  // toggle and rename/X controls, but no Upload button. Clicking the toggle
  // rewrites the Markdown hero, and renaming a staged file fixes the hero
  // reference too.
  const createState = {
    isCreating: true,
    busy: false,
    existingImages: [],
    stagedUrls: [],
    markdownPath: "",
  };
  refs.stagedChangeHandler = () => renderStagedImages({ refs, state: createState, ui: ctx.ui });
  refs.imageInput.files = [new File(["image-bytes"], "zphoto.jpg", { type: "image/jpeg" })];
  refs.textarea.value = "# New Recipe\n\n![Alt Text](image.png)\n\n## Ingredients\n\n- carrots\n";
  refs.stagedChangeHandler();

  assert.equal(refs.stagedList.hidden, false);
  assert.equal(refs.stagedList.childNodes.length, 1);
  const stagedRow = refs.stagedList.childNodes[0];
  assert.equal(stagedRow.querySelector(".recipe-editor__image-upload"), null);
  assert.equal(stagedRow.querySelector(".recipe-editor__image-remove") !== null, true);

  const toggle = mainButton(stagedRow);
  toggle.click();
  assert.equal(
    refs.textarea.value,
    "# New Recipe\n\n![Alt Text](zphoto.jpg)\n\n## Ingredients\n\n- carrots\n",
  );
  assert.equal(toggle.getAttribute("aria-pressed"), "true");

  // Renaming the staged file renames it in the input and in the Markdown.
  const renameInput = stagedRow.querySelector(".recipe-editor__image-name");
  const renameButton = stagedRow.querySelector(".recipe-editor__image-rename");
  renameInput.value = "hero.jpg";
  renameInput.dispatchEvent({ type: "input", target: renameInput });
  assert.equal(renameButton.disabled, false);
  renameButton.click();
  assert.equal(
    refs.textarea.value,
    "# New Recipe\n\n![Alt Text](hero.jpg)\n\n## Ingredients\n\n- carrots\n",
  );
  assert.deepEqual(
    [...refs.imageInput.files].map((file) => file.name),
    ["hero.jpg"],
  );
  assert.ok(statuses.some((message) => message.includes('Renamed "zphoto.jpg" to "hero.jpg".')));

  console.log("staged images flow checks passed");
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
