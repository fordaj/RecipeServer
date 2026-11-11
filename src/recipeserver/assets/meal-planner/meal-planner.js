(() => {
  const MEAL_PLANNER_ID = "meal-planner-dialog";
  const MEAL_PLANNER_ASSETS = "/assets/meal-planner";
  const MEAL_PLANNER_API = "/api/meal-planner";
  const RECIPE_SCALER_URL = "/assets/recipe-scaler.html";
  const KATEX_CSS_URL = "/assets/katex/dist/katex.min.css";
  const KATEX_JS_URL = "/assets/katex/dist/katex.min.js";

  let dialog = null;
  let state = null;
  let scalerMarkup = "";
  let katexPromise = null;
  let loading = false;

  // ----- Markup and assets ----- //

  async function fetchTemplate(name) {
    const response = await fetch(`${MEAL_PLANNER_ASSETS}/${name}.html`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load meal planner template: ${name} (HTTP ${response.status})`);
    }
    return response.text();
  }

  async function createDialog() {
    const element = document.createElement("dialog");
    element.id = MEAL_PLANNER_ID;
    element.className = "meal-planner-dialog";
    element.innerHTML = await fetchTemplate("meal-planner");
    document.body.append(element);
    return element;
  }

  async function loadScalerMarkup() {
    if (scalerMarkup) return scalerMarkup;

    const response = await fetch(RECIPE_SCALER_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load the recipe scaler (HTTP ${response.status})`);
    }

    scalerMarkup = await response.text();
    return scalerMarkup;
  }

  // KaTeX is only needed once the planner opens, so it is loaded on demand
  // instead of on every index page view.
  function loadKatex() {
    if (typeof window.katex?.render === "function") return Promise.resolve();
    if (katexPromise) return katexPromise;

    katexPromise = new Promise((resolve, reject) => {
      if (!document.querySelector(`link[href="${KATEX_CSS_URL}"]`)) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = KATEX_CSS_URL;
        document.head.append(link);
      }

      const existing = document.querySelector(`script[src="${KATEX_JS_URL}"]`);
      const script = existing ?? document.createElement("script");

      script.addEventListener("load", () => resolve());
      script.addEventListener("error", () => reject(new Error("Unable to load KaTeX")));

      if (!existing) {
        script.src = KATEX_JS_URL;
        document.head.append(script);
      }
    });

    return katexPromise;
  }

  // ----- API ----- //

  async function requestIngredients(paths) {
    const url = new URL(MEAL_PLANNER_API, window.location.origin);
    for (const path of paths) url.searchParams.append("path", path);

    const response = await fetch(url, { cache: "no-store" });
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }

    return result;
  }

  // ----- State ----- //

  function createState(element) {
    return {
      dialog: element,
      status: element.querySelector(".meal-planner__status"),
      recipes: element.querySelector(".meal-planner__recipes"),
      list: element.querySelector(".meal-planner__ingredients"),
      rows: [],
      plans: [],
      ready: false,
    };
  }

  function setStatus(message) {
    if (state?.status) state.status.textContent = message;
  }

  // ----- Recipe details ----- //

  function findRecipeCard(path) {
    for (const card of document.querySelectorAll("#recipe-list .recipe")) {
      if (card.dataset.path === path) return card;
    }
    return null;
  }

  function recipeDetails(path) {
    const card = findRecipeCard(path);
    const fallback = path.replace(/\.md$/i, "").split("/").pop();

    return {
      path,
      title: card?.dataset.title || fallback,
      image: card?.querySelector(".recipe-card__image img")?.getAttribute("src") || "",
    };
  }

  // ----- Ingredient markup ----- //

  // The plain text of an ingredient, with the scaled amount in place of the
  // quantity span the recipe scaler renders with KaTeX.
  function ingredientText(item) {
    const clone = item.cloneNode(true);

    clone.querySelectorAll('input[type="checkbox"]').forEach((input) => input.remove());
    clone.querySelectorAll(".quantity").forEach((quantity) => {
      const text = quantity.dataset.scaledText ?? quantity.textContent;
      quantity.replaceWith(document.createTextNode(text));
    });

    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  function buildChecklistItem(source) {
    const item = document.createElement("li");
    item.className = "task-list-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";

    const content = document.createElement("span");
    content.className = "meal-planner__ingredient";
    content.innerHTML = source.innerHTML;
    content.querySelectorAll('input[type="checkbox"]').forEach((input) => input.remove());

    item.append(checkbox, document.createTextNode(" "), content);
    return item;
  }

  // ----- Rendering ----- //

  function buildRow(recipe, ingredients) {
    const row = document.createElement("div");
    row.className = "meal-planner__recipe";

    const scaler = document.createElement("div");
    scaler.className = "meal-planner__scaler";
    scaler.innerHTML = scalerMarkup;

    const image = document.createElement(recipe.image ? "img" : "span");
    image.className = "meal-planner__image";
    if (recipe.image) {
      image.src = recipe.image;
      image.alt = "";
      image.loading = "lazy";
    } else {
      // Keep the row aligned when the recipe has no image.
      image.classList.add("meal-planner__image--empty");
      image.setAttribute("aria-hidden", "true");
    }

    const details = document.createElement("div");
    details.className = "meal-planner__details";

    const name = document.createElement("h4");
    name.className = "meal-planner__name";
    name.textContent = recipe.title;

    const list = document.createElement("ul");
    list.className = "meal-planner__recipe-ingredients";

    for (const markup of ingredients) {
      const item = document.createElement("li");
      item.innerHTML = markup;
      // The combined list is the checklist. The per-recipe lists only
      // show the amounts, so their checkboxes are dropped.
      item.querySelectorAll('input[type="checkbox"]').forEach((input) => input.remove());
      list.append(item);
    }

    if (!list.childElementCount) {
      const empty = document.createElement("li");
      empty.className = "meal-planner__no-ingredients";
      empty.textContent = "No ingredients found.";
      list.append(empty);
    }

    details.append(name, list);
    row.append(scaler, image, details);
    return row;
  }

  function renderCombined() {
    if (!state?.ready) return;

    // Keep the ticked items ticked when a scale change re-renders the list.
    const ticked = new Set();
    for (const item of state.list.querySelectorAll(".task-list-item")) {
      if (item.querySelector('input[type="checkbox"]')?.checked) ticked.add(ingredientText(item));
    }

    const entries = [];
    for (const row of state.rows) {
      for (const item of row.querySelectorAll(".meal-planner__recipe-ingredients > li")) {
        // The placeholder for a recipe without ingredients is not an ingredient.
        if (item.classList.contains("meal-planner__no-ingredients")) continue;
        entries.push({ text: ingredientText(item), item });
      }
    }

    entries.sort((left, right) =>
      left.text.localeCompare(right.text, undefined, { sensitivity: "base" }),
    );

    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      fragment.append(buildChecklistItem(entry.item));
    }
    state.list.replaceChildren(fragment);

    for (const item of state.list.querySelectorAll(".task-list-item")) {
      const checkbox = item.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.checked = ticked.has(ingredientText(item));
    }

    if (!state.list.childElementCount) {
      const empty = document.createElement("li");
      empty.className = "meal-planner__no-ingredients";
      empty.textContent = "No ingredients found.";
      state.list.append(empty);
    }
  }

  // ----- Checklist export ----- //

  function buildChecklistMarkdown() {
    const lines = ["# Meal Plan", "", "## Recipes", ""];

    for (const plan of state.plans) {
      lines.push(`- ${plan.title}`);
    }

    lines.push("", "## Combined Ingredients", "");

    for (const item of state.list.querySelectorAll(".task-list-item")) {
      const checked = item.querySelector('input[type="checkbox"]')?.checked ? "x" : " ";
      lines.push(`- [${checked}] ${ingredientText(item)}`);
    }

    return `${lines.join("\n")}\n`;
  }

  function downloadChecklist() {
    const blob = new Blob([buildChecklistMarkdown()], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "meal-plan.md";
    document.body.append(link);
    link.click();
    link.remove();

    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ----- Dialog wiring ----- //

  function registerDialogListeners(element) {
    element.querySelector(".meal-planner__close")?.addEventListener("click", () => element.close());

    element.querySelector(".meal-planner__print")?.addEventListener("click", () => window.print());

    // The dialog form closes the planner; the checklist is downloaded first.
    element
      .querySelector("form.meal-planner")
      ?.addEventListener("submit", () => downloadChecklist());

    let pointerDownTarget = null;
    element.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });
    element.addEventListener("click", (event) => {
      if (event.target === element && pointerDownTarget === element) element.close();
      pointerDownTarget = null;
    });

    element.addEventListener("close", () => {
      state.ready = false;
      state.rows = [];
      state.plans = [];
      state.recipes.replaceChildren();
      state.list.replaceChildren();
    });
  }

  // ----- Opening ----- //

  async function openMealPlanner(paths) {
    if (!paths?.length || loading) return;
    loading = true;

    try {
      if (!dialog) {
        dialog = await createDialog();
        state = createState(dialog);
        registerDialogListeners(dialog);
      }

      state.ready = false;
      state.rows = [];
      state.plans = [];
      state.recipes.replaceChildren();
      state.list.replaceChildren();
      setStatus("Loading recipes…");

      // Open the planner straight away so the wait is visible.
      if (!dialog.open) dialog.showModal();

      try {
        const [markup, payload] = await Promise.all([
          loadScalerMarkup(),
          requestIngredients(paths),
        ]);
        scalerMarkup = markup;
        await loadKatex();

        const ingredientsByPath = new Map(
          (payload.recipes ?? []).map((recipe) => [recipe.path, recipe.ingredients ?? []]),
        );

        const fragment = document.createDocumentFragment();
        for (const path of paths) {
          const recipe = recipeDetails(path);
          const row = buildRow(recipe, ingredientsByPath.get(path) ?? []);
          fragment.append(row);
          state.plans.push(recipe);
        }
        state.recipes.append(fragment);

        state.rows = [...state.recipes.querySelectorAll(".meal-planner__recipe")];
        for (const row of state.rows) {
          // Every recipe gets its own scaler so it can be scaled on its own.
          new RecipeScaler(row, { onUpdate: renderCombined });
        }

        state.ready = true;
        renderCombined();
        setStatus("");
      } catch (error) {
        setStatus(error.message || "Unable to load the selected recipes.");
      }
    } finally {
      loading = false;
    }
  }

  function initialize() {
    document.addEventListener("plan-meals", (event) => {
      openMealPlanner(event.detail?.paths || []);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
