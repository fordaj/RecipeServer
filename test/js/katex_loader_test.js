"use strict";

// One lazy KaTeX loader: load on demand, retry after failure, and honour the
// auto-render option used by the assistant chat.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const LOADER_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "katex-loader.js",
);

function resetEnvironment() {
  const children = [];
  let failNextScript = false;

  function makeNode(tag) {
    return {
      tag,
      src: "",
      href: "",
      rel: "",
      defer: false,
      dataset: {},
      listeners: {},
      addEventListener(type, callback) {
        (this.listeners[type] ||= []).push(callback);
      },
      remove() {
        const index = children.indexOf(this);
        if (index >= 0) children.splice(index, 1);
      },
      fire(type) {
        (this.listeners[type] || []).forEach((callback) => callback());
      },
    };
  }

  const head = {
    append(node) {
      children.push(node);
      if (node.tag === "script") {
        const shouldFail = failNextScript;
        failNextScript = false;
        queueMicrotask(() => node.fire(shouldFail ? "error" : "load"));
      }
    },
  };

  global.window = {
    katex: undefined,
    renderMathInElement: undefined,
    setTimeout: () => 1,
    clearTimeout: () => {},
  };
  global.document = {
    head,
    createElement: makeNode,
    querySelector(selector) {
      const match = /^(script|link)\[src="([^"]+)"\]$|^link\[href="([^"]+)"\]$/.exec(selector);
      if (!match) return null;
      const value = match[2] || match[3];
      return (
        children.find(
          (node) => node.tag === match[1] && (node.src === value || node.href === value),
        ) || null
      );
    },
  };

  return {
    children,
    failNext() {
      failNextScript = true;
    },
  };
}

async function main() {
  let env = resetEnvironment();
  vm.runInThisContext(fs.readFileSync(LOADER_JS, "utf8"), { filename: LOADER_JS });
  const { ensureKatex } = global.window.RecipeKatexLoader;

  await ensureKatex({ autoRender: false });
  assert.equal(
    env.children.filter((node) => node.tag === "script").length,
    1,
    "shopping list loads only katex.min.js",
  );
  assert.equal(env.children.filter((node) => node.tag === "link").length, 1);

  // Already loaded: no further assets, and no new promise needed.
  await ensureKatex({ autoRender: false });
  assert.equal(env.children.filter((node) => node.tag === "script").length, 1);

  // A failed load must not be cached: the next call can retry.
  env = resetEnvironment();
  vm.runInThisContext(fs.readFileSync(LOADER_JS, "utf8"), { filename: LOADER_JS });
  const retry = global.window.RecipeKatexLoader.ensureKatex;
  env.failNext();
  await assert.rejects(() => retry({ autoRender: false }), /Unable to load/);
  await retry({ autoRender: false });
  // The failed tag was removed and replaced by exactly one working tag.
  assert.equal(env.children.filter((node) => node.tag === "script").length, 1);

  // The assistant also needs auto-render.
  env = resetEnvironment();
  vm.runInThisContext(fs.readFileSync(LOADER_JS, "utf8"), { filename: LOADER_JS });
  await global.window.RecipeKatexLoader.ensureKatex({ autoRender: true });
  const scripts = env.children.filter((node) => node.tag === "script").map((node) => node.src);
  assert.equal(scripts.length, 2);
  assert.ok(scripts.some((src) => src.endsWith("auto-render.min.js")));

  console.log("katex loader checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
