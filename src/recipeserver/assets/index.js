// Loaded before this file on the index page; destructured once so the
// external dependency is explicit.
const { RecipeIcons } = window;

// ----- Constants ----- //
// Card zoom stores the minimum card width (px) used by the card-view
// grid. Smaller cards show more recipes per row; larger cards show
// fewer. The same value also scales list-view thumbnails, via the
// --list-thumb-ratio custom property in index.css (--list-thumb-size is
// --card-min-width times that ratio), so list-row height follows the
// image size indirectly. Persisted in localStorage so the preference
// survives reloads and applies in both views.
const CARD_ZOOM_STORAGE_KEY = "recipe-card-min-width";
const CARD_ZOOM_MIN = 180;
const CARD_ZOOM_MAX = 440;
const CARD_ZOOM_DEFAULT = 280;

// The List/Cards view choice is persisted alongside the zoom value.
const RECIPE_VIEW_STORAGE_KEY = "recipe-view";

// Sort option values are "<field>:<direction>" (for example
// "edited:desc"), produced by _sort_control_html in index_html_generator.py
// and split on SORT_VALUE_DELIMITER here. The direction is "asc" or
// "desc"; any other direction sorts ascending.
const SORT_STORAGE_KEY = "recipe-sort";
const DEFAULT_SORT = "edited:desc";
const SORT_VALUE_DELIMITER = ":";
const SORT_DIRECTION_DESCENDING = "desc";

// A dropdown in a right-hand grid column can otherwise extend past the
// viewport on narrow screens. Right-align it only when it would cross
// the edge, keeping DROPDOWN_VIEWPORT_MARGIN_PX of breathing room. When
// neither innerWidth nor clientWidth is available, estimate the viewport
// as ending slightly past the fieldset's right edge so alignment still
// triggers.
const DROPDOWN_VIEWPORT_MARGIN_PX = 8;
const VIEWPORT_WIDTH_FALLBACK_PX = 16;

// ----- Shared Context ----- //
// DOM references and shared state travel in a single context object so
// the section functions below can stay independent. The generated index
// page (index_html_generator.py) always emits every element queried
// here; the only optional page is one without #recipe-list, which is
// how initRecipeIndex bails out on other pages.

// The metadata filter menus always carry a data-filter, a label, and an
// "All" option whose count sits next to its checkbox.
const collectFilterMenus = () =>
  [...document.querySelectorAll(".filter-menu[data-filter]")].map((menu) => ({
    menu,
    datasetKey: menu.dataset.filter,
    labelBase: menu.dataset.filterLabel || "",
    label: menu.querySelector(".filter-menu__label"),
    allBox: menu.querySelector(".filter-option-all"),
    allCount: menu.querySelector(".filter-menu__option--all .filter-menu__count"),
    boxes: [...menu.querySelectorAll(".filter-option")],
  }));

const createIndexContext = (list) => {
  const recipes = [...list.querySelectorAll(".recipe")];
  const filterMenus = collectFilterMenus();

  return {
    list,
    recipes,
    recipeFilterValues: buildRecipeFilterValues(recipes, filterMenus),
    filterMenus,
    allFilterMenus: [...document.querySelectorAll(".filter-menu")],
    search: document.querySelector("#recipe-search"),
    sort: document.querySelector("#sort-recipes"),
    count: document.querySelector("#recipe-count"),
    clearFilters: document.querySelector("#clear-filters"),
    viewButtons: [...document.querySelectorAll("[data-view]")],
    metadataStatus: document.querySelector("#metadata-status"),
    reviewAll: document.querySelector("#filter-reviews-all"),
    reviewBoxes: [...document.querySelectorAll(".filter-reviews")],
    reviewLabel: document.querySelector("#review-filter-label"),
    selectionToggle: document.querySelector("#bulk-selection-toggle"),
    selectionToggleLabel: document.querySelector("#bulk-selection-toggle [data-selection-label]"),
    selectionOnlyControls: [...document.querySelectorAll("#bulk-controls [data-selection-only]")],
    showArchived: document.querySelector("#show-archived"),
    cardZoom: document.querySelector("#card-zoom"),
    bulkControls: document.querySelector("#bulk-controls"),
    bulkEdit: document.querySelector("#bulk-edit"),
    shoppingList: document.querySelector("#shopping-list"),
    bulkDelete: document.querySelector("#bulk-delete"),
    clearSelections: document.querySelector("#clear-selections"),
    bulkCount: document.querySelector("#bulk-selection-count"),
    selectAll: document.querySelector("#select-all"),
    selectBoxes: [...document.querySelectorAll(".recipe-select__checkbox")],
    // Selection mode is driven by the Select/Cancel button in the bulk
    // controls bar, so the state lives here instead of on a checkbox.
    selectionAnchor: null,
    selectionModeEnabled: false,
    // Filled in once the warning icon asset has been inlined at start-up.
    ratingWarningIcon: "",
  };
};

