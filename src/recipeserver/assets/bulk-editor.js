// Bulk editor dialog for index.html (issue #36).
// Lets the user select several recipes on the index and apply shared
// (non-recipe-unique) front-matter changes to all of them in one save,
// or delete the whole selection. Talks to POST /api/bulk-edit.

const BULK_EDITOR_API = "/api/bulk-edit";
const BULK_EDIT_BUTTON_ID = "bulk-edit-open";

const state = {
  busy: false,
  selected: [], // [{path, title}] in selection order
  applyBoxes: new Map(), // field -> checkbox
  inputs: new Map(), // field -> input
};

let dialog = null;
let form = null;
let summaryLine = null;
let titleList = null;
let statusLine = null;
let saveButton = null;
let cancelButton = null;
let closeButton = null;
let deleteBox = null;

const LIST_FIELDS = [
  ["meals", "Meals", "ex. Breakfast, Dessert"],
  ["tags", "Tags", "ex. Chocolate, Sweet"],
  ["cuisine", "Cuisine", "ex. American"],
  ["categories", "Categories", "ex. Slow Cooker, Meat"],
];

const SCALAR_FIELDS = [
  ["contributor", "Contributor", "Andy Ford", "text"],
  ["createdOn", "Contribution date", "", "date"],
  ["author", "Source author", "First Last", "text"],
  ["makes", "Makes", "0", "number"],
  ["difficulty", "Difficulty", "5", "number"],
];

function element(tag, className, textContent) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textContent !== undefined) node.textContent = textContent;
  return node;
}

function setStatus(message) {
  statusLine.textContent = message || "";
}

function setBusy(busy) {
  state.busy = busy;
  saveButton.disabled = busy;
  cancelButton.disabled = busy;
  closeButton.disabled = busy;
  deleteBox.disabled = busy;
  for (const [field, box] of state.applyBoxes) {
    box.disabled = busy;
    const input = state.inputs.get(field);
    if (input) input.disabled = busy || !box.checked;
  }
  for (const input of state.inputs.values()) {
    input.disabled = busy || !state.applyBoxes.get(input.dataset.field)?.checked;
  }
}

