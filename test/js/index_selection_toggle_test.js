"use strict";

// Behavioural checks for the Select/Cancel button in the index bulk
// controls bar. The index script is loaded into the DOM stub from
// dom_stub.js so the button can be driven the way a browser would
// drive it.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const INDEX_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "index.js");

const FILTER_IDS = [
  "filter-meal",
  "filter-cuisine",
  "filter-status",
  "filter-category",
  "filter-tag",
  "filter-contributor",
  "filter-source-title",
];

function element(document, tagName, attributes = {}) {
  const node = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

// Builds the part of the index page the bulk controls bar lives in.
function buildPage(document) {
  const search = element(document, "input", { id: "recipe-search" });
  const sort = element(document, "select", { id: "sort-recipes" });
  sort.value = "title:asc";
  const count = element(document, "p", { id: "recipe-count" });
  const clearFilters = element(document, "button", { id: "clear-filters" });
  const metadataStatus = element(document, "input", { id: "metadata-status" });
  const filters = FILTER_IDS.map((id) => {
    const select = element(document, "select", { id });
    select.value = "";
    return select;
  });

  const selectAllLabel = element(document, "label", {
    class: "select-all-control",
    "data-selection-only": "",
  });
  selectAllLabel.hidden = true;
  const selectAll = element(document, "input", { type: "checkbox", id: "select-all" });
  selectAllLabel.append(selectAll);

  const clearSelections = element(document, "button", {
    id: "clear-selections",
    "data-selection-only": "",
  });
  clearSelections.hidden = true;
  const bulkDelete = element(document, "button", {
    id: "bulk-delete",
    "data-selection-only": "",
  });
  bulkDelete.hidden = true;
  const shoppingList = element(document, "button", {
    id: "shopping-list",
    "data-selection-only": "",
  });
  shoppingList.hidden = true;
  const bulkEdit = element(document, "button", { id: "bulk-edit", "data-selection-only": "" });
  bulkEdit.hidden = true;

  const bulkCount = element(document, "span", {
    id: "bulk-selection-count",
    "data-selection-only": "",
  });
  bulkCount.hidden = true;
  bulkCount.textContent = "0 selected";

  const toggleLabel = element(document, "span", { "data-selection-label": "" });
  toggleLabel.textContent = "Select";
  const selectionToggle = element(document, "button", { id: "bulk-selection-toggle" });
  selectionToggle.append(toggleLabel);

  // The count and the button sit together at the far right of the bar.
  const status = element(document, "span", { class: "bulk-controls__status" });
  status.append(bulkCount, selectionToggle);

  const bulkControls = element(document, "div", { id: "bulk-controls", class: "bulk-controls" });
  bulkControls.append(selectAllLabel, clearSelections, bulkDelete, shoppingList, bulkEdit, status);

  const list = element(document, "ul", { id: "recipe-list" });
  const recipes = [];
  for (const title of ["Soup", "Stew"]) {
    const slug = title.toLowerCase();
    const recipe = element(document, "li", { class: "recipe", "data-path": `${slug}/recipe.md` });
    recipe.setAttribute("data-title", title);
    recipe.setAttribute("data-search", slug);
    recipe.setAttribute("data-ratings", "[]");
    recipe.setAttribute("data-archived", "false");

    const selectLabel = element(document, "label", { class: "recipe-select" });
    selectLabel.hidden = true;
    const box = element(document, "input", { type: "checkbox", class: "recipe-select__checkbox" });
    box.setAttribute("data-path", `${slug}/recipe.md`);
    selectLabel.append(box);
    recipe.append(selectLabel);

    list.append(recipe);
    recipes.push({ recipe, box, selectLabel });
  }

  document.body.append(
    search,
    sort,
    count,
    clearFilters,
    metadataStatus,
    ...filters,
    bulkControls,
    list,
  );

  return {
    list,
    bulkControls,
    bulkCount,
    bulkEdit,
    selectAll,
    selectAllLabel,
    selectionToggle,
    toggleLabel,
    status,
    recipes,
  };
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

// The browser toggles the checkbox before the click handler runs.
function toggleBox(box) {
  box.checked = !box.checked;
  box.click();
}

async function main() {
  const document = createDocument();
  const page = buildPage(document);

  globalThis.window = { location: { pathname: "/", origin: "http://localhost" } };
  globalThis.document = document;
  globalThis.fetch = async () => ({ ok: false });
  const store = new Map();
  globalThis.localStorage = {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
  };

  require(INDEX_JS);
  document.dispatchEvent({ type: "DOMContentLoaded" });
  await tick();

  // The bar always offers the button, and the bulk actions stay hidden
  // until selection mode is on.
  assert.equal(page.toggleLabel.textContent, "Select");
  assert.equal(page.bulkControls.hidden, false);
  assert.equal(page.bulkCount.hidden, true);
  assert.equal(page.bulkEdit.hidden, true);
  assert.equal(page.selectAllLabel.hidden, true);
  assert.equal(page.list.classList.contains("selection-mode"), false);

  // The count belongs to the left of the button.
  assert.equal(page.bulkCount.parentNode, page.selectionToggle.parentNode);
  assert.ok(
    page.status.childNodes.indexOf(page.bulkCount) <
      page.status.childNodes.indexOf(page.selectionToggle),
    "the selection count comes before the Select button",
  );

  // Clicking the button turns selection mode on and renames it Cancel.
  page.selectionToggle.click();
  assert.equal(page.toggleLabel.textContent, "Cancel");
  assert.equal(page.list.classList.contains("selection-mode"), true);
  assert.equal(page.bulkControls.classList.contains("is-selection-mode"), true);
  assert.equal(page.bulkCount.hidden, false);
  assert.equal(page.bulkEdit.hidden, false);
  assert.equal(page.selectAllLabel.hidden, false);
  assert.equal(page.recipes[0].selectLabel.hidden, false);

  // Selecting a recipe updates the count next to the Cancel button.
  toggleBox(page.recipes[0].box);
  assert.equal(page.bulkCount.textContent, "1 selected");
  assert.equal(page.bulkEdit.disabled, false);

  // Cancelling leaves selection mode and clears the selection.
  page.selectionToggle.click();
  assert.equal(page.toggleLabel.textContent, "Select");
  assert.equal(page.list.classList.contains("selection-mode"), false);
  assert.equal(page.bulkControls.classList.contains("is-selection-mode"), false);
  assert.equal(page.bulkCount.hidden, true);
  assert.equal(page.bulkEdit.hidden, true);
  assert.equal(page.selectAllLabel.hidden, true);
  assert.equal(page.recipes[0].selectLabel.hidden, true);
  assert.equal(page.recipes[0].box.checked, false);
  assert.equal(page.bulkCount.textContent, "0 selected");

  console.log("index selection toggle checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
