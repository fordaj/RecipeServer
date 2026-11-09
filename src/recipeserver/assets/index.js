const initRecipeIndex = async () => {
  const list = document.querySelector("#recipe-list");
  if (!list) return;

  // ----- DOM References ----- //
  const recipes = [...list.querySelectorAll(".recipe")];
  const search = document.querySelector("#recipe-search");
  const filterControls = [
    ["meals", document.querySelector("#filter-meal")],
    ["cuisine", document.querySelector("#filter-cuisine")],
    ["status", document.querySelector("#filter-status")],
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
  const selectionMode = document.querySelector("#bulk-selection-mode");
  const showArchived = document.querySelector("#show-archived");
  const cardZoom = document.querySelector("#card-zoom");
  const bulkControls = document.querySelector("#bulk-controls");
  const bulkEdit = document.querySelector("#bulk-edit");
  const bulkDelete = document.querySelector("#bulk-delete");
  const clearSelections = document.querySelector("#clear-selections");
  const bulkCount = document.querySelector("#bulk-selection-count");
  const selectAll = document.querySelector("#select-all");
  const selectBoxes = [...document.querySelectorAll(".recipe-select__checkbox")];

  let selectionAnchor = null;

  // ----- Bulk Selection ----- //
  const getSelectedPaths = () =>
    selectBoxes.filter((box) => box.checked).map((box) => box.dataset.path);

  const visibleRecipes = () => recipes.filter((recipe) => !recipe.hidden);

  const applyMultiSelect = (targetRecipe, event) => {
    const visible = visibleRecipes();
    const targetIndex = visible.indexOf(targetRecipe);
    if (targetIndex < 0) return;

    const targetBox = targetRecipe.querySelector(".recipe-select__checkbox");
    if (!targetBox) return;

    // Range selection needs both keys (Ctrl/Cmd + Shift) like File
    // Explorer's additive range. Shift alone used to produce a native text
    // highlight, so it now falls through to a plain toggle below.
    const isRangeClick = event.shiftKey && (event.ctrlKey || event.metaKey);
    if (isRangeClick && selectionAnchor) {
      const anchorIndex = visible.indexOf(selectionAnchor);
      if (anchorIndex >= 0) {
        const start = Math.min(anchorIndex, targetIndex);
        const end = Math.max(anchorIndex, targetIndex);
        visible.slice(start, end + 1).forEach((recipe) => {
          const box = recipe.querySelector(".recipe-select__checkbox");
          if (box) box.checked = true;
        });
        updateBulkControls();
        return;
      }
    }

    // Plain click (and Ctrl/Cmd alone) toggles this card without clearing
    // others, so multiple recipes can be selected on mouse and touch.
    targetBox.checked = !targetBox.checked;
    selectionAnchor = targetRecipe;
    updateBulkControls();
  };

  const updateBulkControls = () => {
    const selected = getSelectedPaths();
    if (bulkCount) bulkCount.textContent = `${selected.length} selected`;
    if (bulkEdit) bulkEdit.disabled = selected.length === 0;
    if (bulkDelete) bulkDelete.disabled = selected.length === 0;
    for (const box of selectBoxes) {
      box.closest(".recipe")?.classList.toggle("is-selected", box.checked);
    }
    if (selectAll) {
      const visible = visibleRecipes();
      const selectedVisible = visible.filter(
        (recipe) => recipe.querySelector(".recipe-select__checkbox")?.checked,
      ).length;
      selectAll.checked = visible.length > 0 && selectedVisible === visible.length;
      selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
    }
  };

  const setSelectionMode = (enabled) => {
    list.classList.toggle("selection-mode", enabled);
    document.querySelectorAll(".recipe-select").forEach((label) => {
      label.hidden = !enabled;
    });
    if (bulkControls) bulkControls.hidden = !enabled;
    if (!enabled) {
      selectBoxes.forEach((box) => (box.checked = false));
      selectionAnchor = null;
    }
    updateBulkControls();
  };

  // ----- Filter and Sort Helpers ----- //
  const getDatasetValues = (recipe, datasetKey) =>
    JSON.parse(recipe.dataset[datasetKey] || "[]").map((value) => value.toLowerCase());

  const compareTitle = (leftRecipe, rightRecipe) =>
    leftRecipe.dataset.title.localeCompare(rightRecipe.dataset.title, undefined, {
      sensitivity: "base",
    });

  const compareByDateField = (datasetField, direction, leftRecipe, rightRecipe) => {
    const leftDateText = leftRecipe.dataset[datasetField] || null;
    const rightDateText = rightRecipe.dataset[datasetField] || null;

    if (leftDateText === null && rightDateText !== null) return 1;
    if (rightDateText === null && leftDateText !== null) return -1;

    if (leftDateText !== rightDateText) {
      const leftDate = new Date(leftDateText);
      const rightDate = new Date(rightDateText);
      if (Number.isNaN(leftDate) || Number.isNaN(rightDate)) {
        // Fallback to string comparison if dates are invalid
        return (direction === "desc" ? -1 : 1) * leftDateText.localeCompare(rightDateText);
      }
      return (direction === "desc" ? -1 : 1) * (leftDate - rightDate);
    }

    return compareTitle(leftRecipe, rightRecipe);
  };

  const compareByNumericField = (datasetField, direction, leftRecipe, rightRecipe) => {
    const leftValue =
      leftRecipe.dataset[datasetField] === "" ? null : Number(leftRecipe.dataset[datasetField]);
    const rightValue =
      rightRecipe.dataset[datasetField] === "" ? null : Number(rightRecipe.dataset[datasetField]);

    if (leftValue === null && rightValue !== null) return 1;
    if (rightValue === null && leftValue !== null) return -1;
    if (leftValue !== rightValue) {
      return (direction === "desc" ? -1 : 1) * (leftValue - rightValue);
    }
    return compareTitle(leftRecipe, rightRecipe);
  };

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

  // ----- Rating Warning Icon ----- //
  // The warning icon lives in assets/warning.svg; load it once and
  // inline it so it can inherit the chip's colour via currentColor.
  let ratingWarningIcon = "";
  try {
    const response = await fetch("/assets/warning.svg", { cache: "no-store" });
    if (response.ok) {
      const svg = new DOMParser().parseFromString(
        await response.text(),
        "image/svg+xml",
      ).documentElement;
      svg.setAttribute("class", "recipe-icon");
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      ratingWarningIcon = new XMLSerializer().serializeToString(svg);
    }
  } catch {
    ratingWarningIcon = "";
  }

  const ratingWarningMessage = (reviewers) => {
    if (!reviewers) return "Missing ratings";
    const names = reviewBoxes
      .filter((box) => box.checked)
      .map((box) => box.closest("label")?.querySelector("span")?.textContent.trim())
      .filter(Boolean);
    return names.length === 1 ? `No rating from ${names[0]}` : "No ratings from selected reviewers";
  };

  const ensureRatingWarning = (details) => {
    let warning = details.querySelector(".recipe-detail--rating.recipe-detail--warning");
    if (warning) return warning;

    warning = document.createElement("span");
    warning.className = "recipe-detail recipe-detail--rating recipe-detail--warning";
    warning.innerHTML =
      '<span class="recipe-detail__value"><span class="recipe-chip recipe-warning-chip">' +
      `${ratingWarningIcon} Ratings</span></span>`;
    details.prepend(warning);
    return warning;
  };

  const applyReviewFilter = (reviewers) => {
    if (!reviewFilter) return;
    for (const recipe of recipes) {
      const ratings = JSON.parse(recipe.dataset.ratings || "[]");
      const matching = reviewers ? ratings.filter((rating) => reviewers.has(rating.name)) : ratings;
      const details = recipe.querySelector(".recipe-card__details");
      const existing = details?.querySelector(".recipe-rating");
      const warning = details?.querySelector(".recipe-detail--rating.recipe-detail--warning");

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
        matching.reduce((total, rating) => total + Number(rating.rating), 0) / matching.length;

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

  // ----- Card Zoom ----- //
  // Size stores the minimum card width (px) used by the card-view
  // grid. Smaller cards show more recipes per row; larger cards show
  // fewer. The same value also scales list-view thumbnails (via
  // --list-thumb-size in index.css), so list-row height follows the
  // Image size indirectly. Persisted in localStorage so the
  // preference survives reloads and applies in both views.
  const CARD_ZOOM_STORAGE_KEY = "recipe-card-min-width";
  const CARD_ZOOM_MIN = 180;
  const CARD_ZOOM_MAX = 440;
  const CARD_ZOOM_DEFAULT = 280;

  const clampCardZoom = (value) => {
    if (!Number.isFinite(value)) return CARD_ZOOM_DEFAULT;
    return Math.min(CARD_ZOOM_MAX, Math.max(CARD_ZOOM_MIN, value));
  };

  const loadCardZoom = () => {
    try {
      const stored = Number(localStorage.getItem(CARD_ZOOM_STORAGE_KEY));
      if (Number.isFinite(stored) && stored >= CARD_ZOOM_MIN && stored <= CARD_ZOOM_MAX) {
        return stored;
      }
    } catch {
      // localStorage may be unavailable (e.g. private browsing).
    }
    return CARD_ZOOM_DEFAULT;
  };

  const applyCardZoom = (value) => {
    const zoom = clampCardZoom(value);
    list.style.setProperty("--card-min-width", `${zoom}px`);
    if (cardZoom) cardZoom.value = String(zoom);
    return zoom;
  };

  const saveCardZoom = (value) => {
    try {
      localStorage.setItem(CARD_ZOOM_STORAGE_KEY, String(clampCardZoom(value)));
    } catch {
      // Ignore storage errors; the in-page layout still updates.
    }
  };

  // The List/Cards view choice is persisted alongside the zoom value.
  const RECIPE_VIEW_STORAGE_KEY = "recipe-view";

  const loadRecipeView = () => {
    try {
      return localStorage.getItem(RECIPE_VIEW_STORAGE_KEY) === "cards" ? "cards" : "list";
    } catch {
      // localStorage may be unavailable (e.g. private browsing).
      return "list";
    }
  };

  const saveRecipeView = (view) => {
    try {
      localStorage.setItem(RECIPE_VIEW_STORAGE_KEY, view === "cards" ? "cards" : "list");
    } catch {
      // Ignore storage errors; the in-page layout still updates.
    }
  };

  // ----- Filter, Sort, and Render ----- //
  const isArchivedVisible = (recipe) =>
    !showArchived || showArchived.checked || recipe.dataset.archived !== "true";

  const getFilteredRecipes = (query) =>
    recipes.filter(
      (recipe) =>
        isArchivedVisible(recipe) &&
        recipe.dataset.search.toLowerCase().includes(query) &&
        filterControls.every(
          ([datasetKey, control]) =>
            !control.value || getDatasetValues(recipe, datasetKey).includes(control.value),
        ),
    );

  const sortVisibleRecipes = (visible, sortValue) => {
    const [sortKey, sortDirection] = sortValue.split(":");
    visible.sort((leftRecipe, rightRecipe) => {
      if (sortKey === "title") {
        return sortDirection === "desc"
          ? compareTitle(rightRecipe, leftRecipe)
          : compareTitle(leftRecipe, rightRecipe);
      }

      if (sortKey === "date" || sortKey === "edited") {
        return compareByDateField(sortKey, sortDirection, leftRecipe, rightRecipe);
      }

      return compareByNumericField(sortKey, sortDirection, leftRecipe, rightRecipe);
    });
  };

  const renderRecipeList = (visible, isFiltering) => {
    for (const recipe of visible) {
      list.appendChild(recipe);
      recipe.hidden = false;
    }

    for (const recipe of recipes) {
      if (!visible.includes(recipe)) recipe.hidden = true;
    }

    const total = recipes.filter(isArchivedVisible).length;
    count.textContent = `${visible.length} of ${total} recipes`;
    clearFilters.hidden = !isFiltering;
  };

  const update = () => {
    const query = search.value.trim().toLowerCase();
    const reviewers = getSelectedReviewers();
    applyReviewFilter(reviewers);
    updateReviewLabel(reviewers);

    const isFiltering =
      query !== "" ||
      reviewers !== null ||
      Boolean(showArchived?.checked) ||
      filterControls.some(([, control]) => control.value !== "");
    const visible = getFilteredRecipes(query);
    sortVisibleRecipes(visible, sort.value);
    renderRecipeList(visible, isFiltering);
    updateBulkControls();
  };

  // ----- Event Wiring ----- //
  [search, ...filterControls.map(([, control]) => control), sort].forEach((control) =>
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

  if (showArchived) {
    showArchived.addEventListener("change", update);
  }

  clearFilters.addEventListener("click", () => {
    search.value = "";
    filterControls.forEach(([, control]) => (control.value = ""));
    if (showArchived) showArchived.checked = false;
    if (reviewAll) reviewAll.checked = true;
    reviewBoxes.forEach((box) => (box.checked = false));
    update();
    search.focus();
  });

  metadataStatus.addEventListener("change", () => {
    document.querySelectorAll(".recipe-detail--warning").forEach((warning) => {
      warning.hidden = !metadataStatus.checked;
    });
    applyReviewFilter(getSelectedReviewers());
  });

  const setView = (view) => {
    const isCards = view === "cards";
    list.classList.toggle("list-view", !isCards);
    list.classList.toggle("card-view", isCards);
    viewButtons.forEach((item) => item.setAttribute("aria-pressed", item.dataset.view === view));
    saveRecipeView(isCards ? "cards" : "list");
  };

  viewButtons.forEach((button) =>
    button.addEventListener("click", () => setView(button.dataset.view)),
  );

  if (cardZoom) {
    cardZoom.addEventListener("input", () => {
      saveCardZoom(applyCardZoom(Number(cardZoom.value)));
    });
  }

  if (selectionMode) {
    selectionMode.addEventListener("change", () => setSelectionMode(selectionMode.checked));
  }
  // Prevent Shift+click from creating a native text selection. The
  // selection-mode CSS also disables user-select, but preventing the
  // mousedown default stops the browser forming the highlight at all.
  list.addEventListener("mousedown", (event) => {
    if (!selectionMode?.checked) return;
    if (event.shiftKey) event.preventDefault();
  });
  selectBoxes.forEach((box) => {
    box.addEventListener("click", (event) => {
      if (!selectionMode?.checked) return;
      event.preventDefault();
      const recipe = box.closest(".recipe");
      if (recipe) applyMultiSelect(recipe, event);
    });
  });
  // In selection mode, clicking the card selects it instead of navigating.
  list.addEventListener("click", (event) => {
    if (!selectionMode?.checked) return;
    const checkbox = event.target.closest(".recipe-select__checkbox");
    if (checkbox) return;
    const link = event.target.closest(".recipe-card__link, .recipe-card__image, .recipe-card");
    if (!link || !list.contains(link)) return;
    event.preventDefault();
    const recipe = link.closest(".recipe");
    if (recipe) applyMultiSelect(recipe, event);
  });
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      // Checking selects all in view; unchecking deselects all in view
      // (which is all recipes when nothing is filtered).
      visibleRecipes().forEach((recipe) => {
        const box = recipe.querySelector(".recipe-select__checkbox");
        if (box) box.checked = selectAll.checked;
      });
      if (selectAll.checked) {
        const visible = visibleRecipes();
        if (visible.length) selectionAnchor = visible[visible.length - 1];
      }
      updateBulkControls();
    });
  }
  if (clearSelections) {
    clearSelections.addEventListener("click", () => {
      selectBoxes.forEach((box) => (box.checked = false));
      selectionAnchor = null;
      updateBulkControls();
    });
  }
  if (bulkEdit) {
    bulkEdit.addEventListener("click", () => {
      const paths = getSelectedPaths();
      if (!paths.length) return;
      document.dispatchEvent(new CustomEvent("bulk-edit", { detail: { paths } }));
    });
  }
  if (bulkDelete) {
    bulkDelete.addEventListener("click", async () => {
      const paths = getSelectedPaths();
      if (!paths.length) return;
      if (
        !confirm(
          `Delete ${paths.length} selected recipe${paths.length === 1 ? "" : "s"}? This cannot be undone.`,
        )
      )
        return;
      bulkDelete.disabled = true;
      try {
        const response = await fetch(new URL("/api/bulk-delete", window.location.origin), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.success !== true) {
          throw new Error(result.error || `Request failed (HTTP ${response.status})`);
        }
        window.location.reload();
      } catch (error) {
        alert(error.message || "Unable to delete selected recipes.");
        updateBulkControls();
      }
    });
  }

  // ----- Initialization ----- //
  applyCardZoom(loadCardZoom());
  setView(loadRecipeView());
  setSelectionMode(Boolean(selectionMode?.checked));
  update();
};

document.addEventListener("DOMContentLoaded", () => {
  initRecipeIndex();
});