// ----- Bulk Selection ----- //
const getSelectedPaths = (ctx) =>
  ctx.selectBoxes.filter((box) => box.checked).map((box) => box.dataset.path);

const visibleRecipes = (ctx) => ctx.recipes.filter((recipe) => !recipe.hidden);

const applyMultiSelect = (ctx, targetRecipe, event, checked) => {
  const visible = visibleRecipes(ctx);
  const targetIndex = visible.indexOf(targetRecipe);
  if (targetIndex < 0) return;

  const targetBox = targetRecipe.querySelector(".recipe-select__checkbox");
  if (!targetBox) return;

  // Range selection needs both keys (Ctrl/Cmd + Shift) like File
  // Explorer's additive range. Shift alone used to produce a native text
  // highlight, so it now falls through to a plain toggle below.
  const isRangeClick = event.shiftKey && (event.ctrlKey || event.metaKey);
  if (isRangeClick && ctx.selectionAnchor) {
    const anchorIndex = visible.indexOf(ctx.selectionAnchor);
    if (anchorIndex >= 0) {
      const start = Math.min(anchorIndex, targetIndex);
      const end = Math.max(anchorIndex, targetIndex);
      visible.slice(start, end + 1).forEach((recipe) => {
        const box = recipe.querySelector(".recipe-select__checkbox");
        if (box) box.checked = true;
      });
      updateBulkControls(ctx);
      return;
    }
  }

  // Plain click (and Ctrl/Cmd alone) toggles this card without clearing
  // others, so multiple recipes can be selected on mouse and touch. A
  // click on the checkbox itself already toggled it in the browser, so
  // that state is passed in instead of flipping the box a second time.
  targetBox.checked = checked ?? !targetBox.checked;
  ctx.selectionAnchor = targetRecipe;
  updateBulkControls(ctx);
};

const updateBulkControls = (ctx) => {
  const selected = getSelectedPaths(ctx);
  ctx.bulkCount.textContent = `${selected.length} selected`;
  ctx.bulkEdit.disabled = selected.length === 0;
  ctx.shoppingList.disabled = selected.length === 0;
  ctx.bulkDelete.disabled = selected.length === 0;
  for (const box of ctx.selectBoxes) {
    box.closest(".recipe")?.classList.toggle("is-selected", box.checked);
  }
  const visible = visibleRecipes(ctx);
  const selectedVisible = visible.filter(
    (recipe) => recipe.querySelector(".recipe-select__checkbox")?.checked,
  ).length;
  ctx.selectAll.checked = visible.length > 0 && selectedVisible === visible.length;
  ctx.selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
};

const setSelectionMode = (ctx, enabled) => {
  ctx.selectionModeEnabled = enabled;
  ctx.list.classList.toggle("selection-mode", enabled);
  document.querySelectorAll(".recipe-select").forEach((label) => {
    label.hidden = !enabled;
  });
  // The bulk controls bar is always visible because it holds the
  // Select/Cancel button; the bulk actions themselves only show up
  // while selection mode is on.
  ctx.bulkControls.classList.toggle("is-selection-mode", enabled);
  ctx.selectionOnlyControls.forEach((control) => {
    control.hidden = !enabled;
  });
  ctx.selectionToggleLabel.textContent = enabled ? "Cancel" : "Select";
  if (!enabled) {
    ctx.selectBoxes.forEach((box) => (box.checked = false));
    ctx.selectionAnchor = null;
  }
  updateBulkControls(ctx);
};

