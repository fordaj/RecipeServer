const initRecipeIndex = () => {
  {
    const list = document.querySelector("#recipe-list");
    if (!list) return;
    const recipes = [...list.querySelectorAll(".recipe")];
    const search = document.querySelector("#recipe-search");
    const filters = [
      ["meals", document.querySelector("#filter-meal")],
      ["cuisine", document.querySelector("#filter-cuisine")],
      ["categories", document.querySelector("#filter-category")],
      ["tags", document.querySelector("#filter-tag")],
      ["contributors", document.querySelector("#filter-contributor")],
      ["sourceTitles", document.querySelector("#filter-source-title")],
    ];
    const sort = document.querySelector("#sort-recipes");
    const count = document.querySelector("#recipe-count");
    const clearFilters = document.querySelector("#clear-filters");
    const viewButtons = [...document.querySelectorAll("[data-view]")];
    const metadataStatus = document.querySelector("#metadata-status");

    const getValues = (recipe, key) =>
      JSON.parse(recipe.dataset[key] || "[]").map((value) => value.toLowerCase());

    const compareTitle = (a, b) =>
      a.dataset.title.localeCompare(b.dataset.title, undefined, { sensitivity: "base" });

    const update = () => {
      {
        const query = search.value.trim().toLowerCase();
        const filtering = query !== "" || filters.some(([, control]) => control.value !== "");
        const visible = recipes.filter(
          (recipe) =>
            recipe.dataset.search.toLowerCase().includes(query) &&
            filters.every(
              ([key, control]) => !control.value || getValues(recipe, key).includes(control.value),
            ),
        );

        const [key, direction] = sort.value.split(":");
        visible.sort((a, b) => {
          {
            if (key === "title") {
              {
                return direction === "desc" ? compareTitle(b, a) : compareTitle(a, b);
              }
            }

            if (key === "date") {
              const aDate = a.dataset.date || null;
              const bDate = b.dataset.date || null;
              if (aDate === null && bDate !== null) return 1;
              if (bDate === null && aDate !== null) return -1;
              if (aDate !== bDate) {
                // For date comparison, we need to parse the dates properly
                const dateA = new Date(aDate);
                const dateB = new Date(bDate);
                if (isNaN(dateA) || isNaN(dateB)) {
                  // Fallback to string comparison if dates are invalid
                  return (direction === "desc" ? -1 : 1) * aDate.localeCompare(bDate);
                }
                return (direction === "desc" ? -1 : 1) * (dateA - dateB);
              }
              return compareTitle(a, b);
            } else if (key === "edited") {
              const aDate = a.dataset.edited || null;
              const bDate = b.dataset.edited || null;

              if (aDate === null && bDate !== null) return 1;
              if (bDate === null && aDate !== null) return -1;

              if (aDate !== bDate) {
                // For date comparison, we need to parse the dates properly
                const dateA = new Date(aDate);
                const dateB = new Date(bDate);
                if (isNaN(dateA) || isNaN(dateB)) {
                  // Fallback to string comparison if dates are invalid
                  return (direction === "desc" ? -1 : 1) * aDate.localeCompare(bDate);
                }
                return (direction === "desc" ? -1 : 1) * (dateA - dateB);
              }

              return compareTitle(a, b);
            }
            const aValue = a.dataset[key] === "" ? null : Number(a.dataset[key]);
            const bValue = b.dataset[key] === "" ? null : Number(b.dataset[key]);
            if (aValue === null && bValue !== null) return 1;
            if (bValue === null && aValue !== null) return -1;
            if (aValue !== bValue) {
              {
                return (direction === "desc" ? -1 : 1) * (aValue - bValue);
              }
            }
            return compareTitle(a, b);
          }
        });

        for (const recipe of visible) {
          {
            list.appendChild(recipe);
            recipe.hidden = false;
          }
        }

        for (const recipe of recipes) {
          {
            if (!visible.includes(recipe)) recipe.hidden = true;
          }
        }

        count.textContent = `${visible.length} of ${recipes.length} recipes`;
        clearFilters.hidden = !filtering;
      }
    };

    [search, ...filters.map(([, control]) => control), sort].forEach((control) =>
      control.addEventListener(control === search ? "input" : "change", update),
    );

    clearFilters.addEventListener("click", () => {
      {
        search.value = "";
        filters.forEach(([, control]) => (control.value = ""));
        update();
        search.focus();
      }
    });
    metadataStatus.addEventListener("change", () => {
      document.querySelectorAll(".recipe-detail--warning").forEach((warning) => {
        warning.hidden = !metadataStatus.checked;
      });
    });
    viewButtons.forEach((button) =>
      button.addEventListener("click", () => {
        {
          const view = button.dataset.view;
          list.classList.toggle("list-view", view === "list");
          list.classList.toggle("card-view", view === "cards");
          viewButtons.forEach((item) => item.setAttribute("aria-pressed", item === button));
        }
      }),
    );

    update();
  }
};

document.addEventListener("DOMContentLoaded", () => {
  initRecipeIndex();
});
