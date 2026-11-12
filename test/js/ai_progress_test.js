"use strict";

// Behavioural checks for the AI generation progress panel. The progress module
// is loaded into the DOM stub from dom_stub.js so the batching, immediate
// status transitions, thinking output, and metrics can be driven the way the
// browser drives them.

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

  const thinking = element(document, "details", "recipe-editor__ai-thinking");
  thinking.hidden = true;
  const thinkingText = element(document, "pre", "recipe-editor__ai-thinking-text");
  thinking.append(element(document, "summary"), thinkingText);
  progress.append(thinking);

  const preview = element(document, "pre", "recipe-editor__ai-preview");
  preview.hidden = true;
  progress.append(preview);

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
  return { root, status, progress, thinking, thinkingText, preview, metrics };
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function metricText(root, className) {
  return root.querySelector(`.${className}`).textContent;
}

async function main() {
  const document = createDocument();
  globalThis.window = {};
  globalThis.document = document;
  require(AI_PROGRESS_JS);

  const { createProgress } = window.RecipeAIProgress;
  const elements = buildRoot(document);
  const progress = createProgress(elements.root, { flushInterval: 25 });

  // Starting a generation shows the panel and the initial status immediately.
  progress.start("Recipe text received.");
  assert.equal(elements.status.textContent, "Recipe text received.");
  assert.equal(elements.progress.hidden, false);

  // Status transitions are applied immediately, not on the content interval.
  progress.handle({ type: "status", state: "checking_model", message: "Checking model status..." });
  assert.equal(elements.status.textContent, "Checking model status...");

  // Thinking is shown in its own collapsible block and batched like content.
  progress.handle({ type: "thinking", text: "Considering " });
  assert.equal(elements.thinking.hidden, false);
  assert.equal(elements.thinkingText.textContent, "");
  assert.equal(elements.status.textContent, "Thinking...");

  await sleep(40);
  assert.equal(elements.thinkingText.textContent, "Considering ");

  // The first content chunk switches the status immediately, but the preview
  // waits for the batch interval.
  progress.handle({ type: "content", text: "Hello" });
  assert.equal(elements.status.textContent, "Generating...");
  assert.equal(elements.preview.textContent, "");

  await sleep(40);
  assert.equal(elements.preview.textContent, "Hello");
  assert.equal(elements.preview.hidden, false);

  // More content is batched: the old preview remains until the timer fires.
  progress.handle({ type: "content", text: " world" });
  assert.equal(elements.preview.textContent, "Hello");

  await sleep(40);
  assert.equal(elements.preview.textContent, "Hello world");

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

  // Completion flushes buffered content immediately instead of waiting for the
  // next interval.
  progress.handle({ type: "content", text: "!" });
  assert.equal(elements.preview.textContent, "Hello world");
  progress.handle({ type: "status", state: "complete", message: "Generation complete." });
  assert.equal(elements.status.textContent, "Generation complete.");
  assert.equal(elements.preview.textContent, "Hello world!");

  // An error also flushes and is shown as the final status.
  progress.handle({ type: "content", text: " partial" });
  progress.handle({ type: "error", message: "Generation failed: boom" });
  assert.equal(elements.status.textContent, "Generation failed: boom");
  assert.equal(elements.preview.textContent, "Hello world! partial");

  // Flushing with no new information must not touch the DOM again.
  let previewWrites = 0;
  let previewValue = elements.preview.textContent;
  Object.defineProperty(elements.preview, "textContent", {
    get() {
      return previewValue;
    },
    set(value) {
      previewWrites += 1;
      previewValue = String(value);
    },
  });

  progress.handle({ type: "content", text: " again" });
  await sleep(40);
  const writesAfterUpdate = previewWrites;
  progress.flush();
  progress.flush();
  assert.equal(previewWrites, writesAfterUpdate);

  // Resetting clears every part of the panel.
  progress.reset();
  assert.equal(elements.progress.hidden, true);
  assert.equal(elements.preview.textContent, "");
  assert.equal(elements.thinking.hidden, true);
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

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