// ----- Filter and Sort Helpers ----- //
const getDatasetValues = (recipe, datasetKey) =>
  JSON.parse(recipe.dataset[datasetKey] || "[]").map((value) => value.toLowerCase());

// Index the filterable values once so every update and count pass can
// reuse them instead of parsing the data attributes repeatedly.
const buildRecipeFilterValues = (recipes, filterMenus) => {
  const datasetKeys = [...new Set(filterMenus.map((group) => group.datasetKey))];
  return new Map(
    recipes.map((recipe) => [
      recipe,
      Object.fromEntries(datasetKeys.map((key) => [key, new Set(getDatasetValues(recipe, key))])),
    ]),
  );
};

const getFilterSelection = (group) => {
  const selected = group.boxes.filter((box) => box.checked).map((box) => box.value);
  return selected.length ? new Set(selected) : null;
};

const getFilterSelections = (ctx) =>
  new Map(ctx.filterMenus.map((group) => [group, getFilterSelection(group)]));

const recipeMatchesQuery = (recipe, query) =>
  !query || recipe.dataset.search.toLowerCase().includes(query);

const recipeMatchesGroup = (ctx, recipe, group, selection) => {
  if (!selection) return true;
  const values = ctx.recipeFilterValues.get(recipe)?.[group.datasetKey];
  if (!values) return false;
  for (const value of selection) {
    if (values.has(value)) return true;
  }
  return false;
};

const recipeMatchesGroups = (ctx, recipe, groups, selections) =>
  groups.every((group) => recipeMatchesGroup(ctx, recipe, group, selections.get(group)));

const compareTitle = (leftRecipe, rightRecipe) =>
  leftRecipe.dataset.title.localeCompare(rightRecipe.dataset.title, undefined, {
    sensitivity: "base",
  });

// The date and numeric comparisons share this scaffold: missing values
// sort last, the direction picks ascending or descending, and equal
// values fall back to the title so the order stays stable. Only the
// value extraction and the value comparison differ between fields.
const compareFields = (extractValue, compareValues, direction, leftRecipe, rightRecipe) => {
  const leftValue = extractValue(leftRecipe);
  const rightValue = extractValue(rightRecipe);

  if (leftValue === null && rightValue !== null) return 1;
  if (rightValue === null && leftValue !== null) return -1;

  if (leftValue !== rightValue) {
    const descending = direction === SORT_DIRECTION_DESCENDING ? -1 : 1;
    return descending * compareValues(leftValue, rightValue);
  }

  return compareTitle(leftRecipe, rightRecipe);
};

const dateFieldValue = (datasetField) => (recipe) => recipe.dataset[datasetField] || null;

const compareDateValues = (leftText, rightText) => {
  const leftDate = new Date(leftText);
  const rightDate = new Date(rightText);
  if (Number.isNaN(leftDate) || Number.isNaN(rightDate)) {
    // Fall back to string comparison if the dates are invalid.
    return leftText.localeCompare(rightText);
  }
  return leftDate - rightDate;
};

const numericFieldValue = (datasetField) => (recipe) =>
  recipe.dataset[datasetField] === "" ? null : Number(recipe.dataset[datasetField]);

const compareNumericValues = (leftValue, rightValue) => leftValue - rightValue;

const getSelectedReviewers = (ctx) => {
  if (ctx.reviewAll.checked) return null;
  const selected = ctx.reviewBoxes.filter((box) => box.checked).map((box) => box.value);
  return selected.length ? new Set(selected) : null;
};

