"use strict";

// The shared microphone/transcription transport used by the search button and
// the assistant composer.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DICTATION_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "dictation.js");
const API_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "api.js");

class FakeRecorder {
  static isTypeSupported(type) {
    return type === "audio/webm;codecs=opus";
  }

  constructor(stream, options = {}) {
    this.stream = stream;
    this.mimeType = options.mimeType || "audio/webm";
    this.state = "inactive";
    FakeRecorder.instances.push(this);
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: { size: 4 } });
    this.onstop?.();
  }
}
FakeRecorder.instances = [];

const stoppedTracks = [];
global.MediaRecorder = FakeRecorder;
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    mediaDevices: {
      async getUserMedia() {
        return { getTracks: () => [{ stop() { stoppedTracks.push(true); } }] };
      },
    },
  },
});
global.window = {
  location: { protocol: "https:" },
  MediaRecorder: FakeRecorder,
  setTimeout: () => 1,
  clearTimeout: () => {},
};
global.fetch = async () => ({ ok: true, json: async () => ({ text: "Add flour." }) });

require(API_JS);
vm.runInThisContext(fs.readFileSync(DICTATION_JS, "utf8"), { filename: DICTATION_JS });
const dictation = global.window.RecipeDictation;

async function main() {
  assert.equal(dictation.isSecurePage(), true);
  assert.equal(dictation.canRecord(), true);
  assert.equal(dictation.supportedMimeType(), "audio/webm;codecs=opus");
  assert.equal(dictation.LONG_PRESS_MS, 450);

  let stopped = null;
  const recorder = dictation.createRecorder({ onStop: (blob) => (stopped = blob) });
  assert.equal(await recorder.start(), true);
  assert.equal(recorder.isRecording(), true);
  recorder.stop();
  assert.equal(recorder.isRecording(), false);
  assert.ok(stopped, "the recorded blob is handed to onStop");
  assert.equal(stoppedTracks.length, 1, "the microphone is released on stop");

  const cancelled = dictation.createRecorder({ onStop: () => { throw new Error("must not fire"); } });
  assert.equal(await cancelled.start(), true);
  cancelled.cancel();
  assert.equal(cancelled.isRecording(), false);

  const blob = { size: 4, type: "audio/webm" };
  assert.equal(await dictation.transcribe(blob), "Add flour.");
  assert.equal(await dictation.transcribe(blob, { stripTrailingPeriod: true }), "Add flour");
  await assert.rejects(() => dictation.transcribe({ size: 0 }), /Nothing was heard/);

  console.log("dictation checks passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
