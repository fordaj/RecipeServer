(() => {
  // Shared helper for fetching standalone .svg assets and inlining them so
  // they inherit the colour of the element they sit in through currentColor.
  // aria-hidden/focusable keep the icon out of the accessibility tree.

  const DEFAULT_ATTRIBUTES = {
    "aria-hidden": "true",
    focusable: "false",
  };

  // Returns the serialized SVG, or "" when the asset cannot be loaded, so
  // callers can fall back to rendering nothing.
  async function loadSvgIcon(url, attributes = {}) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return "";

      const svg = new DOMParser().parseFromString(
        await response.text(),
        "image/svg+xml",
      ).documentElement;
      for (const [name, value] of Object.entries({ ...DEFAULT_ATTRIBUTES, ...attributes })) {
        svg.setAttribute(name, value);
      }
      return new XMLSerializer().serializeToString(svg);
    } catch {
      return "";
    }
  }

  window.RecipeIcons = { loadSvgIcon };
})();
