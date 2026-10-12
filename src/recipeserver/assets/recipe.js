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
