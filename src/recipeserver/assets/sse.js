// Shared Server-Sent Events reader for the AI progress stream and the chat.
//
// The server emits both an `event:` line and a `type` field in the JSON `data:`
// line. Reading either one alone made the two consumers disagree: one ignored
// the frame name, the other dropped an unterminated final frame. This module
// owns the wire format; callers only decide what each event means.

(function () {
  "use strict";

  function parseEventBlock(block) {
    let eventName = "";
    const dataLines = [];

    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }

    if (!dataLines.length) {
      return null;
    }

    let data;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return null;
    }
    if (!data || typeof data !== "object") {
      return null;
    }

    // The frame name is authoritative; the JSON field is a fallback for
    // streams that only carry data lines.
    return { ...data, type: eventName || (typeof data.type === "string" ? data.type : "message") };
  }

  async function readEventStream(body, onEvent) {
    if (!body) {
      throw new Error("The AI progress stream is unavailable.");
    }

    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });

      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const event = parseEventBlock(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (event) {
          await onEvent(event);
        }
      }

      if (done) {
        break;
      }
    }

    // Flush a partial multibyte character and any final frame that arrived
    // without a trailing blank line.
    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = parseEventBlock(buffer);
      if (event) {
        await onEvent(event);
      }
    }
  }

  window.RecipeSSE = { parseEventBlock, readEventStream };
})();
