// Configuration editor dialog. Inspired by the recipe editor: a native
// <dialog> built in JS, Save/Cancel footer, busy-state disabling, and
// server-returned validation errors surfaced on a status line. Fields are
// rendered from the server's field specs (GET /api/config), so new
// configuration keys appear here without client changes.

const CONFIG_EDITOR_API = "/api/config";
const CONFIG_EDITOR_HOOK = "[data-config]";

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
}

function setStatus(message) {
  statusLine.textContent = message || "";
}

function refreshChanged() {
  for (const [key, input] of state.inputs) {
    const field = input.closest(".config-editor__field");
    const changed = input.value !== (state.original[key] ?? "");
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
    label.append(element("span", null, field.label));
    if (field.required) {
      label.append(element("span", "config-editor__required", "required"));
    }

    const input = element("input");
    input.id = inputId;
    input.name = field.key;
    input.spellcheck = false;
    if (field.placeholder) input.placeholder = field.placeholder;
    // Browser-level validation for URL fields; the server validates
    // strictly and reports the real rules in the help text.
    input.type = field.input_type === "url" ? "url" : "text";
    if (field.required) input.required = true;
    input.value = values[field.key] ?? "";
    input.addEventListener("input", () => {
      refreshChanged();
      setStatus("");
    });

    const help = element("p", "config-editor__help", field.help || "");
    wrapper.append(label, input, help);
    fieldsContainer.append(wrapper);
    state.inputs.set(field.key, input);
  }

  state.original = { ...values };
  refreshChanged();
}

function closeEditor() {
  if (dialog.open) dialog.close();
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
  for (const [key, input] of state.inputs) values[key] = input.value;

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
  cancelButton = element("button", "config-editor__cancel", "Cancel");
  cancelButton.type = "button";
  cancelButton.addEventListener("click", closeEditor);
  saveButton = element("button", "config-editor__save", "Save");
  saveButton.type = "submit";
  footer.append(cancelButton, saveButton);

  form.append(header, fieldsContainer, statusLine, footer);
  form.addEventListener("submit", saveEditor);

  dialog.append(form);
  document.body.append(dialog);

  // Let Escape work while busy only by blocking the close; the dialog
  // cancel event keeps the dialog open until saving finishes.
  dialog.addEventListener("cancel", (event) => {
    if (state.busy) event.preventDefault();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeEditor();
  });
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
