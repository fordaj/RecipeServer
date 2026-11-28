"use strict";

// Behaviour of the shared JSON API wrapper used by every page bundle.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const API_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "api.js");

global.window = {};
vm.runInThisContext(fs.readFileSync(API_JS, "utf8"), { filename: API_JS });
const { requestJson } = global.window.RecipeApi;

function stubFetch(response) {
  global.fetch = async () => response;
}

async function main() {
  stubFetch({ ok: true, status: 200, json: async () => ({ ok: true }) });
  assert.deepEqual(await requestJson("/api/x", { cache: "no-store" }), { ok: true });

  stubFetch({ ok: false, status: 404, json: async () => ({ error: "Markdown file not found" }) });
  await assert.rejects(() => requestJson("/api/x"), (error) => error.status === 404 && /Markdown file not found/.test(error.message));

  // A non-JSON error (403/503 from a reverse proxy) must not surface as a
  // SyntaxError from response.json().
  stubFetch({ ok: false, status: 503, json: async () => { throw new SyntaxError("bad json"); } });
  await assert.rejects(() => requestJson("/api/x", { fallbackMessage: "Transcription failed" }), /Transcription failed \(HTTP 503\)/);

  stubFetch({ ok: true, status: 200, json: async () => ({ success: false }) });
  await assert.rejects(() => requestJson("/api/x", { expectSuccess: true, fallbackMessage: "Save failed" }), /Save failed/);
  assert.deepEqual(await requestJson("/api/x", { expectSuccess: true }).catch(() => ({})), {});

  stubFetch({ ok: true, status: 200, json: async () => ({ success: true, value: 1 }) });
  assert.deepEqual(await requestJson("/api/x", { expectSuccess: true }), { success: true, value: 1 });

  console.log("api wrapper checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
