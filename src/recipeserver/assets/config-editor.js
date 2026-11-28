// Configuration editor dialog. Inspired by the recipe editor: a native
// <dialog> built in JS, Save/Cancel footer, busy-state disabling, and
// server-returned validation errors surfaced on a status line. Fields are
// rendered from the server's field specs (GET /api/config), so new
// configuration keys appear here without client changes.

const CONFIG_EDITOR_API = "/api/config";
const TRANSCRIPTION_TEST_API = "/api/config/test-transcription";
const CONFIG_EDITOR_HOOK = "[data-config]";

// The keep-alive fields that pair with a probed model field. The Configuration
// dialog disables the keep-alive field (and explains why) when the paired
// model cannot be kept loaded — e.g. it is not installed on the server, the
// server could not be reached, or the model reports no size.
const KEEP_ALIVE_SOURCES = {
  all_purpose_model_keep_alive: "all_purpose_model_name",
  image_analysis_model_keep_alive: "image_analysis_model",
  transcription_keep_alive: "transcription_model",
};

const state = {
  busy: false,
  original: {},
  inputs: new Map(),
  probedDisabled: new Set(),
};

let dialog = null;
let form = null;
let fieldsContainer = null;
let statusLine = null;
let saveButton = null;
let cancelButton = null;
let closeButton = null;
let testButton = null;
let testing = false;

function element(tag, className, textContent) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textContent !== undefined) node.textContent = textContent;
  return node;
}

function setBusy(busy) {
  state.busy = busy;
  for (const [key, input] of state.inputs.entries())
    input.disabled = busy || state.probedDisabled.has(key);
  saveButton.disabled = busy;
  cancelButton.disabled = busy;
  closeButton.disabled = busy;
  testButton.disabled = busy || testing;
}

function setStatus(message, { ok = false } = {}) {
  statusLine.textContent = message || "";
  statusLine.classList.toggle("config-editor__status--ok", ok && Boolean(message));
}

// The serialised value of a field: checkboxes are "true"/"false",
// everything else is the input's text value.
function fieldValue(input) {
  return input.type === "checkbox" ? (input.checked ? "true" : "false") : input.value;
}

function refreshChanged() {
  for (const [key, input] of state.inputs) {
    const field = input.closest(".config-editor__field");
    const changed = fieldValue(input) !== (state.original[key] ?? "");
    if (field) field.classList.toggle("is-changed", changed);
  }
}

// One caption describing the probed model: its on-disk size plus the
// interesting details, or the probe's failure message.
function modelCaptionText(info, configuredName) {
  if (!info || (!info.present && info.error)) return info?.error || "";
  const parts = [];
  if (info.size_gb != null) parts.push(`${info.size_gb} GB on disk`);
  if (info.parameter_size) parts.push(String(info.parameter_size));
  if (info.quantization_level) parts.push(String(info.quantization_level));
  if (info.runner) parts.push(String(info.runner));
  if (!configuredName && info.resolved_model) parts.push(`auto-detected: ${info.resolved_model}`);
  return parts.join(" · ") || info.error || "";
}

function buildFields(fields, values, models = {}) {
  fieldsContainer.textContent = "";
  state.inputs.clear();
  state.probedDisabled.clear();

  for (const field of fields) {
    const wrapper = element("div", "config-editor__field");
    const label = element("label");
    const inputId = `config-editor-${field.key}`;
    label.htmlFor = inputId;

    let input;
    if (field.input_type === "select") {
      // Selects render their options from the server's field spec.
      input = element("select", "field-input");
      input.id = inputId;
      input.name = field.key;
      for (const option of field.options || []) {
        const optionElement = element("option", null, option.label);
        optionElement.value = option.value;
        input.append(optionElement);
      }
      input.value = values[field.key] ?? "";
      label.append(element("span", null, field.label));
      if (field.required) {
        label.append(element("span", "config-editor__required", "required"));
      }
    } else {
      input = element("input", "field-input");
      input.id = inputId;
      input.name = field.key;
      input.spellcheck = false;

      if (field.input_type === "checkbox") {
        // Checkboxes render inside the label so clicking the text toggles them.
        wrapper.classList.add("config-editor__field--checkbox");
        label.classList.add("config-editor__checkbox-label");
        input.type = "checkbox";
        input.className = "config-editor__checkbox";
        input.checked = values[field.key] === "true";
        label.append(input, element("span", null, field.label));
      } else {
        label.append(element("span", null, field.label));
        if (field.required) {
          label.append(element("span", "config-editor__required", "required"));
        }

        if (field.placeholder) input.placeholder = field.placeholder;
        // Browser-level validation for URL and number fields; the server
        // validates strictly and reports the real rules in the help text.
        input.type =
          field.input_type === "url" ? "url" : field.input_type === "number" ? "number" : "text";
        if (input.type === "number") {
          if (field.min !== undefined) input.min = String(field.min);
          if (field.max !== undefined) input.max = String(field.max);
          input.step = "1";
          input.inputMode = "numeric";
        }
        if (field.required) input.required = true;
        input.value = values[field.key] ?? "";
      }
    }

    input.addEventListener("input", () => {
      refreshChanged();
      setStatus("");
    });
    input.addEventListener("change", () => {
      refreshChanged();
      setStatus("");
    });

    const help = element("p", "config-editor__help", field.help || "");
    const captions = [];

    const info = models[field.key];
    if (info) {
      const text = modelCaptionText(info, values[field.key]);
      if (text) {
        const className = info.error
          ? "config-editor__model-info config-editor__model-info--warning"
          : "config-editor__model-info";
        captions.push(element("p", className, text));
      }
    }

    const keepAliveSource = KEEP_ALIVE_SOURCES[field.key];
    if (keepAliveSource) {
      const sourceInfo = models[keepAliveSource];
      if (sourceInfo && !sourceInfo.can_keep_alive) {
        state.probedDisabled.add(field.key);
        input.disabled = true;
        captions.push(
          element(
            "p",
            "config-editor__model-info config-editor__model-info--warning",
            `Keep-alive unavailable: ${sourceInfo.error || "the model cannot be kept loaded"}`,
          ),
        );
      }
    }

    if (field.input_type === "checkbox") {
      wrapper.append(label, help, ...captions);
    } else {
      wrapper.append(label, input, help, ...captions);
    }
    fieldsContainer.append(wrapper);
    state.inputs.set(field.key, input);
  }

  state.original = { ...values };
  refreshChanged();
}

