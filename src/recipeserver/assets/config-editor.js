// Configuration editor dialog. Inspired by the recipe editor: a native
// <dialog> built in JS, Save/Cancel footer, busy-state disabling, and
// server-returned validation errors surfaced on a status line. Fields are
// rendered from the server's field specs (GET /api/config), so new
// configuration keys appear here without client changes.

const CONFIG_EDITOR_API = "/api/config";
const TRANSCRIPTION_TEST_API = "/api/config/test-transcription";
const CONFIG_EDITOR_HOOK = "[data-config]";
// TCP port ceiling, mirroring MAX_PORT on the server.
const MAX_SERVER_PORT = 65535;

const state = {
  busy: false,
  original: {},
  inputs: new Map(),
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
  for (const input of state.inputs.values()) input.disabled = busy;
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

function buildFields(fields, values) {
  fieldsContainer.textContent = "";
  state.inputs.clear();

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
          input.min = "1";
          input.max = String(MAX_SERVER_PORT);
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
    if (field.input_type === "checkbox") {
      wrapper.append(label, help);
    } else {
      wrapper.append(label, input, help);
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
    const response = await fetch(TRANSCRIPTION_TEST_API, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(values),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The transcription test failed.");

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
    const response = await fetch(CONFIG_EDITOR_API, { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to load configuration.");

    buildFields(data.fields || [], data.values || {});
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
    const response = await fetch(CONFIG_EDITOR_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to save configuration.");

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
