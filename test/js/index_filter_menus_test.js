"use strict";

// Behavioural checks for the multi-select filters in the index Advanced
// section. The index script is loaded into the DOM stub so the checkboxes
// can be driven the way a browser would drive them.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const INDEX_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "index.js");

function element(document, tagName, attributes = {}) {
  const node = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

function buildMenu(document, { controlId, filter, label, allLabel, options }) {
  const menu = element(document, "details", {
    class: "filter-control filter-menu",
    id: controlId,
    "data-filter": filter,
    "data-filter-label": label,
  });
  menu.open = false;

  const summary = element(document, "summary");
  const summaryLabel = element(document, "span", {
    class: "filter-menu__label",
    id: `${controlId}-label`,
  });
  summaryLabel.textContent = `${label}: All`;
  summary.append(summaryLabel);
  menu.append(summary);

  const fieldset = element(document, "fieldset", { class: "filter-menu__menu" });
  const allOption = element(document, "label", {
    class: "filter-menu__option filter-menu__option--all",
  });
  const allBox = element(document, "input", {
    type: "checkbox",
    class: "filter-option-all",
    id: `${controlId}-all`,
  });
  allBox.checked = true;
  const allName = element(document, "span");
  allName.textContent = allLabel;
  const allCount = element(document, "span", { class: "filter-menu__count" });
  allCount.textContent = "0";
  allOption.append(allBox, allName, allCount);
  fieldset.append(allOption);

  const boxes = options.map(({ value, text }) => {
    const option = element(document, "label", { class: "filter-menu__option" });
    const box = element(document, "input", {
      type: "checkbox",
      class: "filter-option",
      value,
    });
    box.value = value;
    const name = element(document, "span");
    name.textContent = text;
    const count = element(document, "span", { class: "filter-menu__count" });
    count.textContent = "0";
    option.append(box, name, count);
    fieldset.append(option);
    return { box, count };
  });

  menu.append(fieldset);
  return { menu, summaryLabel, allBox, allCount, boxes };
}

function buildRecipe(document, { title, meals, categories, archived = false }) {
  const slug = title.toLowerCase();
  const recipe = element(document, "li", {
    class: "recipe",
    "data-path": `${slug}/recipe.md`,
    "data-title": title,
    "data-search": `${title} ${meals.join(" ")} ${categories.join(" ")}`.toLowerCase(),
    "data-meals": JSON.stringify(meals),
    "data-categories": JSON.stringify(categories),
    "data-ratings": "[]",
    "data-archived": archived ? "true" : "false",
  });
  recipe.append(element(document, "article", { class: "recipe-card" }));
  return recipe;
}

function buildPage(document) {
  const search = element(document, "input", { id: "recipe-search" });
  const sort = element(document, "select", { id: "sort-recipes" });
  sort.value = "title:asc";
  const count = element(document, "p", { id: "recipe-count" });
  const clearFilters = element(document, "button", { id: "clear-filters" });
  clearFilters.hidden = true;
  const metadataStatus = element(document, "input", { id: "metadata-status" });
  const showArchived = element(document, "input", { id: "show-archived" });
  showArchived.checked = false;

  const meals = buildMenu(document, {
    controlId: "filter-meal",
    filter: "meals",
    label: "Meals",
    allLabel: "All meals",
    options: [
      { value: "breakfast", text: "Breakfast" },
      { value: "dinner", text: "Dinner" },
    ],
  });
  const categories = buildMenu(document, {
    controlId: "filter-category",
    filter: "categories",
    label: "Categories",
    allLabel: "All categories",
    options: [
      { value: "baking", text: "Baking" },
      { value: "dinner", text: "Dinner" },
    ],
  });

  const recipes = [
    buildRecipe(document, { title: "Alpha", meals: ["Breakfast"], categories: ["Baking"] }),
    buildRecipe(document, {
      title: "Beta",
      meals: ["Breakfast", "Dinner"],
      categories: ["Dinner"],
    }),
    buildRecipe(document, {
      title: "Gamma",
      meals: ["Dinner"],
      categories: ["Dinner"],
      archived: true,
    }),
  ];

  const list = element(document, "ul", { id: "recipe-list" });
  list.append(...recipes);

  document.body.append(
    search,
    sort,
    count,
    clearFilters,
    metadataStatus,
    showArchived,
    meals.menu,
    categories.menu,
    list,
  );

  return { search, sort, count, clearFilters, showArchived, meals, categories, recipes, list };
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function visibleTitles(page) {
  return page.recipes.filter((recipe) => !recipe.hidden).map((recipe) => recipe.dataset.title);
}

function counts(menu) {
  return Object.fromEntries(menu.boxes.map(({ box, count }) => [box.value, count.textContent]));
}

function select(document, box) {
  box.checked = !box.checked;
  box.dispatchEvent({ type: "change" });
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

  // Initial counts ignore archived recipes.
  assert.deepEqual(visibleTitles(page), ["Alpha", "Beta"]);
  assert.equal(page.count.textContent, "2 of 2 recipes");
  assert.equal(page.clearFilters.hidden, true);
  assert.deepEqual(counts(page.meals), { breakfast: "2", dinner: "1" });
  assert.deepEqual(counts(page.categories), { baking: "1", dinner: "1" });
  assert.equal(page.meals.allCount.textContent, "2");
  assert.equal(page.meals.summaryLabel.textContent, "Meals: All");

  // Selecting one meal filters the list and updates the summary.
  select(document, page.meals.boxes[0].box);
  assert.equal(page.meals.allBox.checked, false);
  assert.equal(page.meals.summaryLabel.textContent, "Meals: 1 selected");
  assert.deepEqual(visibleTitles(page), ["Alpha", "Beta"]);
  assert.equal(page.clearFilters.hidden, false);

  // Counts respect the other filters.
  assert.deepEqual(counts(page.categories), { baking: "1", dinner: "1" });

  // Selecting a second value widens the same field (OR) instead of narrowing it.
  select(document, page.meals.boxes[1].box);
  assert.equal(page.meals.summaryLabel.textContent, "Meals: 2 selected");
  assert.deepEqual(visibleTitles(page), ["Alpha", "Beta"]);

  // Different fields still combine with AND.
  select(document, page.categories.boxes[1].box);
  assert.deepEqual(visibleTitles(page), ["Beta"]);
  assert.equal(page.categories.summaryLabel.textContent, "Categories: 1 selected");

  select(document, page.categories.boxes[0].box);
  assert.deepEqual(visibleTitles(page), ["Alpha", "Beta"]);
  assert.equal(page.count.textContent, "2 of 2 recipes");

  // Search narrows both the results and the option counts.
  page.search.value = "alpha";
  page.search.dispatchEvent({ type: "input" });
  assert.deepEqual(visibleTitles(page), ["Alpha"]);
  assert.equal(page.count.textContent, "1 of 2 recipes");
  assert.deepEqual(counts(page.categories), { baking: "1", dinner: "0" });
  assert.deepEqual(counts(page.meals), { breakfast: "1", dinner: "0" });

  // Showing archived recipes updates the totals without changing the matches.
  page.showArchived.checked = true;
  page.showArchived.dispatchEvent({ type: "change" });
  assert.deepEqual(visibleTitles(page), ["Alpha"]);
  assert.equal(page.count.textContent, "1 of 3 recipes");

  // Unchecking the last value restores the All option.
  select(document, page.meals.boxes[0].box);
  assert.equal(page.meals.allBox.checked, false);
  select(document, page.meals.boxes[1].box);
  assert.equal(page.meals.allBox.checked, true);
  assert.equal(page.meals.summaryLabel.textContent, "Meals: All");

  // Clear filters resets the search and every menu.
  page.clearFilters.click();
  assert.equal(page.search.value, "");
  assert.equal(page.showArchived.checked, false);
  assert.equal(page.meals.allBox.checked, true);
  assert.equal(page.categories.allBox.checked, true);
  assert.deepEqual(visibleTitles(page), ["Alpha", "Beta"]);
  assert.equal(page.count.textContent, "2 of 2 recipes");
  assert.equal(page.clearFilters.hidden, true);

  console.log("index filter menu checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