const updateReviewLabel = (ctx, reviewers) => {
  ctx.reviewLabel.textContent = reviewers
    ? `Filter Reviews: ${reviewers.size} selected`
    : "Filter Reviews: All";
};

// ----- Rating Warnings ----- //
// The rating summary for each recipe is either an average ("4.5/10"
// with its rating count) or a warning chip when no rating from the
// selected reviewers is available.
const parseRecipeRatings = (recipe) => JSON.parse(recipe.dataset.ratings || "[]");

const matchingRatings = (recipe, reviewers) => {
  const ratings = parseRecipeRatings(recipe);
  return reviewers ? ratings.filter((rating) => reviewers.has(rating.name)) : ratings;
};

const clearRecipeRating = (recipe) => {
  // A single place that marks a recipe as carrying no usable rating, so
  // the sort key never holds a stale value.
  recipe.dataset.rating = "";
};

const ratingWarningMessage = (ctx, reviewers) => {
  if (!reviewers) return "Missing ratings";
  const names = ctx.reviewBoxes
    .filter((box) => box.checked)
    .map((box) => box.closest("label")?.querySelector("span")?.textContent.trim())
    .filter(Boolean);
  return names.length === 1 ? `No rating from ${names[0]}` : "No ratings from selected reviewers";
};

const ensureRatingWarning = (ctx, details) => {
  let warning = details.querySelector(".recipe-detail--rating.recipe-detail--warning");
  if (warning) return warning;

  warning = document.createElement("span");
  warning.className = "recipe-detail recipe-detail--rating recipe-detail--warning";
  const value = document.createElement("span");
  value.className = "recipe-detail__value";
  const chip = document.createElement("span");
  chip.className = "recipe-chip recipe-warning-chip";
  // The icon is trusted same-origin markup from loadSvgIcon, and the
  // label is static text; reviewer names never reach innerHTML.
  chip.innerHTML = ctx.ratingWarningIcon ? `${ctx.ratingWarningIcon} Ratings` : "Ratings";
  value.append(chip);
  warning.append(value);
  details.prepend(warning);
  return warning;
};

const ensureRatingElement = (details) => {
  if (!details) return null;
  let rating = details.querySelector(".recipe-rating");
  if (rating) return rating;

  rating = document.createElement("span");
  rating.className = "recipe-rating";
  const star = document.createElement("span");
  star.className = "recipe-rating__star";
  star.setAttribute("aria-hidden", "true");
  star.textContent = "★";
  const score = document.createElement("span");
  score.className = "recipe-rating__score";
  const count = document.createElement("span");
  count.className = "recipe-rating__count";
  rating.append(star, score, count);
  details.prepend(rating);
  return rating;
};

const showMissingRating = (ctx, recipe, details, reviewers) => {
  const existing = details?.querySelector(".recipe-rating");
  if (existing) existing.hidden = true;

  const warning = details?.querySelector(".recipe-detail--rating.recipe-detail--warning");
  if (details && (warning || reviewers !== null)) {
    const ratingWarning = warning || ensureRatingWarning(ctx, details);
    const message = ratingWarningMessage(ctx, reviewers);
    ratingWarning.setAttribute("title", message);
    ratingWarning.setAttribute("aria-label", message);
    ratingWarning.hidden = !ctx.metadataStatus.checked;
  }
  clearRecipeRating(recipe);
};

const showAverageRating = (ctx, recipe, details, matching) => {
  const total = matching.reduce((sum, rating) => sum + Number(rating.rating), 0);
  const average = total / matching.length;

  const rating = ensureRatingElement(details);
  if (!rating) {
    clearRecipeRating(recipe);
    return;
  }

  const warning = details.querySelector(".recipe-detail--rating.recipe-detail--warning");
  if (warning) warning.hidden = true;
  rating.hidden = false;
  rating.setAttribute(
    "aria-label",
    `Rated ${average.toFixed(1)} out of 10 from ${matching.length} ratings`,
  );
  rating.querySelector(".recipe-rating__score").textContent = `${average.toFixed(1)}/10`;
  rating.querySelector(".recipe-rating__count").textContent = `(${matching.length})`;
  recipe.dataset.rating = String(average);
};

