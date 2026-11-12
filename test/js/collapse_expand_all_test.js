"use strict";

// Behavioural checks for the button that collapses or expands every section
// of a recipe at once. The recipe script is loaded into the DOM stub from
// dom_stub.js so the button can be driven the way a browser would drive it.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const RECIPE_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "recipe.js");

function buildPage(document) {
  const title = document.createElement("h1");
  title.textContent = "Pancakes";

  const ingredients = document.createElement("h2");
  ingredients.textContent = "Ingredients";

  const list = document.createElement("ul");
  const item = document.createElement("li");
  item.textContent = "flour";
  list.append(item);

  const method = document.createElement("h2");
  method.textContent = "Method";

  const steps = document.createElement("ol");
  steps.append(document.createElement("li"));

  // The ratings sit outside the sections of the recipe and carry a control of
  // their own, so they are never a collapsible section.
  const extras = document.createElement("section");
  extras.className = "recipe-ratings recipe-extras";

  const extrasHeading = document.createElement("h2");
  extrasHeading.textContent = "Ratings";

  const addButton = document.createElement("button");
  addButton.className = "recipe-ratings__add";

  extrasHeading.append(addButton);
  extras.append(extrasHeading);

  document.body.append(title, ingredients, list, method, steps, extras);

  return { title, ingredients, list, method, steps, extras, extrasHeading };
}

function main() {
  const document = createDocument();
  const page = buildPage(document);

  globalThis.document = document;

  require(RECIPE_JS);

  // Every section heading carries a button that collapses all of them.
  const buttons = document.querySelectorAll(".recipe-sections__toggle");
  assert.equal(buttons.length, 2);

  assert.ok(page.ingredients.querySelector(".recipe-sections__toggle"));
  assert.ok(page.method.querySelector(".recipe-sections__toggle"));

  // The heading of the ratings holds a control of its own, so it is not a
  // section and it does not get a button.
  assert.equal(page.extrasHeading.querySelector(".recipe-sections__toggle"), null);

  // The title does not carry a button.
  assert.equal(page.title.querySelector(".recipe-sections__toggle"), null);

  // Every section starts out expanded.
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "true");
  assert.equal(page.method.getAttribute("aria-expanded"), "true");
  assert.equal(page.list.hidden, false);
  assert.equal(page.steps.hidden, false);

  buttons.forEach((button) => {
    assert.equal(button.getAttribute("data-state"), "expanded");
    assert.equal(button.getAttribute("aria-label"), "Collapse all sections");
    assert.equal(button.getAttribute("title"), "Collapse all sections");
  });

  // The button collapses every section at once.
  buttons[0].click();
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "false");
  assert.equal(page.method.getAttribute("aria-expanded"), "false");
  assert.equal(page.list.hidden, true);
  assert.equal(page.steps.hidden, true);

  buttons.forEach((button) => {
    assert.equal(button.getAttribute("data-state"), "collapsed");
    assert.equal(button.getAttribute("aria-label"), "Expand all sections");
    assert.equal(button.getAttribute("title"), "Expand all sections");
  });

  // The ratings and the comments are not a section, so they stay visible.
  assert.equal(page.extras.hidden, false);

  // The button expands every section again.
  buttons[1].click();
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "true");
  assert.equal(page.method.getAttribute("aria-expanded"), "true");
  assert.equal(page.list.hidden, false);
  assert.equal(page.steps.hidden, false);

  buttons.forEach((button) => {
    assert.equal(button.getAttribute("data-state"), "expanded");
    assert.equal(button.getAttribute("aria-label"), "Collapse all sections");
  });

  // Collapsing a single section by hand changes what the buttons offer.
  page.ingredients.click();
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "false");
  assert.equal(page.list.hidden, true);
  assert.equal(buttons[0].getAttribute("data-state"), "collapsed");
  assert.equal(buttons[0].getAttribute("aria-label"), "Expand all sections");

  // The buttons open every section again, including the one closed by hand.
  buttons[0].click();
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "true");
  assert.equal(page.method.getAttribute("aria-expanded"), "true");
  assert.equal(page.list.hidden, false);
  assert.equal(page.steps.hidden, false);

  // The keys of the button belong to the button, not to the section.
  buttons[0].dispatchEvent({ type: "keydown", key: "Enter" });
  assert.equal(page.ingredients.getAttribute("aria-expanded"), "true");
  assert.equal(page.method.getAttribute("aria-expanded"), "true");

  console.log("collapse and expand all sections checks passed");
}

main();
