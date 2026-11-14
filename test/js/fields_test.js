"use strict";

// Behavioural checks for the recipe editor field scaffolding. The fields are
// built from descriptors in fields.js; this test builds the three groups and
// checks the generated DOM contract that recipe-editor.js and
// metadata-picker.js consume.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const FIELDS_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "recipe-editor",
  "fields.js",
);

function fieldset(document, group) {
  const container = document.createElement("fieldset");
  container.setAttribute("data-field-group", group);
  document.body.append(container);
  return container;
}

function names(container) {
  return container.querySelectorAll("input, select").map((element) => element.getAttribute("name"));
}

function main() {
  const document = createDocument();
  globalThis.window = {};
  globalThis.document = document;

  const details = fieldset(document, "details");
  const sources = fieldset(document, "sources");
  const ratings = fieldset(document, "ratings");

  require(FIELDS_JS);
  window.RecipeEditorFields.buildFieldGroups(document);

  // ----- Details group ----- //
  assert.ok(details.children.length > 0, "details group is populated");
  const detailNames = names(details);
  for (const name of ["createdOn", "makes", "difficulty", "archived"]) {
    assert.ok(detailNames.includes(name), `details group has a ${name} field`);
  }
  // Picker fields render the metadata-picker hook, not a free-text input.
  const pickers = details.querySelectorAll(".recipe-editor__picker");
  assert.equal(pickers.length, 6, "six picker fields");
  assert.deepEqual(pickers.map((element) => element.getAttribute("data-field")).sort(), [
    "categories",
    "contributor",
    "cuisine",
    "meals",
    "status",
    "tags",
  ]);

  // Every generated field carries a MIXED badge and a bulk Save button.
  const detailMixed = details.querySelectorAll(".recipe-editor__mixed");
  assert.equal(
    detailMixed.length,
    10,
    "ten MIXED badges in details (all fields, including the checkbox)",
  );
  assert.ok(detailMixed.every((element) => element.hidden === true));
  const detailSave = details.querySelectorAll(".recipe-editor__bulk-field-save");
  assert.equal(detailSave.length, 10, "ten bulk Save buttons in details");
  assert.ok(detailSave.every((element) => element.hidden === true));

  // The numeric pair shares the .recipe-editor__numeric wrapper.
  const numeric = details.querySelectorAll(".recipe-editor__numeric");
  assert.equal(numeric.length, 1);
  assert.deepEqual(names(numeric[0]).sort(), ["difficulty", "makes"]);

  // The archived checkbox is a checkbox input.
  const archived = details
    .querySelectorAll("input")
    .find((element) => element.getAttribute("name") === "archived");
  assert.ok(archived, "archived checkbox exists");
  assert.equal(archived.getAttribute("type"), "checkbox");

  // ----- Sources group ----- //
  assert.deepEqual(names(sources), [
    "source.author",
    "source.title",
    "source.format",
    "source.url",
  ]);
  const selects = sources.querySelectorAll("select");
  assert.equal(selects.length, 1, "source.format is a select");
  assert.deepEqual(
    selects[0].children.map((option) => option.value),
    ["", "Website", "AI", "Book", "Other"],
  );
  // All four source fields save the shared "source" key.
  assert.deepEqual(
    sources
      .querySelectorAll(".recipe-editor__bulk-field-save")
      .map((element) => element.getAttribute("data-field")),
    ["source", "source", "source", "source"],
  );

  // ----- Ratings group ----- //
  assert.deepEqual(names(ratings), ["rating.name", "rating.score"]);
  // The rating score field is not bulk-savable and carries no MIXED badge.
  assert.equal(ratings.querySelectorAll(".recipe-editor__mixed").length, 1);
  assert.deepEqual(
    ratings
      .querySelectorAll(".recipe-editor__bulk-field-save")
      .map((element) => element.getAttribute("data-field")),
    ["rating"],
  );
  const score = ratings
    .querySelectorAll("input")
    .find((element) => element.getAttribute("name") === "rating.score");
  assert.equal(score.getAttribute("type"), "number");
  assert.equal(score.getAttribute("min"), "0");
  assert.equal(score.getAttribute("max"), "10");

  // ----- aria labels are derivable ----- //
  const labels = details
    .querySelectorAll(".recipe-editor__bulk-field-save")
    .map((element) => element.getAttribute("aria-label"));
  assert.ok(labels.includes("Save contributor to all selected recipes"));
  assert.ok(labels.includes("Save contribution date to all selected recipes"));
  assert.ok(labels.includes("Save archived to all selected recipes"));

  console.log("editor fields checks passed");
}

main();