const applyReviewFilterToRecipe = (ctx, recipe, reviewers) => {
  const matching = matchingRatings(recipe, reviewers);
  const details = recipe.querySelector(".recipe-card__details");

  if (matching.length === 0) {
    showMissingRating(ctx, recipe, details, reviewers);
    return;
  }
  showAverageRating(ctx, recipe, details, matching);
};

const applyReviewFilter = (ctx, reviewers) => {
  for (const recipe of ctx.recipes) {
    applyReviewFilterToRecipe(ctx, recipe, reviewers);
  }
};

// ----- Card Zoom and View Persistence ----- //
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

const applyCardZoom = (ctx, value) => {
  const zoom = clampCardZoom(value);
  ctx.list.style.setProperty("--card-min-width", `${zoom}px`);
  ctx.cardZoom.value = String(zoom);
  return zoom;
};

const saveCardZoom = (value) => {
  try {
    localStorage.setItem(CARD_ZOOM_STORAGE_KEY, String(clampCardZoom(value)));
  } catch {
    // Ignore storage errors; the in-page layout still updates.
  }
};

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

const loadSort = (ctx) => {
  const options = Array.from(ctx.sort.options || []);
  try {
    const stored = localStorage.getItem(SORT_STORAGE_KEY);
    if (stored && options.some((option) => option.value === stored)) {
      return stored;
    }
  } catch {
    // localStorage may be unavailable (e.g. private browsing).
  }
  return options.some((option) => option.value === ctx.sort.value) ? ctx.sort.value : DEFAULT_SORT;
};

const saveSort = (value) => {
  try {
    localStorage.setItem(SORT_STORAGE_KEY, value);
  } catch {
    // Ignore storage errors; the in-page sort still updates.
  }
};

const setView = (ctx, view) => {
  const isCards = view === "cards";
  ctx.list.classList.toggle("list-view", !isCards);
  ctx.list.classList.toggle("card-view", isCards);
  ctx.viewButtons.forEach((item) => item.setAttribute("aria-pressed", item.dataset.view === view));
  saveRecipeView(isCards ? "cards" : "list");
};

// ----- Filter, Sort, and Render ----- //
const isArchivedVisible = (ctx, recipe) =>
  ctx.showArchived.checked || recipe.dataset.archived !== "true";

// Groups narrows which filter menus the recipe must match; the
// per-group count pass passes every menu except the group being counted
// so a group's own selection does not hide its other values.
const getFilteredRecipes = (ctx, query, selections, groups = ctx.filterMenus) =>
  ctx.recipes.filter(
    (recipe) =>
      isArchivedVisible(ctx, recipe) &&
      recipeMatchesQuery(recipe, query) &&
      recipeMatchesGroups(ctx, recipe, groups, selections),
  );

const updateFilterLabels = (ctx) => {
  for (const group of ctx.filterMenus) {
    const selected = group.boxes.filter((box) => box.checked).length;
    const state = selected ? `${selected} selected` : "All";
    group.label.textContent = `${group.labelBase}: ${state}`;
  }
};

// Tally how many matching recipes carry each value.
const countValues = (recipesToCount, valuesOf) => {
  const counts = new Map();
  for (const recipe of recipesToCount) {
    for (const value of valuesOf(recipe)) {
      counts.set(value, (counts.get(value) || 0) + 1);
    }
  }
  return counts;
};

// Render the per-option counts next to every checkbox and hide options
// that would match nothing. A checked option stays visible so the user
// can always uncheck it.
const updateOptionCounts = (boxes, counts) => {
  for (const box of boxes) {
    const option = box.closest(".filter-menu__option");
    const countValue = counts.get(box.value) || 0;
    const countElement = option?.querySelector(".filter-menu__count");
    if (countElement) countElement.textContent = String(countValue);
    if (option) option.hidden = countValue === 0 && !box.checked;
  }
};

