"use strict";

// Behavioural checks for the dictation button on the index page. The script
// is loaded into the DOM stub from dom_stub.js so the button can be driven
// the way a browser would drive it: the page protocol decides whether the
// button is offered at all, and a recording is transcribed and inserted
// into the search field.

const assert = require("node:assert/strict");
const path = require("node:path");

const { createDocument } = require("./dom_stub.js");

const SPEECH_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "recipeserver",
  "assets",
  "speech-button",
  "speech-button.js",
);

// The DOM stub copies the properties of the event it is given, so a plain
// object works better here than the browser's Event class.
global.Event = class Event {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
  }
};

const recorded = [];
const fetchCalls = [];

// A stand-in for MediaRecorder that hands the recorded audio to the
// script the same way a browser does.
class FakeMediaRecorder {
  static isTypeSupported(type) {
    return type.startsWith("audio/webm");
  }

  constructor(stream, options = {}) {
    this.stream = stream;
    this.mimeType = options.mimeType || "audio/webm";
    this.state = "inactive";
    recorded.push(this);
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

global.MediaRecorder = FakeMediaRecorder;

// Node defines navigator as a read-only global, so it is replaced.
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    mediaDevices: {
      async getUserMedia() {
        return {
          getTracks: () => [{ stop() {} }],
        };
      },
    },
  },
});

global.fetch = async (url, options) => {
  fetchCalls.push({ url, options });

  return {
    ok: true,
    async json() {
      return { text: "chocolate cake" };
    },
  };
};

function element(document, tagName, attributes = {}) {
  const node = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

// Builds the search field and its dictation button the way the generated
// index page does.
function buildSearch(document) {
  const wrapper = element(document, "div", { class: "speech-input" });
  const label = element(document, "label", { class: "search-control" });
  const input = element(document, "input", { id: "recipe-search" });
  const button = element(document, "button", {
    class: "speech-button",
    "data-testid": "speech-button",
  });
  const icon = element(document, "span", { class: "speech-button__icon" });

  button.hidden = true;
  button.append(icon);
  label.append(input);
  wrapper.append(label, button);
  document.body.append(wrapper);

  return { wrapper, input, button };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  const document = createDocument();

  // The script reads the protocol of the page to decide whether the
  // dictation button is offered.
  globalThis.window = {
    location: { protocol: "http:" },
    setTimeout: () => 0,
    MediaRecorder: FakeMediaRecorder,
    RecipeIcons: {
      async loadSvgIcon(url) {
        return `<svg data-url="${url}"></svg>`;
      },
    },
  };
  globalThis.document = document;

  require(SPEECH_JS);

  // ----- Without HTTPS there is no dictation button ----- //
  const insecure = buildSearch(document);
  window.initializeSpeechInputs();

  assert.equal(
    insecure.wrapper.querySelector(".speech-button"),
    null,
    "the button is removed without HTTPS",
  );
  assert.equal(insecure.button.parentNode, null);

  // ----- Over HTTPS the button is offered ----- //
  window.location.protocol = "https:";

  const secure = buildSearch(document);
  window.initializeSpeechInputs();

  assert.notEqual(
    secure.wrapper.querySelector(".speech-button"),
    null,
    "the button is offered over HTTPS",
  );
  assert.equal(secure.button.hidden, false, "the button is revealed over HTTPS");
  assert.equal(secure.button.dataset.state, "idle");
  assert.equal(secure.button.getAttribute("aria-label"), "Start dictation");

  // ----- Dictating fills the search field ----- //
  const inputEvents = [];
  secure.input.addEventListener("input", () => inputEvents.push(secure.input.value));

  secure.button.click();
  await tick();
  assert.equal(secure.button.dataset.state, "recording");
  assert.equal(secure.button.getAttribute("aria-label"), "Stop dictation");
  assert.equal(recorded.length, 1);

  secure.button.click();
  await tick();
  await tick();

  assert.equal(fetchCalls.length, 1, "the recording is posted to the server");
  assert.equal(fetchCalls[0].url, "/api/transcribe");
  assert.equal(fetchCalls[0].options.method, "POST");
  assert.equal(fetchCalls[0].options.headers["Content-Type"], "audio/webm;codecs=opus");

  assert.equal(secure.input.value, "chocolate cake", "the transcript lands in the search field");
  assert.deepEqual(inputEvents, ["chocolate cake"], "the search filter is notified");
  assert.equal(secure.button.dataset.state, "complete");

  // ----- A refused transcription explains itself ----- //
  global.fetch = async () => ({
    ok: false,
    async json() {
      return { error: "Speech transcription requires an HTTPS connection" };
    },
  });

  secure.button.click();
  await tick();
  secure.button.click();
  await tick();
  await tick();

  assert.equal(secure.button.dataset.state, "error");
  assert.equal(secure.button.title, "Speech transcription requires an HTTPS connection");

  console.log("speech button checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
