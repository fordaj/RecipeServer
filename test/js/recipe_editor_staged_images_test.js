"use strict";

// Behavioural checks for the staged-images UI. The recipe editor's image
// section is loaded from recipe-editor.js into the DOM stub, wired the way
// initialize() wires it (the picker's onChange goes through
// refs.stagedChangeHandler with the fully assembled context), and the
// staged-upload and delete flows are driven from clicks.

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
  return { success: true, images: [], referenced: false };
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
  mainImageSelect: element("select"),
  mainImagePreview: element("img"),
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

(async () => {
  // Two images are staged; rows appear when the refresh runs.
  refs.imageInput.files = [{ name: "saved.png" }, { name: "another.png" }];
  refs.stagedChangeHandler();
  assert.equal(refs.stagedList.hidden, false);
  assert.equal(refs.stagedList.childNodes.length, 2);
  assert.equal(refs.selectedImages.textContent, "2 image(s) staged for upload.");

  renderExistingImages(ctx);
  assert.equal(refs.imageList.childNodes.length, 1);
  assert.equal(refs.mainImageSelect.value, "keep.jpg");

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

  // The X on a staged row discards it after a confirm.
  refs.stagedList.childNodes[0].querySelector(".recipe-editor__image-remove").click();
  assert.deepEqual(
    [...refs.imageInput.files].map((file) => file.name),
    [],
  );
  assert.equal(refs.stagedList.hidden, true);
  assert.equal(confirms.length, 1);

  // The X on an uploaded row deletes it after a confirm.
  refs.imageList.childNodes[0].querySelector(".recipe-editor__image-remove").click();
  await tick();
  assert.equal(fetchCalls[1].name, "keep.jpg");
  assert.equal(refs.imageList.childNodes.length, 1); // empty-state row
  assert.equal(confirms.length, 2);
  assert.ok(statuses.some((message) => message.includes('Deleted "keep.jpg"')));

  console.log("staged images flow checks passed");
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
