"use strict";

// A tiny DOM stub covering the subset of the browser API that the recipe
// page scripts use. It keeps the rating interactions testable without a
// browser or a headless DOM dependency.

function createStyle() {
  const properties = new Map();
  return {
    setProperty(name, value) {
      properties.set(name, String(value));
    },
    getPropertyValue(name) {
      return properties.get(name) ?? "";
    },
  };
}

function toDataAttribute(key) {
  return `data-${String(key).replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
}

function createDataset(element) {
  return new Proxy(
    {},
    {
      get(_target, key) {
        if (typeof key !== "string") return undefined;
        return element.getAttribute(toDataAttribute(key));
      },
      set(_target, key, value) {
        element.setAttribute(toDataAttribute(key), value);
        return true;
      },
    },
  );
}

class ClassList {
  constructor(element) {
    this.element = element;
  }

  get values() {
    return String(this.element.className || "")
      .split(/\s+/)
      .filter(Boolean);
  }

  contains(name) {
    return this.values.includes(name);
  }

  add(name) {
    if (!this.contains(name)) {
      this.element.className = [...this.values, name].join(" ");
    }
  }

  remove(name) {
    this.element.className = this.values.filter((value) => value !== name).join(" ");
  }

  toggle(name, force) {
    const next = force === undefined ? !this.contains(name) : Boolean(force);
    if (next) {
      this.add(name);
    } else {
      this.remove(name);
    }
    return next;
  }
}

class Element {
  constructor(tagName, ownerDocument) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDocument;
    this.parentNode = null;
    this.childNodes = [];
    this.attributes = new Map();
    this.dataset = createDataset(this);
    this.style = createStyle();
    this.listeners = new Map();
    this.classList = new ClassList(this);
    this.className = "";
    this.textContent = "";
    this.hidden = false;
    this.tabIndex = 0;
    this.type = "";
    this.value = "";
    this.defaultValue = "";
    this.validationMessage = "";
    this.selected = false;
    this.rect = {};
    this.capturedPointers = new Set();
  }

  get children() {
    return this.childNodes.filter((node) => node instanceof Element);
  }

  get nextElementSibling() {
    if (!this.parentNode) return null;
    const siblings = this.parentNode.children;
    const index = siblings.indexOf(this);
    if (index < 0 || index + 1 >= siblings.length) return null;
    return siblings[index + 1];
  }

  setAttribute(name, value) {
    const text = String(value);
    this.attributes.set(name, text);
    if (name === "class") {
      this.className = text;
    }
  }

  getAttribute(name) {
    if (name === "class") return this.className || null;
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  hasAttribute(name) {
    return this.getAttribute(name) !== null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  append(...nodes) {
    for (const node of nodes) {
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }

  appendChild(node) {
    // The browser moves an existing child instead of duplicating it.
    if (!this.childNodes.includes(node)) {
      node.parentNode = this;
      this.childNodes.push(node);
    }
    return node;
  }

  replaceChildren(...nodes) {
    this.childNodes = [];
    this.append(...nodes);
  }

  replaceWith(node) {
    const parent = this.parentNode;
    if (!parent) return;
    const index = parent.childNodes.indexOf(this);
    node.parentNode = parent;
    parent.childNodes[index] = node;
    this.parentNode = null;
  }

  remove() {
    const parent = this.parentNode;
    if (!parent) return;
    parent.childNodes.splice(parent.childNodes.indexOf(this), 1);
    this.parentNode = null;
  }

  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode;
    }
    return false;
  }

  matches(selector) {
    return matchesSelector(this, selector);
  }

  closest(selector) {
    let current = this;
    while (current) {
      if (matchesSelector(current, selector)) return current;
      current = current.parentNode;
    }
    return null;
  }

  querySelector(selector) {
    for (const node of descendants(this)) {
      if (matchesSelector(node, selector)) return node;
    }
    return null;
  }

  querySelectorAll(selector) {
    return descendants(this).filter((node) => matchesSelector(node, selector));
  }

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }

  dispatchEvent(event) {
    const payload = {
      preventDefault() {},
      stopPropagation() {
        payload.propagationStopped = true;
      },
      ...event,
    };
    if (payload.target === undefined) {
      payload.target = this;
    }

    let current = this;
    while (current) {
      payload.currentTarget = current;
      const handlers = current.listeners.get(payload.type) ?? [];
      for (const handler of handlers) handler.call(current, payload);
      if (payload.propagationStopped || payload.bubbles === false) break;
      current = current.parentNode;
    }
    return true;
  }

  click() {
    this.dispatchEvent({ type: "click", target: this });
  }

  focus() {
    this.ownerDocument.activeElement = this;
    this.dispatchEvent({ type: "focus", target: this, bubbles: false });
  }

  select() {
    this.selected = true;
  }

  setCustomValidity(message) {
    this.validationMessage = String(message ?? "");
  }

  reportValidity() {
    return true;
  }

  getBoundingClientRect() {
    const { left = 0, top = 0, width = 0, height = 0 } = this.rect;
    return { left, top, width, height, right: left + width, bottom: top + height };
  }

  setPointerCapture(pointerId) {
    this.capturedPointers.add(pointerId);
  }

  hasPointerCapture(pointerId) {
    return this.capturedPointers.has(pointerId);
  }

  releasePointerCapture(pointerId) {
    this.capturedPointers.delete(pointerId);
  }

  reset() {
    for (const node of descendants(this)) {
      if (node.tagName === "INPUT") {
        node.value = node.defaultValue;
      }
    }
  }
}

function descendants(element) {
  const found = [];
  for (const child of element.childNodes) {
    found.push(child);
    found.push(...descendants(child));
  }
  return found;
}

function matchesToken(element, token) {
  if (token.startsWith("#")) {
    return element.getAttribute("id") === token.slice(1);
  }
  if (token.startsWith(".")) {
    return element.classList.contains(token.slice(1));
  }
  if (token.startsWith("[")) {
    const body = token.slice(1, -1);
    const separator = body.indexOf("=");
    if (separator === -1) {
      return element.hasAttribute(body);
    }
    const name = body.slice(0, separator);
    const value = body.slice(separator + 1).replace(/^["']|["']$/g, "");
    return element.getAttribute(name) === value;
  }
  return element.tagName === token.toUpperCase();
}

function matchesSelector(element, selector) {
  return splitTopLevel(String(selector), ",").some((part) => matchesComplex(element, part.trim()));
}

function splitTopLevel(text, separator) {
  const parts = [];
  let current = "";
  let depth = 0;
  for (const character of text) {
    if (character === "[") depth += 1;
    if (character === "]") depth -= 1;
    if (depth === 0 && character === separator) {
      parts.push(current);
      current = "";
      continue;
    }
    current += character;
  }
  parts.push(current);
  return parts;
}

function matchesComplex(element, complex) {
  const parts = splitTopLevel(complex, " ").filter((part) => part.trim().length > 0);
  if (parts.length === 0) return false;
  return matchesParts(element, parts);
}

function matchesParts(element, parts) {
  if (!matchesCompound(element, parts[parts.length - 1])) return false;
  if (parts.length === 1) return true;

  let current = element.parentNode;
  while (current) {
    if (matchesParts(current, parts.slice(0, -1))) return true;
    current = current.parentNode;
  }
  return false;
}

function matchesCompound(element, compound) {
  const tokens = [];
  let index = 0;
  while (index < compound.length) {
    if (compound[index] === "[") {
      const end = compound.indexOf("]", index);
      tokens.push(compound.slice(index, end + 1));
      index = end + 1;
      continue;
    }
    let end = index;
    if (compound[end] === "#" || compound[end] === ".") end += 1;
    while (end < compound.length && !" \t\n.#[]".includes(compound[end])) end += 1;
    if (end === index) end += 1;
    tokens.push(compound.slice(index, end));
    index = end;
  }
  return tokens.length > 0 && tokens.every((token) => matchesToken(element, token));
}

function createDocument() {
  const document = {
    activeElement: null,
    listeners: new Map(),
    createElement(tagName) {
      return new Element(tagName, document);
    },
    querySelector(selector) {
      return document.documentElement.querySelector(selector);
    },
    querySelectorAll(selector) {
      return document.documentElement.querySelectorAll(selector);
    },
    addEventListener(type, handler) {
      if (!document.listeners.has(type)) document.listeners.set(type, []);
      document.listeners.get(type).push(handler);
    },
    dispatchEvent(event) {
      const handlers = document.listeners.get(event.type) ?? [];
      const payload = { ...event, target: event.target ?? document };
      for (const handler of handlers) handler(payload);
      return true;
    },
  };

  document.documentElement = new Element("html", document);
  document.body = new Element("body", document);
  document.documentElement.append(document.body);

  return document;
}

module.exports = { Element, createDocument };
