"use strict";

// Behavioural checks for the AI generation progress panel. The progress module
// is loaded into the DOM stub from dom_stub.js so the status transitions and
// metrics can be driven the way the browser drives them.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const AI_PROGRESS_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "recipe-editor",
  "ai-progress.js",
);

function element(document, tagName, className) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  return node;
}

function buildRoot(document) {
  const root = element(document, "fieldset", "recipe-editor__section recipe-editor__ai");

  const status = element(document, "p", "recipe-editor__ai-status");
  root.append(status);

  const progress = element(document, "div", "recipe-editor__ai-progress");
  progress.hidden = true;
  root.append(progress);

  const metrics = element(document, "dl", "recipe-editor__ai-metrics");
  metrics.hidden = true;
  for (const className of [
    "recipe-editor__ai-metric-model-load",
    "recipe-editor__ai-metric-generation",
    "recipe-editor__ai-metric-tokens",
    "recipe-editor__ai-metric-rate",
  ]) {
    const row = element(document, "div", "recipe-editor__ai-metric");
    row.append(element(document, "dt"), element(document, "dd", className));
    metrics.append(row);
  }
  progress.append(metrics);

  document.body.append(root);
  return { root, status, progress, metrics };
}

function metricText(root, className) {
  return root.querySelector(`.${className}`).textContent;
}

function main() {
  const document = createDocument();
  globalThis.window = {};
  globalThis.document = document;
  require(AI_PROGRESS_JS);

  const { createProgress } = window.RecipeAIProgress;
  const elements = buildRoot(document);
  const progress = createProgress(elements.root);

  // Starting a generation shows the panel and the initial status immediately.
  progress.start("Recipe text received.");
  assert.equal(elements.status.textContent, "Recipe text received.");
  assert.equal(elements.progress.hidden, false);
  assert.equal(elements.metrics.hidden, true);

  // Status transitions are applied immediately.
  progress.handle({ type: "status", state: "checking_model", message: "Checking model status..." });
  assert.equal(elements.status.textContent, "Checking model status...");

  progress.handle({
    type: "status",
    state: "loading_model",
    message: "Loading model into memory...",
  });
  assert.equal(elements.status.textContent, "Loading model into memory...");

  progress.handle({ type: "status", state: "thinking", message: "Thinking..." });
  assert.equal(elements.status.textContent, "Thinking...");

  progress.handle({ type: "status", state: "generating", message: "Generating recipe..." });
  assert.equal(elements.status.textContent, "Generating recipe...");

  // Metrics only display the values that are available.
  progress.handle({
    type: "metrics",
    metrics: {
      model_load_seconds: 1.5,
      generation_seconds: 2,
      token_count: 100,
      tokens_per_second: 50,
    },
  });
  assert.equal(elements.metrics.hidden, false);
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-model-load"), "1.50 s");
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-generation"), "2.00 s");
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-tokens"), "100 tokens");
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-rate"), "50.0 tok/s");

  // Completion is shown as the final status.
  progress.handle({ type: "status", state: "complete", message: "Generation complete." });
  assert.equal(elements.status.textContent, "Generation complete.");

  // An error is shown as the final status.
  progress.handle({ type: "error", message: "Generation failed: boom" });
  assert.equal(elements.status.textContent, "Generation failed: boom");

  // Content and thinking events no longer have fields to render.
  progress.handle({ type: "content", text: "ignored" });
  progress.handle({ type: "thinking", text: "ignored" });
  assert.equal(elements.status.textContent, "Generation failed: boom");
  assert.equal(elements.metrics.hidden, false);

  // Resetting clears the panel.
  progress.reset();
  assert.equal(elements.progress.hidden, true);
  assert.equal(elements.metrics.hidden, true);
  assert.equal(elements.status.textContent, "");
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-tokens"), "");

  // A partial metrics payload still shows the panel but leaves missing values
  // blank.
  progress.handle({ type: "metrics", metrics: { token_count: 5 } });
  assert.equal(elements.metrics.hidden, false);
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-tokens"), "5 tokens");
  assert.equal(metricText(elements.root, "recipe-editor__ai-metric-model-load"), "");

  console.log("ai progress checks passed");
}

main();