// Each option shows how many recipes would match it. The counts ignore the
// group's own selection so the other values stay useful while several are
// picked, but they respect the search, archived toggle, and other filters.
const updateFilterCounts = (ctx, query, selections) => {
  for (const group of ctx.filterMenus) {
    const otherGroups = ctx.filterMenus.filter((item) => item !== group);
    const matching = getFilteredRecipes(ctx, query, selections, otherGroups);
    const counts = countValues(
      matching,
      (recipe) => ctx.recipeFilterValues.get(recipe)?.[group.datasetKey] ?? [],
    );
    updateOptionCounts(group.boxes, counts);
    group.allCount.textContent = String(matching.length);
  }

  // The review filter is separate from the metadata filter menus, but it
  // should also hide reviewers who match none of the currently visible
  // recipes.
  if (ctx.reviewBoxes.length) {
    const matching = getFilteredRecipes(ctx, query, selections);
    const counts = countValues(matching, (recipe) => JSON.parse(recipe.dataset.reviewers || "[]"));
    updateOptionCounts(ctx.reviewBoxes, counts);
    const reviewAllCount = ctx.reviewAll
      .closest(".filter-menu__option")
      ?.querySelector(".filter-menu__count");
    if (reviewAllCount) reviewAllCount.textContent = String(matching.length);
  }
};

const alignFilterMenu = (menu) => {
  const fieldset = menu.querySelector(".filter-menu__menu");
  if (!fieldset) return;
  fieldset.classList.remove("filter-menu__menu--right");
  if (!menu.open) return;

  const rect = fieldset.getBoundingClientRect();
  const viewportWidth =
    window.innerWidth ||
    document.documentElement?.clientWidth ||
    rect.right + VIEWPORT_WIDTH_FALLBACK_PX;
  if (rect.right > viewportWidth - DROPDOWN_VIEWPORT_MARGIN_PX) {
    fieldset.classList.add("filter-menu__menu--right");
  }
};

// sortValue is "<field>:<direction>" (see the SORT_* constants). The
// title field sorts by name; the date and edited fields sort by their
// date columns; everything else sorts numerically (rating, makes,
// difficulty).
const sortVisibleRecipes = (visible, sortValue) => {
  const [sortKey, sortDirection] = sortValue.split(SORT_VALUE_DELIMITER);
  visible.sort((leftRecipe, rightRecipe) => {
    if (sortKey === "title") {
      return sortDirection === SORT_DIRECTION_DESCENDING
        ? compareTitle(rightRecipe, leftRecipe)
        : compareTitle(leftRecipe, rightRecipe);
    }

    if (sortKey === "date" || sortKey === "edited") {
      return compareFields(
        dateFieldValue(sortKey),
        compareDateValues,
        sortDirection,
        leftRecipe,
        rightRecipe,
      );
    }

    return compareFields(
      numericFieldValue(sortKey),
      compareNumericValues,
      sortDirection,
      leftRecipe,
      rightRecipe,
    );
  });
};

const renderRecipeList = (ctx, visible, isFiltering) => {
  for (const recipe of visible) {
    ctx.list.appendChild(recipe);
    recipe.hidden = false;
  }

  for (const recipe of ctx.recipes) {
    if (!visible.includes(recipe)) recipe.hidden = true;
  }

  const total = ctx.recipes.filter((recipe) => isArchivedVisible(ctx, recipe)).length;
  ctx.count.textContent = `${visible.length} of ${total} recipes`;
  ctx.clearFilters.hidden = !isFiltering;
};

const update = (ctx) => {
  const query = ctx.search.value.trim().toLowerCase();
  const reviewers = getSelectedReviewers(ctx);
  applyReviewFilter(ctx, reviewers);
  updateReviewLabel(ctx, reviewers);

  const selections = getFilterSelections(ctx);
  const isFiltering =
    query !== "" ||
    reviewers !== null ||
    ctx.showArchived.checked ||
    [...selections.values()].some((selection) => selection !== null);
  updateFilterLabels(ctx);
  updateFilterCounts(ctx, query, selections);
  const visible = getFilteredRecipes(ctx, query, selections);
  sortVisibleRecipes(visible, ctx.sort.value);
  renderRecipeList(ctx, visible, isFiltering);
  updateBulkControls(ctx);
};

