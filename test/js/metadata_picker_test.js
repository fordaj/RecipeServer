"use strict";

// Behavioural checks for the metadata dropdowns in the recipe editor. The
// picker script is loaded into the DOM stub from dom_stub.js so the dropdown
// and the "Add new" text field can be driven the way a browser would drive
// them.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const PICKER_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "recipe-editor",
  "metadata-picker.js",
);

function buildPicker(document, field) {
  const container = document.createElement("span");
  container.className = "recipe-editor__picker";
  container.setAttribute("data-field", field);
  document.body.append(container);
  return container;
}

function optionValues(select) {
  return select.children.map((option) => option.value);
}

function optionTexts(select) {
  return select.children.map((option) => option.textContent);
}

function chipValues(picker) {
  return picker.valuesElement.children.map((chip) => chip.dataset.value);
}

function chipTexts(picker) {
  return picker.valuesElement.children.map(
    (chip) => chip.querySelector(".recipe-editor__picker-chip-label").textContent,
  );
}

function choose(select, value) {
  select.value = value;
  select.dispatchEvent({ type: "change" });
}

function main() {
  const document = createDocument();
  globalThis.window = {};
  globalThis.document = document;
  require(PICKER_JS);

  const { createPickers, NEW_VALUE } = window.RecipeMetadataPicker;

  buildPicker(document, "meals");
  buildPicker(document, "status");
  const pickers = createPickers(document.body);

  const meals = pickers.get("meals");
  const status = pickers.get("status");

  pickers.setOptions("meals", [
    { value: "Breakfast", count: 3 },
    { value: "Dinner", count: 1 },
  ]);
  pickers.setOptions("status", [
    { value: "In Rotation", count: 2 },
    { value: "Try Me", count: 1 },
  ]);

  // The dropdown offers the values that are already in the library, each with
  // the number of recipes that use it. "Add new" is at the top so a value that
  // is not in the library yet is always one click away.
  assert.deepEqual(optionValues(meals.select), ["", NEW_VALUE, "Breakfast", "Dinner"]);
  assert.deepEqual(optionTexts(meals.select), [
    "Add meal",
    "Add new…",
    "Breakfast (3)",
    "Dinner (1)",
  ]);
  assert.deepEqual(optionTexts(status.select), [
    "Select status",
    "Add new…",
    "In Rotation (2)",
    "Try Me (1)",
  ]);

  // Selecting an existing value adds it to the field.
  choose(meals.select, "Dinner");
  assert.deepEqual(meals.getValues(), ["Dinner"]);
  assert.deepEqual(chipValues(meals), ["Dinner"]);

  // The chip shows how many recipes use the value.
  assert.deepEqual(chipTexts(meals), ["Dinner (1)"]);

  // A value that is already set is no longer offered in the dropdown.
  assert.deepEqual(optionValues(meals.select), ["", NEW_VALUE, "Breakfast"]);

  // "Add new" swaps the dropdown for a text field.
  choose(meals.select, NEW_VALUE);
  assert.equal(meals.select.hidden, true);
  assert.equal(meals.newInput.hidden, false);
  assert.equal(meals.newInput.getAttribute("aria-label"), "New meal");

  // The typed value is added when it is confirmed. It is not in the library
  // yet, so it has no count.
  meals.newInput.value = "Brunch";
  meals.addButton.click();
  assert.deepEqual(meals.getValues(), ["Dinner", "Brunch"]);
  assert.deepEqual(chipValues(meals), ["Dinner", "Brunch"]);
  assert.deepEqual(chipTexts(meals), ["Dinner (1)", "Brunch"]);
  assert.equal(meals.select.hidden, false);
  assert.equal(meals.newInput.hidden, true);

  // The Enter key confirms a typed value too.
  choose(meals.select, NEW_VALUE);
  meals.newInput.value = "Snack";
  meals.newInput.dispatchEvent({ type: "keydown", key: "Enter" });
  assert.deepEqual(meals.getValues(), ["Dinner", "Brunch", "Snack"]);

  // Escape throws the typed value away.
  choose(meals.select, NEW_VALUE);
  meals.newInput.value = "Discarded";
  meals.newInput.dispatchEvent({ type: "keydown", key: "Escape" });
  assert.deepEqual(meals.getValues(), ["Dinner", "Brunch", "Snack"]);
  assert.equal(meals.select.hidden, false);

  // A chip can be removed again.
  const removeButton = meals.valuesElement.children[0].querySelector(
    ".recipe-editor__picker-chip-remove",
  );
  removeButton.click();
  assert.deepEqual(meals.getValues(), ["Brunch", "Snack"]);

  // A single-value field keeps exactly one value.
  choose(status.select, "Try Me");
  assert.deepEqual(status.getValues(), ["Try Me"]);
  assert.deepEqual(chipTexts(status), ["Try Me (1)"]);
  choose(status.select, "In Rotation");
  assert.deepEqual(status.getValues(), ["In Rotation"]);

  // Values that are loaded from a recipe replace whatever was selected, and
  // they pick up the count of the library.
  meals.setValues(["Breakfast"]);
  assert.deepEqual(meals.getValues(), ["Breakfast"]);
  assert.deepEqual(chipTexts(meals), ["Breakfast (3)"]);

  meals.setValues([]);
  assert.deepEqual(meals.getValues(), []);

  // The same value is never added twice.
  meals.setValues(["Dinner", "dinner"]);
  assert.deepEqual(meals.getValues(), ["Dinner"]);

  // A single-value field only keeps the first loaded value.
  status.setValues(["In Rotation", "Try Me"]);
  assert.deepEqual(status.getValues(), ["In Rotation"]);

  console.log("metadata picker checks passed");
}

main();
