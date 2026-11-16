"use strict";

// Shared helpers for the index-page DOM stub tests. The tests load the real
// assets into dom_stub.js so they can drive the page the way a browser would;
// these helpers keep the per-test scaffolding identical.

function element(document, tagName, attributes = {}) {
  const node = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

module.exports = { element, tick };