// ----- Event Wiring ----- //
const handleSortChange = (ctx) => {
  saveSort(ctx.sort.value);
  update(ctx);
};

// Checking any option unchecks the menu's "All" option; clearing every
// option restores it (an empty selection means "all"). Shared by the
// metadata filter menus and the review filter.
const syncAllCheckbox = (allBox, optionBoxes) => {
  allBox.checked = !optionBoxes.some((box) => box.checked);
};

const wireFilterMenus = (ctx) => {
  ctx.filterMenus.forEach((group) => {
    group.allBox.addEventListener("change", () => {
      if (group.allBox.checked) {
        group.boxes.forEach((box) => (box.checked = false));
      } else if (!group.boxes.some((box) => box.checked)) {
        // An empty selection means "all", so keep the All option in sync.
        group.allBox.checked = true;
      }
      update(ctx);
    });

    group.boxes.forEach((box) =>
      box.addEventListener("change", () => {
        syncAllCheckbox(group.allBox, group.boxes);
        update(ctx);
      }),
    );
  });
};

const wireReviewFilter = (ctx) => {
  ctx.reviewAll.addEventListener("change", () => {
    if (ctx.reviewAll.checked) {
      ctx.reviewBoxes.forEach((box) => (box.checked = false));
    }
    update(ctx);
  });

  ctx.reviewBoxes.forEach((box) =>
    box.addEventListener("change", () => {
      syncAllCheckbox(ctx.reviewAll, ctx.reviewBoxes);
      update(ctx);
    }),
  );
};

const wireFilterMenuAlignment = (ctx) => {
  for (const menu of ctx.allFilterMenus) {
    menu.addEventListener("toggle", () => alignFilterMenu(menu));
  }
  document.addEventListener("click", (event) => {
    for (const menu of ctx.allFilterMenus) {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    }
  });
  window.addEventListener?.("resize", () => {
    for (const menu of ctx.allFilterMenus) {
      if (menu.open) alignFilterMenu(menu);
    }
  });
};

const deleteSelectedRecipes = async (ctx) => {
  const paths = getSelectedPaths(ctx);
  if (!paths.length) return;
  if (
    !confirm(
      `Delete ${paths.length} selected recipe${paths.length === 1 ? "" : "s"}? This cannot be undone.`,
    )
  )
    return;
  ctx.bulkDelete.disabled = true;
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
    updateBulkControls(ctx);
  }
};

