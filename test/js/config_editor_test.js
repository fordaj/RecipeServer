"use strict";

// Behavioural checks for the Configuration dialog's select fields (the
// timeline_retention dropdown). The dialog builds its DOM from the server's
// field specs; this verifies that a select field renders its options, tracks
// changes, and is posted back to /api/config on save.

const assert = require("node:assert/strict");
const path = require("node:path");

const { Element, createDocument } = require("./dom_stub.js");

const CONFIG_EDITOR_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "config-editor.js",
);

const GET_PAYLOAD = {
  values: {
    recipe_server_name: "Test Kitchen",
    source_directory: "/tmp/recipes",
    model_endpoint: "",
    all_purpose_model_name: "",
    image_analysis_model: "",
    server_port: "8000",
    food_color: "#8d5542",
    dictation_enabled: "true",
    timeline_retention: "gfs",
  },
  fields: [
    {
      key: "timeline_retention",
      label: "Timeline retention",
      help: "GFS automatically removes older, redundant revisions.",
      input_type: "select",
      placeholder: "",
      required: false,
      options: [
        { value: "gfs", label: "GFS (recommended)" },
        { value: "unlimited", label: "Unlimited" },
      ],
    },
    {
      key: "dictation_enabled",
      label: "Dictation",
      help: "Enable dictation.",
      input_type: "checkbox",
      placeholder: "",
      required: false,
    },
  ],
};

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function collectElements(root) {
  const found = [];
  for (const child of root.childNodes) {
    found.push(child);
    found.push(...collectElements(child));
  }
  return found;
}

async function main() {
  const document = createDocument();
  document.getElementById = (id) =>
    collectElements(document.documentElement).find(
      (node) => node.getAttribute && node.getAttribute("id") === id,
    ) ?? null;
  const hook = document.createElement("button");
  hook.setAttribute("data-config", "");
  document.body.append(hook);

  Element.prototype.showModal = function showModal() {
    this.open = true;
  };
  Element.prototype.close = function close() {
    this.open = false;
  };
  Element.prototype.checkValidity = function checkValidity() {
    return true;
  };
  Element.prototype.reportValidity = function reportValidity() {
    return true;
  };

  let savedBody = null;
  let reloaded = false;
  globalThis.window = {
    RecipeDialogs: { installClickOutsideClose: () => {} },
    location: {
      reload() {
        reloaded = true;
      },
    },
  };
  globalThis.document = document;
  globalThis.fetch = async (_url, options) => {
    if (!options || !options.method) {
      return { ok: true, json: async () => GET_PAYLOAD };
    }
    savedBody = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({
        success: true,
        values: savedBody.values,
        changed: ["timeline_retention"],
      }),
    };
  };

  require(CONFIG_EDITOR_JS);

  // Clicking the Configuration entry opens (and populates) the dialog.
  hook.click();
  await flush();
  await flush();

  const byId = (id) => collectElements(document.documentElement).find((node) => node.id === id);
  const select = byId("config-editor-timeline_retention");
  assert.ok(select, "select field is rendered");
  assert.equal(select.tagName, "SELECT");
  assert.equal(select.value, "gfs");
  assert.deepEqual(
    select.childNodes.map((option) => [option.value, option.textContent]),
    [
      ["gfs", "GFS (recommended)"],
      ["unlimited", "Unlimited"],
    ],
  );

  // The checkbox field renders as a checkbox next to its label.
  const checkbox = byId("config-editor-dictation_enabled");
  assert.ok(checkbox, "checkbox field is rendered");
  assert.equal(checkbox.type, "checkbox");

  // Changing the select marks the field as changed and is posted on save.
  select.value = "unlimited";
  select.dispatchEvent({ type: "change", target: select });
  const wrapper = select.closest(".config-editor__field");
  assert.ok(wrapper.classList.contains("is-changed"), "changed select is flagged");

  const form = document.querySelector(".config-editor");
  form.dispatchEvent({ type: "submit", target: form, preventDefault() {} });
  await flush();
  await flush();

  assert.ok(savedBody, "save posts to /api/config");
  assert.equal(savedBody.values.timeline_retention, "unlimited");
  assert.ok(reloaded, "page reloads after a successful save");

  console.log("config editor checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
