"use strict";

// Behavioural checks for the "Paste from clipboard" button in the recipe
// editor image dropzones. createImagePicker is loaded from recipe-editor.js
// into the DOM stub and driven the way the browser drives it, with a stubbed
// async Clipboard API.

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

function loadImagePickers() {
  const source = fs.readFileSync(EDITOR_JS, "utf8");
  const start = source.indexOf("  // ----- Image pickers ----- //");
  const end = source.indexOf("  // ----- Existing images and main image ----- //");
  assert.notEqual(start, -1, "image picker section marker not found");
  assert.notEqual(end, -1, "existing images section marker not found");
  return source
    .slice(start, end)
    .split("\n")
    .map((line) => line.slice(2))
    .join("\n");
}

const document = createDocument();

global.document = document;
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
global.RecipeIcons = { loadSvgIcon: async () => "<svg></svg>" };

function setClipboardRead(read) {
  Object.defineProperty(globalThis, "navigator", {
    value: read ? { clipboard: { read } } : {},
    configurable: true,
    writable: true,
  });
}

const moduleInstance = new module.constructor();
moduleInstance._compile(
  `const CLIPBOARD_PASTE_ICON_URL = "/assets/clipboard-paste.svg";\n${loadImagePickers()}\nmodule.exports = { createImagePicker };`,
  "recipe-editor-pickers.js",
);
const { createImagePicker } = moduleInstance.exports;

function element(tagName, className) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  return node;
}

function buildDropzone() {
  const dropzone = element("div", "recipe-editor__images");
  const input = element("input");
  input.type = "file";
  input.files = [];
  input.clicked = false;
  input.click = () => {
    input.clicked = true;
  };
  const button = element("button", "recipe-editor__paste-clipboard");
  button.hidden = true;
  const icon = element("span", "recipe-editor__paste-clipboard-icon");
  button.append(icon);
  dropzone.append(input, button);
  document.body.append(dropzone);
  return { dropzone, input, button };
}

function clipboardItem(type, bytes) {
  return {
    types: [type, "text/plain"],
    async getType(wanted) {
      if (wanted !== type) throw new Error(`unexpected type ${wanted}`);
      return new Blob([bytes], { type });
    },
  };
}

function notices() {
  const messages = [];
  return {
    messages,
    notify: (message) => messages.push(message),
  };
}

async function tick(times = 6) {
  for (let index = 0; index < times; index += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

(async () => {
  // The button stays hidden when the async Clipboard API is unavailable.
  setClipboardRead(null);
  {
    const { dropzone, input, button } = buildDropzone();
    const { messages, notify } = notices();
    createImagePicker({
      input,
      dropzone,
      isDisabled: () => false,
      onNotify: notify,
    });
    assert.equal(button.hidden, true);
    assert.deepEqual(messages, []);
  }

  // The button is revealed when the API exists, and clicking it stages the
  // clipboard image instead of opening the native file picker.
  setClipboardRead(async () => [clipboardItem("image/png", "png-bytes")]);
  {
    const { dropzone, input, button } = buildDropzone();
    const { messages, notify } = notices();
    let changes = 0;
    createImagePicker({
      input,
      dropzone,
      isDisabled: () => false,
      onChange: () => {
        changes += 1;
      },
      onNotify: notify,
    });
    assert.equal(button.hidden, false);

    button.click();
    await tick();

    assert.equal(input.clicked, false, "the file picker must not open for clipboard pastes");
    assert.equal(input.files.length, 1);
    assert.match(input.files[0].name, /^pasted-image-\d+-1\.png$/);
    assert.equal(input.files[0].type, "image/png");
    assert.equal(changes, 1);
    assert.equal(messages.length, 1);
    assert.match(messages[0], /from the clipboard\./);
  }

  // Multiple clipboard images keep their order and get distinct names.
  setClipboardRead(async () => [
    clipboardItem("image/png", "one"),
    clipboardItem("image/jpeg", "two"),
  ]);
  {
    const { dropzone, input, button } = buildDropzone();
    const { notify } = notices();
    createImagePicker({
      input,
      dropzone,
      isDisabled: () => false,
      onNotify: notify,
    });
    button.click();
    await tick();
    assert.equal(input.files.length, 2);
    assert.match(input.files[0].name, /\.png$/);
    assert.match(input.files[1].name, /\.jpe?g$/);
    assert.notEqual(input.files[0].name, input.files[1].name);
  }

  // A clipboard without an image reports it and stages nothing.
  setClipboardRead(async () => [
    {
      types: ["text/plain"],
      async getType() {
        return new Blob(["hello"], { type: "text/plain" });
      },
    },
  ]);
  {
    const { dropzone, input, button } = buildDropzone();
    const { messages, notify } = notices();
    createImagePicker({
      input,
      dropzone,
      isDisabled: () => false,
      onNotify: notify,
    });
    button.click();
    await tick();
    assert.equal(input.files.length, 0);
    assert.equal(messages[0], "No image was found in the clipboard.");
  }

  // A denied clipboard read reports the permission failure.
  setClipboardRead(async () => {
    const error = new Error("denied");
    error.name = "NotAllowedError";
    throw error;
  });
  {
    const { dropzone, input, button } = buildDropzone();
    const { messages, notify } = notices();
    createImagePicker({
      input,
      dropzone,
      isDisabled: () => false,
      onNotify: notify,
    });
    button.click();
    await tick();
    assert.equal(input.files.length, 0);
    assert.equal(messages[0], "Clipboard access was denied. Allow clipboard access and try again.");
  }

  console.log("clipboard paste checks passed");
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