const wireSelectionMode = (ctx) => {
  ctx.selectionToggle.addEventListener("click", () =>
    setSelectionMode(ctx, !ctx.selectionModeEnabled),
  );

  // Prevent Shift+click from creating a native text selection. The
  // selection-mode CSS also disables user-select, but preventing the
  // mousedown default stops the browser forming the highlight at all.
  ctx.list.addEventListener("mousedown", (event) => {
    if (!ctx.selectionModeEnabled) return;
    if (event.shiftKey) event.preventDefault();
  });

  ctx.selectBoxes.forEach((box) => {
    box.addEventListener("click", (event) => {
      if (!ctx.selectionModeEnabled) return;
      // The browser has already toggled the checkbox. Cancelling the click
      // would undo that, so the new state is handed to the shared handler.
      const recipe = box.closest(".recipe");
      if (recipe) applyMultiSelect(ctx, recipe, event, box.checked);
    });
  });

  // In selection mode, clicking the card selects it instead of navigating.
  ctx.list.addEventListener("click", (event) => {
    if (!ctx.selectionModeEnabled) return;
    // The selection control has its own handler; clicking it must not
    // toggle the recipe a second time.
    const control = event.target.closest(".recipe-select");
    if (control) return;
    const link = event.target.closest(".recipe-card__link, .recipe-card__image, .recipe-card");
    if (!link || !ctx.list.contains(link)) return;
    event.preventDefault();
    const recipe = link.closest(".recipe");
    if (recipe) applyMultiSelect(ctx, recipe, event);
  });

  ctx.selectAll.addEventListener("change", () => {
    // Checking selects all in view; unchecking deselects all in view
    // (which is all recipes when nothing is filtered).
    visibleRecipes(ctx).forEach((recipe) => {
      const box = recipe.querySelector(".recipe-select__checkbox");
      if (box) box.checked = ctx.selectAll.checked;
    });
    if (ctx.selectAll.checked) {
      const visible = visibleRecipes(ctx);
      if (visible.length) ctx.selectionAnchor = visible[visible.length - 1];
    }
    updateBulkControls(ctx);
  });

  ctx.clearSelections.addEventListener("click", () => {
    ctx.selectBoxes.forEach((box) => (box.checked = false));
    ctx.selectionAnchor = null;
    updateBulkControls(ctx);
  });

  ctx.bulkEdit.addEventListener("click", () => {
    const paths = getSelectedPaths(ctx);
    if (!paths.length) return;
    document.dispatchEvent(new CustomEvent("bulk-edit", { detail: { paths } }));
  });

  ctx.shoppingList.addEventListener("click", () => {
    const paths = getSelectedPaths(ctx);
    if (!paths.length) return;
    document.dispatchEvent(new CustomEvent("shopping-list", { detail: { paths } }));
  });

  ctx.bulkDelete.addEventListener("click", () => deleteSelectedRecipes(ctx));
};

const wireEvents = (ctx) => {
  // Search filters on every keystroke; the sort select saves and re-renders.
  [
    [ctx.search, "input", update],
    [ctx.sort, "change", handleSortChange],
  ].forEach(([control, event, handler]) => {
    control.addEventListener(event, () => handler(ctx));
  });

  wireFilterMenus(ctx);
  wireReviewFilter(ctx);
  wireFilterMenuAlignment(ctx);

  ctx.showArchived.addEventListener("change", () => update(ctx));

  ctx.clearFilters.addEventListener("click", () => {
    ctx.search.value = "";
    ctx.filterMenus.forEach((group) => {
      group.boxes.forEach((box) => (box.checked = false));
      group.allBox.checked = true;
    });
    ctx.showArchived.checked = false;
    ctx.reviewAll.checked = true;
    ctx.reviewBoxes.forEach((box) => (box.checked = false));
    update(ctx);
    ctx.search.focus();
  });

  ctx.metadataStatus.addEventListener("change", () => {
    document.querySelectorAll(".recipe-detail--warning").forEach((warning) => {
      warning.hidden = !ctx.metadataStatus.checked;
    });
    applyReviewFilter(ctx, getSelectedReviewers(ctx));
  });

  ctx.viewButtons.forEach((button) =>
    button.addEventListener("click", () => setView(ctx, button.dataset.view)),
  );

  ctx.cardZoom.addEventListener("input", () => {
    saveCardZoom(applyCardZoom(ctx, Number(ctx.cardZoom.value)));
  });

  wireSelectionMode(ctx);
};

// ----- Entry Point ----- //
const initRecipeIndex = async () => {
  const list = document.querySelector("#recipe-list");
  if (!list) return;

  const ctx = createIndexContext(list);
  // The warning icon lives in assets/warning.svg; it is inlined so it can
  // inherit the chip's colour via currentColor.
  ctx.ratingWarningIcon = await RecipeIcons.loadSvgIcon("/assets/warning.svg", {
    class: "recipe-index__icon",
  });

  wireEvents(ctx);

  // ----- Initialization ----- //
  ctx.sort.value = loadSort(ctx);
  applyCardZoom(ctx, loadCardZoom());
  setView(ctx, loadRecipeView());
  setSelectionMode(ctx, false);
  update(ctx);
};

document.addEventListener("DOMContentLoaded", () => {
  initRecipeIndex();
});