function closeEditor() {
  if (dialog.open) dialog.close();
}

// Send the bundled speech sample through the configured transcription
// server/model and report the transcript. Tests the field values as they
// are in the dialog, so an unsaved change can be verified before saving.
async function testTranscription() {
  if (state.busy || testing) return;

  const values = {};
  for (const key of ["transcription_endpoint", "transcription_model", "transcription_keep_alive"]) {
    const input = state.inputs.get(key);
    if (input) values[key] = fieldValue(input);
  }

  testing = true;
  testButton.disabled = true;
  setStatus("Testing the transcription model…");

  try {
    const data = await window.RecipeApi.requestJson(TRANSCRIPTION_TEST_API, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(values),
      fallbackMessage: "The transcription test failed.",
    });

    const seconds = typeof data.seconds === "number" ? `${data.seconds}s — ` : "";
    const text = String(data.text || "").trim();
    setStatus(
      `Test passed (${seconds}${text ? `“${truncate(text, 120)}”` : "empty transcription"})`,
      { ok: true },
    );
  } catch (error) {
    setStatus(error.message || "The transcription test failed.");
  } finally {
    testing = false;
    testButton.disabled = state.busy;
  }
}

function truncate(text, max) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

async function openEditor() {
  if (state.busy) return;
  setBusy(true);
  setStatus("");

  try {
    const data = await window.RecipeApi.requestJson(CONFIG_EDITOR_API, {
      headers: { Accept: "application/json" },
      fallbackMessage: "Unable to load configuration.",
    });

    buildFields(data.fields || [], data.values || {}, data.models || {});
    dialog.showModal();
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
}

async function saveEditor(event) {
  event.preventDefault();
  if (state.busy) return;

  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }

  const values = {};
  for (const [key, input] of state.inputs) values[key] = fieldValue(input);

  setBusy(true);
  setStatus("");

  try {
    await window.RecipeApi.requestJson(CONFIG_EDITOR_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
      fallbackMessage: "Unable to save configuration.",
    });

    // The server regenerates the site on save; reload to show it.
    window.location.reload();
  } catch (error) {
    setStatus(error.message);
    setBusy(false);
  }
}

function closeSandwichMenu(menu) {
  const panel = menu ? menu.querySelector(".sandwich-menu__panel") : null;
  const toggle = menu ? menu.querySelector(".sandwich-menu__toggle") : null;
  if (panel) panel.hidden = true;
  if (toggle) toggle.setAttribute("aria-expanded", "false");
}

function createEditorDialog() {
  dialog = element("dialog", "config-editor-dialog");
  dialog.id = "config-editor";

  form = element("form", "config-editor");
  form.method = "dialog";
  form.setAttribute("novalidate", "false");

  const header = element("header", "config-editor__header");
  header.append(element("h2", null, "Configuration"));
  closeButton = element("button", "config-editor__close", "\u00d7");
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close configuration editor");
  closeButton.addEventListener("click", closeEditor);
  header.append(closeButton);

  fieldsContainer = element("div", "config-editor__fields");

  statusLine = element("p", "config-editor__status");
  statusLine.setAttribute("role", "status");

  const footer = element("footer", "config-editor__footer");
  testButton = element("button", "config-editor__test", "Test transcription");
  testButton.type = "button";
  testButton.setAttribute(
    "aria-label",
    "Send a test recording to the configured transcription server",
  );
  testButton.addEventListener("click", () => {
    void testTranscription();
  });
  cancelButton = element("button", "config-editor__cancel", "Cancel");
  cancelButton.type = "button";
  cancelButton.addEventListener("click", closeEditor);
  saveButton = element("button", "config-editor__save", "Save");
  saveButton.type = "submit";
  footer.append(testButton, cancelButton, saveButton);

  form.append(header, fieldsContainer, statusLine, footer);
  form.addEventListener("submit", saveEditor);

  dialog.append(form);
  document.body.append(dialog);

  // Let Escape work while busy only by blocking the close; the dialog
  // cancel event keeps the dialog open until saving finishes.
  dialog.addEventListener("cancel", (event) => {
    if (state.busy) event.preventDefault();
  });
  // Click outside the dialog (a full press on the backdrop) closes it.
  window.RecipeDialogs.installClickOutsideClose(dialog, closeEditor);
}

function initialize() {
  const hook = document.querySelector(CONFIG_EDITOR_HOOK);
  if (!hook || document.getElementById("config-editor")) return;

  createEditorDialog();
  hook.addEventListener("click", () => {
    closeSandwichMenu(hook.closest(".sandwich-menu"));
    void openEditor();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize);
} else {
  initialize();
}
