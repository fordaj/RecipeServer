"use strict";

// The page URL → library Markdown path helper shared by feedback, history and
// the assistant.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PAGE_PATH_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "page-path.js",
);

global.window = { location: { pathname: "/desserts/chocolate%20cake/recipe.html" } };
let onRecipePage = true;
global.document = {
  getElementById: (id) => (onRecipePage && id === "recipe-metadata" ? {} : null),
};
vm.runInThisContext(fs.readFileSync(PAGE_PATH_JS, "utf8"), { filename: PAGE_PATH_JS });
const { markdownPathFromLocation, recipePathFromLocation } = global.window.RecipePagePath;

function main() {
  assert.equal(markdownPathFromLocation(), "desserts/chocolate cake/recipe.md");
  assert.equal(recipePathFromLocation(), "desserts/chocolate cake/recipe.md");

  onRecipePage = false;
  window.location.pathname = "/index.html";
  assert.equal(markdownPathFromLocation(), "index.md");
  assert.equal(recipePathFromLocation(), null, "the index has no embedded recipe metadata");

  console.log("page path checks passed");
}

main();
