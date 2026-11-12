"use strict";

// Behavioural checks for the rating controls on a recipe page. The recipe
// script is loaded into the DOM stub from dom_stub.js so the star slider and
// the score field can be driven the way a browser would drive them.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const RATINGS_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "ratings.js");

const RATING = {
  name: "Avery",
  rating: 8,
  id: "rating-1",
  created: "2026-01-01T00:00:00.000Z",
  updated: "2026-01-01T00:00:00.000Z",
};

// The slider is five stars wide, so a tenth of the width is half a star.
const SLIDER_WIDTH = 500;

function buildPage(document) {
  const root = document.createElement("section");
  root.setAttribute("id", "recipe-ratings");
  document.body.append(root);

  const addButton = document.createElement("button");
  addButton.className = "recipe-ratings__add";
  root.append(addButton);

  const form = document.createElement("form");
  form.setAttribute("id", "recipe-rating-form");
  form.hidden = true;

  const authorInput = document.createElement("input");
  authorInput.setAttribute("id", "rating-author");
  authorInput.setAttribute("aria-label", "Your name");

  const scoreInput = document.createElement("input");
  scoreInput.setAttribute("id", "rating-score");
  scoreInput.setAttribute("aria-label", "Rating out of 10");
  scoreInput.value = "5";
  scoreInput.defaultValue = "5";

  const scoreValue = document.createElement("output");
  scoreValue.setAttribute("id", "rating-score-value");

  const stars = document.createElement("span");
  stars.className = "recipe-rating__stars";
  stars.textContent = "★★★★★";

  const status = document.createElement("p");
  status.setAttribute("id", "rating-status");

  const cancelButton = document.createElement("button");
  cancelButton.setAttribute("id", "cancel-rating");

  const saveButton = document.createElement("button");
  saveButton.setAttribute("id", "save-rating");

  form.append(authorInput, scoreInput, scoreValue, stars, status, cancelButton, saveButton);
  root.append(form);

  const list = document.createElement("div");
  list.setAttribute("id", "rating-list");
  root.append(list);

  return { root, addButton, form, authorInput, scoreInput, scoreValue, status, list };
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

// Presses the slider at a fraction of its width, the way a pointer would.
function pressSlider(slider, fraction) {
  slider.rect = { left: 0, top: 0, width: SLIDER_WIDTH, height: 40 };
  slider.dispatchEvent({
    type: "pointerdown",
    pointerId: 1,
    clientX: fraction * SLIDER_WIDTH,
    clientY: 20,
    preventDefault() {},
  });
}

function dragSlider(slider, fraction) {
  slider.dispatchEvent({
    type: "pointermove",
    pointerId: 1,
    clientX: fraction * SLIDER_WIDTH,
    clientY: 20,
    preventDefault() {},
  });
}

function releaseSlider(slider) {
  slider.dispatchEvent({ type: "pointerup", pointerId: 1, preventDefault() {} });
}

async function main() {
  const document = createDocument();
  const page = buildPage(document);

  globalThis.window = { location: { pathname: "/pancakes/recipe.html" } };
  globalThis.document = document;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({ value: [RATING] }),
  });

  require(RATINGS_JS);
  await tick();

  // The add form replaces its static stars with a slider.
  const formSlider = document.querySelector("#recipe-rating-form .recipe-rating__stars--slider");
  assert.ok(formSlider, "the add form renders a star slider");
  assert.equal(formSlider.getAttribute("role"), "slider");
  assert.equal(formSlider.getAttribute("aria-valuemin"), "1");
  assert.equal(formSlider.getAttribute("aria-valuemax"), "10");
  assert.equal(formSlider.querySelectorAll(".recipe-rating__star").length, 5);

  // Pressing the slider sets the score field to the pressed score.
  page.addButton.click();
  pressSlider(formSlider, 0.5);
  assert.equal(page.scoreInput.value, "6");
  assert.equal(page.scoreValue.textContent, "6/10");
  assert.equal(formSlider.getAttribute("aria-valuenow"), "6");
  assert.equal(formSlider.getAttribute("aria-valuetext"), "6 out of 10");

  // The left half of a star is worth one point, the right half two.
  pressSlider(formSlider, 0.05);
  assert.equal(page.scoreInput.value, "1");
  pressSlider(formSlider, 0.15);
  assert.equal(page.scoreInput.value, "2");
  pressSlider(formSlider, 0.25);
  assert.equal(page.scoreInput.value, "3");

  // The slider cannot select zero, not even at its very edge.
  pressSlider(formSlider, 0);
  assert.equal(page.scoreInput.value, "1");
  assert.equal(formSlider.getAttribute("aria-valuenow"), "1");

  // The far end of the slider is a full score.
  pressSlider(formSlider, 0.99);
  assert.equal(page.scoreInput.value, "10");
  assert.equal(formSlider.getAttribute("aria-valuenow"), "10");

  // Dragging along the slider keeps updating the score.
  pressSlider(formSlider, 0.05);
  dragSlider(formSlider, 0.45);
  assert.equal(page.scoreInput.value, "5");
  releaseSlider(formSlider);
  dragSlider(formSlider, 0.95);
  assert.equal(page.scoreInput.value, "5");

  // Clicking the score field highlights it so typing replaces the score.
  page.scoreInput.selected = false;
  page.scoreInput.click();
  assert.ok(page.scoreInput.selected, "clicking the score field highlights it");

  // Opening the edit form swaps the static meter for a slider as well.
  const editButton = page.list.querySelector("button[data-action='edit']");
  assert.ok(editButton, "the rating list offers an edit button");
  editButton.click();
  await tick();

  const editForm = document.querySelector(".recipe-rating__edit");
  assert.ok(editForm, "the edit form is rendered");
  const editScore = editForm.querySelector("input[aria-label='Rating out of 10']");
  const editSlider = editForm.querySelector(".recipe-rating__stars--slider");
  assert.ok(editSlider, "the edit form renders a star slider");

  // The slider starts on the rating that is being edited.
  assert.equal(editSlider.getAttribute("aria-valuenow"), "8");
  assert.equal(editSlider.getAttribute("aria-valuetext"), "8 out of 10");

  // Pressing a star during an edit updates the score field.
  pressSlider(editSlider, 0.35);
  assert.equal(editScore.value, "4");
  assert.equal(editForm.querySelector(".recipe-rating__score").textContent, "4/10");
  assert.equal(editSlider.getAttribute("aria-valuenow"), "4");

  // Typing a score updates the slider, including half filled stars.
  editScore.value = "7.5";
  editScore.dispatchEvent({ type: "input" });
  assert.equal(editSlider.getAttribute("aria-valuenow"), "7.5");
  assert.equal(editSlider.getAttribute("aria-valuetext"), "7.5 out of 10");
  assert.equal(editSlider.style.getPropertyValue("--rating-fill"), "75%");

  // The arrow keys move the slider one point at a time.
  editSlider.dispatchEvent({ type: "keydown", key: "ArrowRight" });
  assert.equal(editScore.value, "9");
  editSlider.dispatchEvent({ type: "keydown", key: "ArrowLeft" });
  assert.equal(editScore.value, "8");
  editSlider.dispatchEvent({ type: "keydown", key: "Home" });
  assert.equal(editScore.value, "1");
  editSlider.dispatchEvent({ type: "keydown", key: "End" });
  assert.equal(editScore.value, "10");

  console.log("rating star slider checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
