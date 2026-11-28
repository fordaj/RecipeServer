"use strict";

// Behavioural checks for the shared SSE reader used by the AI progress UI and
// the assistant chat. Both consumers must see the same frames, including one
// that ends without a trailing blank line.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SSE_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "sse.js");

global.window = {};
vm.runInThisContext(fs.readFileSync(SSE_JS, "utf8"), { filename: SSE_JS });
const { parseEventBlock, readEventStream } = global.window.RecipeSSE;

function bodyFrom(text) {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  return {
    getReader() {
      return {
        async read() {
          if (offset >= bytes.length) {
            return { done: true, value: undefined };
          }
          const chunk = bytes.slice(offset, offset + 3);
          offset += chunk.length;
          return { done: false, value: chunk };
        },
      };
    },
  };
}

async function main() {
  const framed = parseEventBlock('event: result\ndata: {"type":"result","result":{"reply":"Hi"}}');
  assert.equal(framed.type, "result");
  assert.equal(framed.result.reply, "Hi");

  const dataOnly = parseEventBlock('data: {"type":"status","message":"Thinking"}');
  assert.equal(dataOnly.type, "status");
  assert.equal(dataOnly.message, "Thinking");

  assert.equal(parseEventBlock("event: ping"), null);
  assert.equal(parseEventBlock("data: not-json"), null);

  const stream = [
    'event: status\ndata: {"type":"status","message":"Checking"}\n\n',
    'event: status\ndata: {"type":"status","message":"Done"}\n\n',
    'event: result\ndata: {"type":"result","result":{"reply":"Final"}}',
  ].join("");
  const events = [];
  await readEventStream(bodyFrom(stream), (event) => events.push(event));

  assert.deepEqual(
    events.map((event) => event.type),
    ["status", "status", "result"],
  );
  assert.equal(events[2].result.reply, "Final");

  let unavailable = false;
  try {
    await readEventStream(null, () => {});
  } catch (error) {
    unavailable = /progress stream is unavailable/.test(error.message);
  }
  assert.equal(unavailable, true, "missing stream body should be reported");

  console.log("sse reader checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
