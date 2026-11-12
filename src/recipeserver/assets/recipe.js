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

// The sections of the recipe that can be collapsed by clicking their heading.
const collapsibleSections = [];

// The buttons that collapse or expand every section at once. Every section
// heading carries one, at the right of the heading.
const toggleAllButtons = [];

// The ratings, the comments, and the version line sit outside the sections of
// the recipe, so they stay visible when a section is collapsed.
const PAGE_EXTRAS = ".recipe-extras";

function allSectionsExpanded() {
  return collapsibleSections.every((section) => section.expanded);
}

// Keep the buttons in step with the sections they control.
function updateToggleState() {
  const expanded = allSectionsExpanded();
  const label = expanded ? "Collapse all sections" : "Expand all sections";

  toggleAllButtons.forEach((button) => {
    button.dataset.state = expanded ? "expanded" : "collapsed";

    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
  });
}

// Build the button that collapses or expands every section at once.
function buildToggleAllButton() {
  const button = document.createElement("button");

  button.className = "recipe-sections__toggle";
  button.setAttribute("type", "button");
  button.setAttribute("data-state", "expanded");
  button.setAttribute("aria-label", "Collapse all sections");
  button.setAttribute("title", "Collapse all sections");

  // The icon is a mask in the stylesheet, so it follows the color of the page.
  const icon = document.createElement("span");
  icon.className = "recipe-sections__icon";
  icon.setAttribute("aria-hidden", "true");

  button.append(icon);

  button.addEventListener("click", () => {
    const expand = !allSectionsExpanded();

    collapsibleSections.forEach((section) => section.setExpanded(expand));

    updateToggleState();
  });

  return button;
}

document.querySelectorAll("h2, h3, h4, h5, h6").forEach((heading) => {
  // Skip headings containing interactive controls.
  if (heading.querySelector("button, input, select, textarea")) return;

  const level = Number(heading.tagName[1]);
  const content = [];

  // Find all content belonging to this heading.
  let sibling = heading.nextElementSibling;

  while (sibling) {
    // The extras of the page are not part of the section.
    if (sibling.matches(PAGE_EXTRAS)) break;

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

  const section = { heading, content, expanded: true };

  // Show or hide the content of this section.
  const setExpanded = (expanded) => {
    section.expanded = expanded;

    heading.setAttribute("aria-expanded", String(expanded));

    content.forEach((element) => {
      element.hidden = !expanded;
    });

    updateToggleState();
  };

  section.setExpanded = setExpanded;

  // Mouse interaction.
  heading.addEventListener("click", (event) => {
    // Don't intercept interactive elements.
    if (event.target.closest("button, a, input, select, textarea")) return;

    setExpanded(!section.expanded);
  });

  // Keyboard interaction.
  heading.addEventListener("keydown", (event) => {
    // Don't intercept the keys of the button inside the heading.
    if (event.target.closest("button, a, input, select, textarea")) return;

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setExpanded(!section.expanded);
    }
  });

  // The button that collapses or expands every section sits at the right of
  // the heading, the way the collapser of the section sits at its left.
  const toggleAll = buildToggleAllButton();
  heading.append(toggleAll);
  toggleAllButtons.push(toggleAll);

  collapsibleSections.push(section);
});

updateToggleState();
