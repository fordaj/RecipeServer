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
    const reviewFilter = document.querySelector("#review-filter");
    const reviewAll = document.querySelector("#filter-reviews-all");
    const reviewBoxes = [...document.querySelectorAll(".filter-reviews")];
    const reviewLabel = document.querySelector("#review-filter-label");

    const getValues = (recipe, key) =>
      JSON.parse(recipe.dataset[key] || "[]").map((value) => value.toLowerCase());

    const compareTitle = (a, b) =>
      a.dataset.title.localeCompare(b.dataset.title, undefined, { sensitivity: "base" });

    const getSelectedReviewers = () => {
      if (!reviewAll || reviewAll.checked) return null;
      const selected = reviewBoxes.filter((box) => box.checked).map((box) => box.value);
      return selected.length ? new Set(selected) : null;
    };

    const updateReviewLabel = (reviewers) => {
      if (!reviewLabel) return;
      reviewLabel.textContent = reviewers
        ? `Filter Reviews: ${reviewers.size} selected`
        : "Filter Reviews: All";
    };

    const RATING_WARNING_ICON =
      '<svg aria-hidden="true" class="recipe-icon" fill="none" focusable="false" height="24" ' +
      'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" ' +
      'viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>' +
      '<path d="M12 9v4"/><path d="M12 17h.01"/></svg>';

    const ratingWarningMessage = (reviewers) => {
      if (!reviewers) return "Missing ratings";
      const names = reviewBoxes
        .filter((box) => box.checked)
        .map((box) => box.closest("label")?.querySelector("span")?.textContent.trim())
        .filter(Boolean);
      return names.length === 1
        ? `No rating from ${names[0]}`
        : "No ratings from selected reviewers";
    };

    const ensureRatingWarning = (details) => {
      let warning = details.querySelector(".recipe-detail--rating.recipe-detail--warning");
      if (warning) return warning;

      warning = document.createElement("span");
      warning.className = "recipe-detail recipe-detail--rating recipe-detail--warning";
      warning.innerHTML =
        '<span class="recipe-detail__value"><span class="recipe-chip recipe-warning-chip">' +
        `${RATING_WARNING_ICON} Ratings</span></span>`;
      details.prepend(warning);
      return warning;
    };

    const applyReviewFilter = (reviewers) => {
      if (!reviewFilter) return;
      for (const recipe of recipes) {
        const ratings = JSON.parse(recipe.dataset.ratings || "[]");
        const matching = reviewers
          ? ratings.filter((rating) => reviewers.has(rating.name))
          : ratings;
        const details = recipe.querySelector(".recipe-card__details");
        const existing = details?.querySelector(".recipe-rating");
        const warning = details?.querySelector(
          ".recipe-detail--rating.recipe-detail--warning",
        );

        if (matching.length === 0) {
          if (existing) existing.hidden = true;
          recipe.dataset.rating = "";

          if (details && (warning || reviewers !== null)) {
            const ratingWarning = warning || ensureRatingWarning(details);
            const message = ratingWarningMessage(reviewers);
            ratingWarning.setAttribute("title", message);
            ratingWarning.setAttribute("aria-label", message);
            ratingWarning.hidden = !metadataStatus?.checked;
          }
          continue;
        }

        const average =
          matching.reduce((total, rating) => total + Number(rating.rating), 0) /
          matching.length;

        let rating = existing;
        if (!rating && details) {
          rating = document.createElement("span");
          rating.className = "recipe-rating";
          rating.innerHTML =
            '<span class="recipe-rating__star" aria-hidden="true">★</span>' +
            '<span class="recipe-rating__score"></span>' +
            '<span class="recipe-rating__count"></span>';
          details.prepend(rating);
        }

        if (!rating) {
          recipe.dataset.rating = "";
          continue;
        }

        if (warning) warning.hidden = true;
        rating.hidden = false;
        rating.setAttribute(
          "aria-label",
          `Rated ${average.toFixed(1)} out of 10 from ${matching.length} ratings`,
        );
        rating.querySelector(".recipe-rating__score").textContent = `${average.toFixed(1)}/10`;
        rating.querySelector(".recipe-rating__count").textContent = `(${matching.length})`;
        recipe.dataset.rating = String(average);
      }
    };

    const update = () => {
      {
        const query = search.value.trim().toLowerCase();
        const reviewers = getSelectedReviewers();
        applyReviewFilter(reviewers);
        updateReviewLabel(reviewers);

        const filtering =
          query !== "" ||
          reviewers !== null ||
          filters.some(([, control]) => control.value !== "");
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

    if (reviewAll) {
      reviewAll.addEventListener("change", () => {
        if (reviewAll.checked) {
          reviewBoxes.forEach((box) => (box.checked = false));
        }
        update();
      });
    }

    reviewBoxes.forEach((box) =>
      box.addEventListener("change", () => {
        if (box.checked && reviewAll) reviewAll.checked = false;
        if (reviewAll && !reviewBoxes.some((item) => item.checked)) reviewAll.checked = true;
        update();
      }),
    );

    if (reviewFilter) {
      document.addEventListener("click", (event) => {
        if (reviewFilter.open && !reviewFilter.contains(event.target)) {
          reviewFilter.open = false;
        }
      });
    }

    clearFilters.addEventListener("click", () => {
      {
        search.value = "";
        filters.forEach(([, control]) => (control.value = ""));
        if (reviewAll) reviewAll.checked = true;
        reviewBoxes.forEach((box) => (box.checked = false));
        update();
        search.focus();
      }
    });
    metadataStatus.addEventListener("change", () => {
      document.querySelectorAll(".recipe-detail--warning").forEach((warning) => {
        warning.hidden = !metadataStatus.checked;
      });
      applyReviewFilter(getSelectedReviewers());
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
