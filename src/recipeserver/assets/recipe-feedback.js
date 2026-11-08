(() => {
  // ----- Path helpers ----- //
  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  // ----- Identity helpers ----- //
  function createId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }

    // UUID v4 fallback for browsers or contexts without randomUUID().
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
      const random = (Math.random() * 16) | 0;
      const value = character === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }

  // ----- Name and date helpers ----- //
  function getInitials(name) {
    return String(name || "")
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase())
      .join("");
  }

  function formatDateText(timestamp) {
    if (typeof timestamp !== "string" || !timestamp) {
      return "";
    }

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
      return timestamp;
    }

    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  }

  function createDateElement(timestamp, className) {
    const dateElement = document.createElement("time");
    if (className) {
      dateElement.className = className;
    }
    if (typeof timestamp === "string" && timestamp) {
      dateElement.dateTime = timestamp;
      dateElement.textContent = formatDateText(timestamp);
    }
    return dateElement;
  }

  function sortByUpdatedDesc(items) {
    return [...items].sort((a, b) => {
      const timestampA = Date.parse((a && (a.updated || a.created)) || "") || 0;
      const timestampB = Date.parse((b && (b.updated || b.created)) || "") || 0;
      return timestampB - timestampA;
    });
  }

  // ----- Network helpers ----- //
  async function fetchMetadata(field, recipePath) {
    const params = new URLSearchParams({ path: recipePath });
    const response = await fetch(`/api/metadata/${field}?${params}`);

    if (!response.ok) {
      throw new Error(`Failed to load ${field} (HTTP ${response.status})`);
    }

    const data = await response.json();
    if (!Array.isArray(data.value)) {
      throw new Error(`Invalid ${field} response`);
    }

    return data.value;
  }

  async function saveMetadata(field, recipePath, value) {
    const response = await fetch(`/api/metadata/${field}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: recipePath, value }),
    });
    const result = await response.json().catch(() => ({}));

    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save ${field} (HTTP ${response.status})`);
    }
  }

  window.RecipeFeedback = {
    getMarkdownPath,
    createId,
    getInitials,
    formatDateText,
    createDateElement,
    sortByUpdatedDesc,
    fetchMetadata,
    saveMetadata,
  };
})();
