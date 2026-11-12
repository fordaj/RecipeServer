(() => {
  const SHOPPING_LIST_ID = "shopping-list-dialog";
  const SHOPPING_LIST_ASSETS = "/assets/shopping-list";
  const SHOPPING_LIST_API = "/api/shopping-list";
  const RECIPE_SCALER_URL = "/assets/recipe-scaler.html";
  const KATEX_CSS_URL = "/assets/katex/dist/katex.min.css";
  const KATEX_JS_URL = "/assets/katex/dist/katex.min.js";
  const PRINTER_ICON_URL = "/assets/printer.svg";
  const LIST_ICON_URL = "/assets/list.svg";
  const COPY_ICON_URL = "/assets/copy.svg";

  let dialog = null;
  let state = null;
  let scalerMarkup = "";
  let katexPromise = null;
  let loading = false;

  // ----- Markup and assets ----- //

  async function fetchTemplate(name) {
    const response = await fetch(`${SHOPPING_LIST_ASSETS}/${name}.html`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load shopping list template: ${name} (HTTP ${response.status})`);
    }
    return response.text();
  }

  async function createDialog() {
    const element = document.createElement("dialog");
    element.id = SHOPPING_LIST_ID;
    element.className = "shopping-list-dialog";
    element.innerHTML = await fetchTemplate("shopping-list");
    document.body.append(element);
    return element;
  }

  // The icons are fetched and inlined so they inherit the colour of the
  // button they sit in through currentColor.
  async function loadSvgIcon(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return "";

      const svg = new DOMParser().parseFromString(
        await response.text(),
        "image/svg+xml",
      ).documentElement;
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      return new XMLSerializer().serializeToString(svg);
    } catch {
      return "";
    }
  }

  async function loadIcons(element) {
    const [printer, list, copy] = await Promise.all([
      loadSvgIcon(PRINTER_ICON_URL),
      loadSvgIcon(LIST_ICON_URL),
      loadSvgIcon(COPY_ICON_URL),
    ]);

    const icons = { ".shopping-list__print": printer, ".shopping-list__download": list };

    for (const [selector, icon] of Object.entries(icons)) {
      const target = element.querySelector(`${selector} .shopping-list__icon`);
      if (target && icon) target.innerHTML = icon;
    }

    const copyButton = element.querySelector(".shopping-list__copy");
    if (copyButton && copy) copyButton.innerHTML = copy;
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

  // KaTeX is only needed once the shopping list opens, so it is loaded on demand
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
    const url = new URL(SHOPPING_LIST_API, window.location.origin);
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
      status: element.querySelector(".shopping-list__status"),
      recipes: element.querySelector(".shopping-list__recipes"),
      list: element.querySelector(".shopping-list__ingredients"),
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

  // ----- Ingredient helpers ----- //

  // Two ingredients are the same when they name the same thing in the same
  // unit. The name and the unit come from the server, so the rules live in
  // one place.
  function mergeKeyFor(ingredient) {
    return [ingredient.name, ingredient.unit, ingredient.has_range ? "range" : "single"].join("|");
  }

  // The plain text of an ingredient, with the scaled amount in place of the
  // quantity span the recipe scaler renders with KaTeX.
  function plainText(element) {
    const clone = element.cloneNode(true);

    clone.querySelectorAll('input[type="checkbox"]').forEach((node) => node.remove());
    clone.querySelectorAll(".shopping-list__sources").forEach((node) => node.remove());
    clone.querySelectorAll(".quantity").forEach((node) => {
      node.replaceWith(document.createTextNode(node.dataset.scaledText ?? node.textContent));
    });

    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  // The parts of an ingredient that are not the amount.
  function remainderOf(item) {
    const clone = item.cloneNode(true);

    clone.querySelectorAll('input[type="checkbox"]').forEach((node) => node.remove());
    clone.querySelectorAll(".quantity").forEach((node) => node.remove());

    return clone.textContent.replace(/\s+/g, " ").trim();
  }

  // ----- Combining ingredients ----- //

  function collectEntries() {
    const entries = [];

    for (const row of state.rows) {
      const source = row.dataset.recipeName ?? "";

      for (const item of row.querySelectorAll(".shopping-list__recipe-ingredients > li")) {
        // The placeholder for a recipe without ingredients is not an ingredient.
        if (item.classList.contains("shopping-list__no-ingredients")) continue;

        const quantityElement = item.querySelector(".quantity");
        const scaled = quantityElement ? parseFloat(quantityElement.dataset.scaledQuantity) : NaN;
        const scaledEnd = quantityElement?.dataset.scaledQuantityEnd;

        entries.push({
          key: item.dataset.mergeKey,
          source,
          item,
          unit: quantityElement?.dataset.unit ?? "",
          remainder: remainderOf(item),
          quantity: Number.isFinite(scaled) ? scaled : null,
          end: scaledEnd === undefined ? null : Number.parseFloat(scaledEnd),
        });
      }
    }

    return entries;
  }

  // Add the amounts of the ingredients that name the same thing together.
  function mergeEntries(entries) {
    const groups = new Map();

    for (const entry of entries) {
      let group = groups.get(entry.key);

      if (!group) {
        group = {
          key: entry.key,
          unit: entry.unit,
          hasRange: entry.end !== null,
          quantity: entry.quantity,
          end: entry.end,
          sources: [],
          members: [],
        };
        groups.set(entry.key, group);
      } else if (group.quantity !== null && entry.quantity !== null) {
        group.quantity += entry.quantity;
        if (group.end !== null && entry.end !== null) group.end += entry.end;
      }

      group.members.push(entry);
      if (!group.sources.includes(entry.source)) group.sources.push(entry.source);
    }

    return [...groups.values()];
  }

  // The amount of a combined ingredient.
  function buildGroupAmount(group) {
    if (group.quantity === null) return null;

    const span = document.createElement("span");
    span.className = "quantity";
    span.dataset.unit = group.unit;
    // The combined list is not scaled, so the amount is already the
    // scaled one.
    span.dataset.quantity = String(group.quantity);
    if (group.hasRange && group.end !== null) span.dataset.quantityEnd = String(group.end);

    const scaled = RecipeScaler.roundQuantity(group.quantity, group.unit);
    let formatted = RecipeScaler.formatQuantity(scaled, group.unit);
    let text = RecipeScaler.formatQuantityText(scaled, group.unit);

    if (group.hasRange && group.end !== null) {
      formatted = RecipeScaler.formatScaledRange(scaled, group.end, group.unit);
      text = RecipeScaler.formatScaledRangeText(scaled, group.end, group.unit);
    }

    span.dataset.scaledText = text;
    RecipeScaler.renderQuantity(span, formatted);
    return span;
  }

  // The content of a combined ingredient: the amount and the rest of the
  // line, keeping the markup of the recipe it came from.
  function buildGroupContent(group) {
    const content = document.createElement("span");
    content.className = "shopping-list__ingredient";

    const clone = group.members[0].item.cloneNode(true);
    clone.querySelectorAll('input[type="checkbox"]').forEach((node) => node.remove());

    const amount = buildGroupAmount(group);
    const quantityElement = clone.querySelector(".quantity");
    if (quantityElement) {
      if (amount) {
        quantityElement.replaceWith(amount);
      } else {
        quantityElement.remove();
      }
    }

    while (clone.firstChild) content.append(clone.firstChild);
    return content;
  }

  // ----- Rendering ----- //

  function buildRow(recipe, ingredients) {
    const row = document.createElement("div");
    row.className = "shopping-list__recipe";
    row.dataset.recipeName = recipe.title;

    const scaler = document.createElement("div");
    scaler.className = "shopping-list__scaler";
    scaler.innerHTML = scalerMarkup;

    const image = document.createElement(recipe.image ? "img" : "span");
    image.className = "shopping-list__image";
    if (recipe.image) {
      image.src = recipe.image;
      image.alt = "";
      image.loading = "lazy";
    } else {
      // Keep the row aligned when the recipe has no image.
      image.classList.add("shopping-list__image--empty");
      image.setAttribute("aria-hidden", "true");
    }

    const details = document.createElement("div");
    details.className = "shopping-list__details";

    const name = document.createElement("h4");
    name.className = "shopping-list__name";
    name.textContent = recipe.title;

    const list = document.createElement("ul");
    list.className = "shopping-list__recipe-ingredients";

    for (const ingredient of ingredients) {
      const item = document.createElement("li");
      item.innerHTML = ingredient.html;
      item.dataset.mergeKey = mergeKeyFor(ingredient);
      // The combined list is the checklist. The per-recipe lists only
      // show the amounts, so their checkboxes are dropped.
      item.querySelectorAll('input[type="checkbox"]').forEach((input) => input.remove());
      list.append(item);
    }

    if (!list.childElementCount) {
      const empty = document.createElement("li");
      empty.className = "shopping-list__no-ingredients";
      empty.textContent = "No ingredients found.";
      list.append(empty);
    }

    details.append(name, list);
    row.append(scaler, image, details);
    return row;
  }

  function buildChecklistItem(entry) {
    const item = document.createElement("li");
    item.className = "task-list-item";
    // The merge key identifies the ingredient, so a ticked ingredient
    // stays ticked when a scale change changes its amount.
    item.dataset.mergeKey = entry.group.key;

    const row = document.createElement("span");
    row.className = "shopping-list__item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";

    const sources = document.createElement("span");
    sources.className = "shopping-list__sources";
    sources.textContent = entry.group.sources.join(", ");

    row.append(checkbox, entry.content, sources);
    item.append(row);
    return item;
  }

  // The key of a ticked item. The merge key is used when it is there, so
  // the tick survives a scale change.
  function tickedKey(item) {
    return item.dataset.mergeKey || plainText(item);
  }

  function renderCombined() {
    if (!state?.ready) return;

    // Keep the ticked items ticked when a scale change re-renders the list.
    const ticked = new Set();
    for (const item of state.list.querySelectorAll(".task-list-item")) {
      if (item.querySelector('input[type="checkbox"]')?.checked) ticked.add(tickedKey(item));
    }

    const entries = mergeEntries(collectEntries()).map((group) => {
      const content = buildGroupContent(group);
      return { group, content, text: plainText(content) };
    });

    entries.sort((left, right) =>
      left.text.localeCompare(right.text, undefined, { sensitivity: "base" }),
    );

    const fragment = document.createDocumentFragment();
    for (const entry of entries) {
      fragment.append(buildChecklistItem(entry));
    }
    state.list.replaceChildren(fragment);

    for (const item of state.list.querySelectorAll(".task-list-item")) {
      const checkbox = item.querySelector('input[type="checkbox"]');
      if (checkbox) checkbox.checked = ticked.has(tickedKey(item));
    }

    if (!state.list.childElementCount) {
      const empty = document.createElement("li");
      empty.className = "shopping-list__no-ingredients";
      empty.textContent = "No ingredients found.";
      state.list.append(empty);
    }
  }

  // ----- Checklist export ----- //

  function buildChecklistMarkdown() {
    const lines = ["# Shopping List", "", "## Recipes", ""];

    for (const recipe of state.selected) {
      lines.push(`- ${recipe.title}`);
    }

    lines.push("", "## Combined Ingredients", "");

    for (const item of state.list.querySelectorAll(".task-list-item")) {
      const checked = item.querySelector('input[type="checkbox"]')?.checked ? "x" : " ";
      lines.push(`- [${checked}] ${plainText(item)}`);
    }

    return `${lines.join("\n")}\n`;
  }

  // The file name carries the date, so a list of lists can be told apart.
  function checklistFileName() {
    const today = new Date();
    const month = String(today.getMonth() + 1).padStart(2, "0");
    const day = String(today.getDate()).padStart(2, "0");
    return `${month}-${day}-${today.getFullYear()} Shopping List.md`;
  }

  function downloadChecklist() {
    const blob = new Blob([buildChecklistMarkdown()], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = checklistFileName();
    document.body.append(link);
    link.click();
    link.remove();

    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // Copy the checklist to the clipboard, falling back to a hidden text area
  // when the clipboard API is not available.
  async function copyChecklist() {
    const markdown = buildChecklistMarkdown();

    try {
      await navigator.clipboard.writeText(markdown);
      return true;
    } catch {
      // The clipboard API needs a secure context, so fall back to the
      // older selection based copy.
    }

    try {
      const field = document.createElement("textarea");
      field.value = markdown;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.append(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      return copied;
    } catch {
      return false;
    }
  }

  // ----- Dialog wiring ----- //

  function registerDialogListeners(element) {
    element
      .querySelector(".shopping-list__close")
      ?.addEventListener("click", () => element.close());

    element.querySelector(".shopping-list__print")?.addEventListener("click", () => window.print());

    element
      .querySelector(".shopping-list__download")
      ?.addEventListener("click", () => downloadChecklist());

    element.querySelector(".shopping-list__copy")?.addEventListener("click", async () => {
      const copied = await copyChecklist();
      setStatus(copied ? "Checklist copied to the clipboard." : "Unable to copy the checklist.");
    });

    // The dialog form closes the shopping list; the "Done" button submits it.
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
      state.selected = [];
      state.recipes.replaceChildren();
      state.list.replaceChildren();
    });
  }

  // ----- Opening ----- //

  async function openShoppingList(paths) {
    if (!paths?.length || loading) return;
    loading = true;

    try {
      if (!dialog) {
        dialog = await createDialog();
        state = createState(dialog);
        registerDialogListeners(dialog);
        loadIcons(dialog);
      }

      state.ready = false;
      state.rows = [];
      state.selected = [];
      state.recipes.replaceChildren();
      state.list.replaceChildren();
      setStatus("Loading recipes…");

      // Open the shopping list straight away so the wait is visible.
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
          state.selected.push(recipe);
        }
        state.recipes.append(fragment);

        state.rows = [...state.recipes.querySelectorAll(".shopping-list__recipe")];
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
    document.addEventListener("shopping-list", (event) => {
      openShoppingList(event.detail?.paths || []);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
