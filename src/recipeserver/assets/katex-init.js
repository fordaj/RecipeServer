document.addEventListener("DOMContentLoaded", () => {
  if (typeof renderMathInElement !== "function") {
    console.warn("KaTeX auto-render hasn't loaded. Check script order.");
    return;
  }

  renderMathInElement(document.body, {
    delimiters: [
      { left: "\\(", right: "\\)", display: false },
      { left: "\\[", right: "\\]", display: true },
    ],
    ignoredClasses: ["quantity"],
    throwOnError: false,
  });
});