function parseList(raw) {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildFields() {
  const container = document.createElement("div");
  container.className = "bulk-editor__fields";

  const addField = (field, label, placeholder, type, wide) => {
    const wrapper = element("div", `bulk-editor__field${wide ? " bulk-editor__field--wide" : ""}`);
    const labelEl = element("label");
    labelEl.append(element("span", null, label));
    const input = element("input");
    input.type = type;
    input.placeholder = placeholder || "";
    input.disabled = true;
    input.dataset.field = field;
    if (field === "makes") {
      input.step = "1";
      input.min = "0";
    }
    if (field === "difficulty") {
      input.step = "any";
      input.min = "0";
      input.max = "10";
    }
    if (field === "createdOn") {
      // Native date input; value stays YYYY-MM-DD.
    }
    labelEl.append(input);

    const applyWrap = element("label", "bulk-editor__apply");
    const applyBox = element("input");
    applyBox.type = "checkbox";
    applyBox.dataset.field = field;
    applyWrap.append(applyBox, element("span", null, "Apply to selected recipes"));
    applyBox.addEventListener("change", () => {
      input.disabled = !applyBox.checked;
      wrapper.classList.toggle("bulk-editor__field--disabled", !applyBox.checked);
      setStatus("");
    });
    wrapper.classList.add("bulk-editor__field--disabled");
    wrapper.append(labelEl, applyWrap);
    container.append(wrapper);
    state.applyBoxes.set(field, applyBox);
    state.inputs.set(field, input);
  };

  for (const [field, label, placeholder] of LIST_FIELDS) {
    addField(field, label, placeholder, "text", true);
  }
  for (const [field, label, placeholder, type] of SCALAR_FIELDS) {
    addField(field, label, placeholder, type, false);
  }

  // Rating upsert: reviewer name + score 0-10.
  const ratingName = element("input");
  ratingName.type = "text";
  ratingName.placeholder = "Reviewer name";
  ratingName.maxLength = 100;
  ratingName.disabled = true;
  ratingName.dataset.field = "ratingName";
  const ratingScore = element("input");
  ratingScore.type = "text";
  ratingScore.inputMode = "decimal";
  ratingScore.placeholder = "0 to 10";
  ratingScore.disabled = true;
  ratingScore.dataset.field = "ratingScore";

  const ratingWrapper = element("div", "bulk-editor__field bulk-editor__field--wide");
  const ratingLabel = element("label");
  ratingLabel.append(element("span", null, "Rating (add or update for this reviewer)"));
  ratingLabel.append(ratingName, ratingScore);
  const ratingApplyWrap = element("label", "bulk-editor__apply");
  const ratingApply = element("input");
  ratingApply.type = "checkbox";
  ratingApply.dataset.field = "rating";
  ratingApplyWrap.append(ratingApply, element("span", null, "Apply to selected recipes"));
  ratingApply.addEventListener("change", () => {
    ratingName.disabled = !ratingApply.checked;
    ratingScore.disabled = !ratingApply.checked;
    ratingWrapper.classList.toggle("bulk-editor__field--disabled", !ratingApply.checked);
  });
  ratingWrapper.classList.add("bulk-editor__field--disabled");
  ratingWrapper.append(ratingLabel, ratingApplyWrap);
  container.append(ratingWrapper);
  state.applyBoxes.set("rating", ratingApply);
  state.inputs.set("ratingName", ratingName);
  state.inputs.set("ratingScore", ratingScore);

  return container;
}

function closeEditor() {
  if (!state.busy && dialog.open) dialog.close();
}

function openEditor() {
  if (state.busy || state.selected.length === 0) return;
  summaryLine.textContent =
    state.selected.length === 1
      ? `Editing 1 recipe: ${state.selected[0].title}`
      : `Editing ${state.selected.length} recipes`;

  titleList.textContent = "";
  const MAX_TITLES = 12;
  const shown = state.selected.slice(0, MAX_TITLES);
  for (const { title } of shown) {
    titleList.append(element("li", null, title));
  }
  if (state.selected.length > MAX_TITLES) {
    titleList.append(element("li", "more", `+ ${state.selected.length - MAX_TITLES} more`));
  }

  setStatus("");
  dialog.showModal();
}

function collectUpdates() {
  const updates = {};
  for (const [field] of LIST_FIELDS) {
    if (!state.applyBoxes.get(field)?.checked) continue;
    updates[field] = parseList(state.inputs.get(field).value);
  }
  for (const [field] of SCALAR_FIELDS) {
    if (!state.applyBoxes.get(field)?.checked) continue;
    const raw = state.inputs.get(field).value.trim();
    if (!raw) {
      updates[field] = null;
      continue;
    }
    if (field === "makes" || field === "difficulty") {
      const number = Number(raw);
      if (!Number.isFinite(number) || (field === "makes" && !Number.isInteger(number))) {
        throw new Error(
          `${field} must be a valid ${field === "makes" ? "integer" : "number"}, or left blank.`,
        );
      }
      updates[field] = number;
    } else {
      updates[field] = raw;
    }
  }

  let rating = null;
  if (state.applyBoxes.get("rating")?.checked) {
    const name = state.inputs.get("ratingName").value.trim();
    const rawScore = state.inputs.get("ratingScore").value.trim();
    const score = Number(rawScore);
    if (!name || !Number.isFinite(score) || score < 0 || score > 10) {
      throw new Error("Enter a reviewer name and a rating from 0 to 10.");
    }
    rating = { name, rating: score };
  }

  return { updates, rating };
}

async function saveEditor(event) {
  event.preventDefault();
  if (state.busy) return;

  const { updates, rating } = (() => {
    try {
      return collectUpdates();
    } catch (error) {
      setStatus(error.message);
      return null;
    }
  })();
  if (!updates) return;

  if (!deleteBox.checked && Object.keys(updates).length === 0 && rating === null) {
    setStatus("Tick “Apply to selected recipes” on at least one field, or choose Delete.");
    return;
  }

  if (deleteBox.checked) {
    const titles = state.selected.map((item) => `- ${item.title}`).join("\n");
    const confirmed = window.confirm(
      `Delete ${state.selected.length} selected recipe(s)? This cannot be undone.\n\n${titles}`,
    );
    if (!confirmed) return;
    if (!window.confirm("Are you sure? This is permanent.")) return;
  }

  setBusy(true);
  setStatus(deleteBox.checked ? "Deleting recipes…" : "Saving selected recipes…");

  try {
    const response = await fetch(BULK_EDITOR_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paths: state.selected.map((item) => item.path),
        updates,
        rating,
        delete: deleteBox.checked,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Unable to save selected recipes.");

    window.location.reload();
  } catch (error) {
    setStatus(error.message || "Unable to save selected recipes.");
    setBusy(false);
  }
}

function createEditorDialog() {
  dialog = element("dialog", "bulk-editor-dialog");
  dialog.id = "bulk-editor";

  form = element("form", "bulk-editor");
  form.method = "dialog";

  const header = element("header", "bulk-editor__header");
  header.append(element("h2", null, "Bulk Edit"));
  closeButton = element("button", "bulk-editor__close", "\u00d7");
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Close bulk editor");
  closeButton.addEventListener("click", closeEditor);
  header.append(closeButton);

  summaryLine = element("p", "bulk-editor__summary");
  summaryLine.setAttribute("role", "status");
  titleList = element("ul", "bulk-editor__list");
  const hint = element(
    "p",
    "bulk-editor__hint",
    "Only ticked fields are changed. Blank means “clear this field” on the selected recipes. Ratings add or update one reviewer on each selected recipe.",
  );

  const fields = buildFields();

  const deleteWrap = element("div", "bulk-editor__delete");
  const deleteLabel = element("label");
  deleteBox = element("input");
  deleteBox.type = "checkbox";
  deleteLabel.append(deleteBox, element("span", null, "Delete selected recipes"));
  const deleteHelp = element(
    "p",
    null,
    "Deletes every selected recipe file. This cannot be undone — you will be asked to confirm twice.",
  );
  deleteWrap.append(deleteLabel, deleteHelp);

  statusLine = element("p", "bulk-editor__status");
  statusLine.setAttribute("role", "status");

  const footer = element("footer", "bulk-editor__footer");
  cancelButton = element("button", "bulk-editor__cancel", "Cancel");
  cancelButton.type = "button";
  cancelButton.addEventListener("click", closeEditor);
  saveButton = element("button", "bulk-editor__save", "Save all");
  saveButton.type = "submit";
  footer.append(cancelButton, saveButton);

  form.append(header, summaryLine, titleList, hint, fields, deleteWrap, statusLine, footer);
  form.addEventListener("submit", saveEditor);

  dialog.append(form);
  document.body.append(dialog);

  dialog.addEventListener("cancel", (event) => {
    if (state.busy) event.preventDefault();
  });

  let pointerDownTarget = null;
  dialog.addEventListener("pointerdown", (event) => {
    pointerDownTarget = event.target;
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && pointerDownTarget === dialog) {
      closeEditor();
    }
    pointerDownTarget = null;
  });
}

function readSelection() {
  const checked = document.querySelectorAll("#recipe-list .recipe-select__input:checked");
  state.selected = [...checked]
    .map((box) => {
      const recipe = box.closest(".recipe");
      return {
        path: recipe?.dataset.path || "",
        title: recipe?.dataset.title || box.dataset.title || "Recipe",
      };
    })
    .filter((item) => item.path);
}

function initialize() {
  const hook = document.getElementById(BULK_EDIT_BUTTON_ID);
  if (!hook || document.getElementById("bulk-editor")) return;

  createEditorDialog();
  hook.addEventListener("click", () => {
    readSelection();
    if (state.selected.length === 0) {
      hook.focus();
      return;
    }
    openEditor();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize);
} else {
  initialize();
}
