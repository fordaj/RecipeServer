// Make checkbox li's clickable for checking and unchecking each line
document.querySelectorAll(".recipe li:has(input[type='checkbox'])").forEach((li) => {
  const checkbox = li.querySelector("input[type='checkbox']");

  li.style.cursor = "pointer";

  li.addEventListener("click", (event) => {
    // Let direct checkbox clicks work normally.
    if (event.target === checkbox) return;

    // Don't interfere with links or other interactive elements.
    if (event.target.closest("a, button, select, textarea, input")) return;

    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
  });
});

document.querySelectorAll("h2, h3, h4, h5, h6").forEach((heading) => {
  // Skip headings containing interactive controls.
  if (heading.querySelector("button, input, select, textarea")) return;

  const level = Number(heading.tagName[1]);
  const content = [];

  // Find all content belonging to this heading.
  let sibling = heading.nextElementSibling;

  while (sibling) {
    const siblingLevel = /^H[1-6]$/.test(sibling.tagName) ? Number(sibling.tagName[1]) : Infinity;

    // Stop at the next heading of equal or higher level.
    if (siblingLevel <= level) break;

    content.push(sibling);
    sibling = sibling.nextElementSibling;
  }

  // Nothing to collapse.
  if (!content.length) return;

  // Configure heading.
  heading.classList.add("collapsible-heading");
  heading.setAttribute("aria-expanded", "true");
  heading.setAttribute("role", "button");
  heading.tabIndex = 0;

  // Toggle section visibility.
  const toggle = () => {
    const expanded = heading.getAttribute("aria-expanded") === "true";

    heading.setAttribute("aria-expanded", String(!expanded));

    content.forEach((element) => {
      element.hidden = expanded;
    });
  };

  // Mouse interaction.
  heading.addEventListener("click", (event) => {
    // Don't intercept interactive elements.
    if (event.target.closest("button, a, input, select, textarea")) return;

    toggle();
  });

  // Keyboard interaction.
  heading.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle();
    }
  });
});
