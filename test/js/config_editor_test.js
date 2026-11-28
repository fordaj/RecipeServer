"use strict";

// Behavioural checks for the Configuration dialog (the select field, the
// transcription fields, and the Test transcription button). The dialog builds
// its DOM from the server's field specs; this verifies that a select field
// renders its options, tracks changes, posts current values through the
// test endpoint, and is posted back to /api/config on save.

const assert = require("node:assert/strict");
const path = require("node:path");

const { Element, createDocument } = require("./dom_stub.js");
const API_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "api.js");

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
    transcription_endpoint: "http://localhost:11434",
    transcription_model: "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
    transcription_keep_alive: "0",
    all_purpose_model_keep_alive: "0",
    image_analysis_model_keep_alive: "0",
    timeline_retention: "gfs",
  },
  models: {
    all_purpose_model_name: {
      resolved_model: "",
      configured_name: "",
      present: false,
      size_bytes: null,
      size_gb: null,
      parameter_size: "",
      quantization_level: "",
      runner: "",
      capabilities: [],
      can_keep_alive: false,
      error: "endpoint not configured",
    },
    image_analysis_model: {
      resolved_model: "",
      configured_name: "",
      present: false,
      size_bytes: null,
      size_gb: null,
      parameter_size: "",
      quantization_level: "",
      runner: "",
      capabilities: [],
      can_keep_alive: false,
      error: "endpoint not configured",
    },
    transcription_model: {
      resolved_model: "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
      configured_name: "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
      present: true,
      size_bytes: 1019142577,
      size_gb: 1.0,
      parameter_size: "752M",
      quantization_level: "Q8_0",
      runner: "ggml",
      capabilities: ["completion", "audio"],
      can_keep_alive: true,
      error: null,
    },
  },
  fields: [
    {
      key: "transcription_endpoint",
      label: "Transcription server",
      help: "Ollama server used for dictation.",
      input_type: "url",
      placeholder: "http://localhost:11434",
      required: false,
    },
    {
      key: "transcription_model",
      label: "Transcription model",
      help: "The Ollama model used for dictation.",
      input_type: "text",
      placeholder: "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
      required: false,
    },
    {
      key: "all_purpose_model_keep_alive",
      label: "All-purpose model keep-alive",
      help: "Minutes before unload. -1 never, 0 immediately, N after N minutes.",
      input_type: "number",
      placeholder: "0",
      required: false,
      min: -1,
    },
    {
      key: "image_analysis_model_keep_alive",
      label: "Image analysis model keep-alive",
      help: "Minutes before unload. -1 never, 0 immediately, N after N minutes.",
      input_type: "number",
      placeholder: "0",
      required: false,
      min: -1,
    },
    {
      key: "transcription_keep_alive",
      label: "Transcription keep-alive",
      help: "Minutes before unload. -1 never, 0 immediately, N after N minutes.",
      input_type: "number",
      placeholder: "0",
      required: false,
      min: -1,
    },
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
  const testRequests = [];
  globalThis.window = {
    RecipeDialogs: { installClickOutsideClose: () => {} },
    location: {
      reload() {
        reloaded = true;
      },
    },
  };
  globalThis.document = document;
  globalThis.fetch = async (url, options) => {
    if (!options || !options.method) {
      return { ok: true, json: async () => GET_PAYLOAD };
    }
    if (url === "/api/config/test-transcription") {
      testRequests.push(JSON.parse(options.body));
      return {
        ok: true,
        json: async () => ({
          ok: true,
          text: "Add two cups of flour and one cup of sugar.",
          seconds: 0.4,
        }),
      };
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

  require(API_JS);
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

  // The Test transcription button posts the current field values and shows
  // the server's result in the status line.
  const testButton = collectElements(document.documentElement).find(
    (node) => node.classList && node.classList.contains("config-editor__test"),
  );
  assert.ok(testButton, "test transcription button is rendered");
  testButton.click();
  await flush();
  await flush();
  assert.equal(testRequests.length, 1, "test button posts to /api/config/test-transcription");
  assert.equal(testRequests[0].transcription_endpoint, "http://localhost:11434");
  assert.equal(testRequests[0].transcription_model, "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0");
  const status = collectElements(document.documentElement).find(
    (node) => node.classList && node.classList.contains("config-editor__status"),
  );
  assert.match(status.textContent, /Test passed/);
  assert.match(status.textContent, /two cups of flour/);

  // The probed model is captioned with its size, and the keep-alive field
  // for a model that cannot be kept loaded is disabled with an explanation.
  const captions = collectElements(document.documentElement).filter(
    (node) => node.classList && node.classList.contains("config-editor__model-info"),
  );
  const captionText = captions.map((node) => node.textContent).join(" | ");
  assert.match(captionText, /1 GB on disk/);
  assert.match(captionText, /Q8_0/);
  assert.match(captionText, /Keep-alive unavailable: endpoint not configured/);

  const transcriptionKeepAlive = byId("config-editor-transcription_keep_alive");
  assert.ok(transcriptionKeepAlive, "transcription keep-alive field is rendered");
  assert.equal(
    transcriptionKeepAlive.disabled,
    false,
    "keep-alive stays enabled for a resident model",
  );
  assert.equal(transcriptionKeepAlive.min, "-1");

  const allPurposeKeepAlive = byId("config-editor-all_purpose_model_keep_alive");
  assert.ok(allPurposeKeepAlive, "all-purpose keep-alive field is rendered");
  assert.equal(
    allPurposeKeepAlive.disabled,
    true,
    "keep-alive is disabled for an unverifiable model",
  );
  assert.equal(allPurposeKeepAlive.min, "-1");

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
