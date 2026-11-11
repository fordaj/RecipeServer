"use strict";

// Behavioural checks for the rating controls on a recipe page. The recipe
// script is loaded into the DOM stub from dom_stub.js so the star picker and
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

function starScores(picker) {
  return picker.querySelectorAll(".recipe-rating__star").map((star) => Number(star.dataset.score));
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

  // The add form replaces its static stars with a picker of five stars.
  const formPicker = document.querySelector("#recipe-rating-form .recipe-rating__star-picker");
  assert.ok(formPicker, "the add form renders a star picker");
  assert.deepEqual(starScores(formPicker), [2, 4, 6, 8, 10]);

  // Clicking a star sets the score field to the matching value.
  page.addButton.click();
  const formStars = formPicker.querySelectorAll(".recipe-rating__star");
  formStars[2].click();
  assert.equal(page.scoreInput.value, "6");
  assert.equal(page.scoreValue.textContent, "6/10");
  assert.equal(formStars[2].getAttribute("aria-checked"), "true");

  // Clicking the score field highlights it so typing replaces the score.
  page.scoreInput.selected = false;
  page.scoreInput.click();
  assert.ok(page.scoreInput.selected, "clicking the score field highlights it");

  // Opening the edit form swaps the static meter for a picker as well.
  const editButton = page.list.querySelector("button[data-action='edit']");
  assert.ok(editButton, "the rating list offers an edit button");
  editButton.click();
  await tick();

  const editForm = document.querySelector(".recipe-rating__edit");
  assert.ok(editForm, "the edit form is rendered");
  const editScore = editForm.querySelector("input[aria-label='Rating out of 10']");
  const editPicker = editForm.querySelector(".recipe-rating__star-picker");
  assert.ok(editPicker, "the edit form renders a star picker");

  const editStars = editPicker.querySelectorAll(".recipe-rating__star");
  assert.deepEqual(starScores(editPicker), [2, 4, 6, 8, 10]);

  // No star can select zero.
  assert.ok(
    starScores(editPicker).every((score) => score >= 2),
    "no star selects zero",
  );

  // Clicking a star during an edit updates the score field.
  editStars[3].click();
  assert.equal(editScore.value, "8");
  assert.equal(editForm.querySelector(".recipe-rating__score").textContent, "8/10");
  assert.equal(editStars[3].getAttribute("aria-checked"), "true");
  assert.equal(editStars[3].style.getPropertyValue("--star-fill"), "100%");
  assert.ok(editScore.selected, "the score field is highlighted after picking a star");

  // The first star selects two, never zero.
  editStars[0].click();
  assert.equal(editScore.value, "2");
  assert.equal(editStars[0].style.getPropertyValue("--star-fill"), "100%");
  assert.equal(editStars[1].style.getPropertyValue("--star-fill"), "0%");

  // Typing a score updates the stars, including half filled stars.
  editScore.value = "7.5";
  editScore.dispatchEvent({ type: "input" });
  assert.equal(editStars[3].style.getPropertyValue("--star-fill"), "75%");
  assert.equal(editStars[4].style.getPropertyValue("--star-fill"), "0%");

  // The arrow keys move through the stars.
  editStars[0].dispatchEvent({ type: "keydown", key: "ArrowRight" });
  assert.equal(editScore.value, "4");
  editStars[1].dispatchEvent({ type: "keydown", key: "ArrowLeft" });
  assert.equal(editScore.value, "2");
  editStars[0].dispatchEvent({ type: "keydown", key: "End" });
  assert.equal(editScore.value, "10");

  console.log("rating star picker checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
