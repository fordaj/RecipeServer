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

function chipValues(picker) {
  return picker.valuesElement.children.map((chip) => chip.dataset.value);
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

  pickers.setOptions("meals", ["Breakfast", "Dinner"]);
  pickers.setOptions("status", ["In Rotation", "Try Me"]);

  // The dropdown offers the values that are already in the library, plus a
  // way to add a value that is not in it yet.
  assert.deepEqual(optionValues(meals.select), ["", "Breakfast", "Dinner", NEW_VALUE]);
  assert.deepEqual(optionValues(status.select), ["", "In Rotation", "Try Me", NEW_VALUE]);

  // Selecting an existing value adds it to the field.
  choose(meals.select, "Dinner");
  assert.deepEqual(meals.getValues(), ["Dinner"]);
  assert.deepEqual(chipValues(meals), ["Dinner"]);

  // A value that is already set is no longer offered in the dropdown.
  assert.deepEqual(optionValues(meals.select), ["", "Breakfast", NEW_VALUE]);

  // "Add new" swaps the dropdown for a text field.
  choose(meals.select, NEW_VALUE);
  assert.equal(meals.select.hidden, true);
  assert.equal(meals.newInput.hidden, false);
  assert.equal(meals.newInput.getAttribute("aria-label"), "New meal");

  // The typed value is added when it is confirmed.
  meals.newInput.value = "Brunch";
  meals.addButton.click();
  assert.deepEqual(meals.getValues(), ["Dinner", "Brunch"]);
  assert.deepEqual(chipValues(meals), ["Dinner", "Brunch"]);
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
  choose(status.select, "In Rotation");
  assert.deepEqual(status.getValues(), ["In Rotation"]);

  // Values that are loaded from a recipe replace whatever was selected.
  meals.setValues(["Dinner", "Lunch"]);
  assert.deepEqual(meals.getValues(), ["Dinner", "Lunch"]);
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
