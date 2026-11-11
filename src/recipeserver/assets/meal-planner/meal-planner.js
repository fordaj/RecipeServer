(() => {
  const DIALOG_ID = "meal-planner-dialog";
  const MARKUP_URL = "/assets/meal-planner/meal-planner.html";
  const SCALER_MARKUP_URL = "/assets/recipe-scaler.html";

  let dialog = null;
  let refs = null;
  let scalerMarkup = "";
  let loadToken = 0;
  let scrollY = 0;

  // ----- Markup ----- //

  async function fetchText(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load ${url} (HTTP ${response.status})`);
    }
    return response.text();
  }

  async function ensureDialog() {
    if (dialog) return;

    const markup = await fetchText(MARKUP_URL);
    scalerMarkup = await fetchText(SCALER_MARKUP_URL);

    dialog = document.createElement("dialog");
    dialog.id = DIALOG_ID;
    dialog.className = "meal-planner-dialog";
    dialog.innerHTML = markup;
    document.body.append(dialog);

    refs = {
      dialog,
      recipes: dialog.querySelector(".meal-planner__recipes"),
      ingredients: dialog.querySelector(".meal-planner__ingredients"),
      status: dialog.querySelector(".meal-planner__status"),
      close: dialog.querySelector(".meal-planner__close"),
      copy: dialog.querySelector(".meal-planner__copy"),
      print: dialog.querySelector(".meal-planner__print"),
    };

    refs.close.addEventListener("click", closePlanner);
    refs.copy.addEventListener("click", copyMarkdown);
    refs.print.addEventListener("click", () => window.print());
    dialog.addEventListener("close", () => {
      loadToken += 1;
      unlockBackgroundScroll();
    });

    let pointerDownTarget = null;
    dialog.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && pointerDownTarget === dialog) {
        closePlanner();
      }
      pointerDownTarget = null;
    });
  }

  // ----- Path helpers ----- //

  function recipePageUrl(path) {
    const page = path.replace(/\.md$/i, ".html").replace(/^\/+/, "");
    return new URL(`/${page}`, window.location.origin);
  }

  function fallbackTitle(path) {
    const parts = path.replace(/\.md$/i, "").split("/").filter(Boolean);
    return parts.length > 1 ? parts[parts.length - 2] : (parts[0] ?? "Recipe");
  }

  // ----- Ingredient extraction ----- //

  // Scan the generated recipe page in document order. A heading that
  // mentions "ingredients" starts a list; the next heading re-evaluates
  // whether its list should be collected too.
  function extractIngredients(doc) {
    const ingredients = [];
    let scraping = false;

    for (const element of doc.querySelectorAll("h1, h2, h3, h4, h5, h6, li")) {
      if (/^H[1-6]$/.test(element.tagName)) {
        scraping = /ingredient/i.test(element.textContent ?? "");
        continue;
      }

      if (scraping) ingredients.push(element);
    }

    return ingredients;
  }

  // Remove leading amounts and units so the shopping list sorts by the
  // ingredient itself rather than by its quantity.
  function sortText(text) {
    const units =
      "cups?|tbsps?|tsps?|tablespoons?|teaspoons?|grams?|g|kg|mg|ml|mL|L|l|oz|ounces?|lbs?|pounds?";
    return text
      .replace(/\s+/g, " ")
      .trim()
      .replace(
        new RegExp(
          `^(?:[\\d\\s./\\u00bc-\\u00be-]+\\s*(?:${units})?\\b|(?:${units})\\b)\\s*(?:of\\s+)?`,
          "i",
        ),
        "",
      )
      .replace(/^of\s+/i, "")
      .toLowerCase();
  }

  // Convert a rendered (KaTeX) quantity back to plain text for Markdown
  // export and sorting. KaTeX duplicates its text in the MathML and HTML
  // trees, which would otherwise appear twice when reading textContent.
  function quantityText(span) {
    const start = Number(span.dataset.quantity);
    const end = Number(span.dataset.quantityEnd);
    if (!Number.isFinite(start)) return (span.textContent ?? "").trim();

    const amount = Number.isFinite(end) ? `${start}-${end}` : `${start}`;
    const unit = (span.dataset.unit ?? "").trim();
    return unit ? `${amount} ${unit}` : amount;
  }

  function ingredientText(item) {
    const clone = item.cloneNode(true);
    clone.querySelectorAll(".quantity").forEach((span) => {
      span.replaceWith(document.createTextNode(quantityText(span)));
    });
    return (clone.textContent ?? "").replace(/\s+/g, " ").trim();
  }

  function buildIngredientItem(ingredient, pageUrl) {
    const content = ingredient.cloneNode(true);
    content
      .querySelectorAll('input[type="checkbox"], script, style')
      .forEach((element) => element.remove());

    // Ingredient links/images are relative to the recipe page, not the index.
    content.querySelectorAll("a[href]").forEach((link) => {
      link.href = new URL(link.getAttribute("href"), pageUrl).href;
    });
    content.querySelectorAll("img[src]").forEach((image) => {
      image.src = new URL(image.getAttribute("src"), pageUrl).href;
    });

    const item = document.createElement("li");
    item.className = "task-list-item";

    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";

    const text = document.createElement("span");
    text.className = "meal-planner__ingredient-text";
    while (content.firstChild) text.append(content.firstChild);

    label.append(checkbox, text);
    item.append(label);
    item.dataset.sortKey = sortText(ingredientText(item));
    return item;
  }

  // ----- Recipe rows ----- //

  function createScaler() {
    const template = document.createElement("template");
    template.innerHTML = scalerMarkup.trim();
    const scaler = template.content.firstElementChild;
    // IDs are unique per document; the shared markup is cloned for every
    // row, so the scaler relies on its classes instead.
    scaler.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    return scaler;
  }

  function createRecipeRow(title, imageUrl) {
    const row = document.createElement("div");
    row.className = "meal-planner__recipe";

    const scaler = createScaler();
    row.append(scaler);

    const image = document.createElement("img");
    image.className = "meal-planner__recipe-image";
    image.alt = "";
    image.loading = "lazy";
    if (imageUrl) {
      image.src = imageUrl;
    } else {
      image.hidden = true;
    }
    row.append(image);

    const name = document.createElement("p");
    name.className = "meal-planner__recipe-name";
    name.textContent = title;
    row.append(name);

    return { row, scaler };
  }

  function mountScaler(scaler, quantities) {
    if (typeof RecipeScaler !== "function") {
      scaler.remove();
      return;
    }

    new RecipeScaler(scaler, {
      scalerElement: scaler,
      quantities,
      onUpdate: sortIngredients,
    });
  }

  // ----- Combined list ----- //

  function sortIngredients() {
    const items = [...refs.ingredients.children];
    items.sort((left, right) =>
      (left.dataset.sortKey ?? "").localeCompare(right.dataset.sortKey ?? "", undefined, {
        sensitivity: "base",
        numeric: true,
      }),
    );
    refs.ingredients.append(...items);
  }

  function setStatus(message) {
    refs.status.textContent = message;
  }

  async function loadRecipe(selection) {
    const pageUrl = recipePageUrl(selection.path);
    const response = await fetch(pageUrl.href, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    return { doc, pageUrl };
  }

  function resolveTitle(selection, doc) {
    const heading = doc.querySelector("h1")?.textContent?.trim();
    return selection.title || heading || fallbackTitle(selection.path);
  }

  function resolveImage(selection, doc, pageUrl) {
    if (selection.image) return selection.image;

    const image = doc.querySelector("main img, img");
    const source = image?.getAttribute("src");
    if (!source) return "";
    try {
      return new URL(source, pageUrl).href;
    } catch {
      return "";
    }
  }

  async function renderPlanner(selections) {
    const token = ++loadToken;
    refs.recipes.replaceChildren();
    refs.ingredients.replaceChildren();
    refs.copy.disabled = true;
    setStatus("Loading selected recipes…");

    const results = await Promise.all(
      selections.map(async (selection) => {
        try {
          return { selection, ...(await loadRecipe(selection)) };
        } catch (error) {
          return { selection, error };
        }
      }),
    );

    if (token !== loadToken) return;

    const failed = [];

    for (const result of results) {
      const { selection } = result;
      const doc = result.doc;
      const title = doc
        ? resolveTitle(selection, doc)
        : selection.title || fallbackTitle(selection.path);
      const imageUrl = doc ? resolveImage(selection, doc, result.pageUrl) : selection.image;
      const { row, scaler } = createRecipeRow(title, imageUrl);
      refs.recipes.append(row);

      if (!doc) {
        failed.push(title);
        continue;
      }

      const quantities = [];
      for (const ingredient of extractIngredients(doc)) {
        const item = buildIngredientItem(ingredient, result.pageUrl);
        refs.ingredients.append(item);
        quantities.push(...item.querySelectorAll(".quantity"));
      }

      mountScaler(scaler, quantities);
    }

    sortIngredients();

    if (failed.length) {
      setStatus(`Could not load: ${failed.join(", ")}.`);
    } else if (!refs.ingredients.children.length) {
      setStatus("No ingredients found in the selected recipes.");
    } else {
      setStatus("");
    }

    if (refs.copy) refs.copy.disabled = refs.ingredients.children.length === 0;
  }

  // ----- Dialog actions ----- //

  function lockBackgroundScroll() {
    scrollY = window.scrollY;
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
  }

  function unlockBackgroundScroll() {
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";
    window.scrollTo(0, scrollY);
  }

  function closePlanner() {
    dialog?.close();
  }

  async function openPlanner(selections) {
    if (!selections?.length) return;

    await ensureDialog();
    if (!dialog.open) {
      lockBackgroundScroll();
      dialog.showModal();
    }
    await renderPlanner(selections);
  }

  function buildMarkdown() {
    return [...refs.ingredients.querySelectorAll(".task-list-item")]
      .map((item) => {
        const checked = item.querySelector('input[type="checkbox"]')?.checked;
        return `- [${checked ? "x" : " "}] ${ingredientText(item)}`;
      })
      .join("\n");
  }

  async function copyMarkdown() {
    const markdown = buildMarkdown();
    if (!markdown) return;

    try {
      await navigator.clipboard.writeText(markdown);
      setStatus("Copied the ingredient list as Markdown.");
    } catch {
      setStatus("Unable to copy the ingredient list.");
    }
  }

  // ----- Bootstrap ----- //

  function initialize() {
    if (!document.querySelector("#plan-meals")) return;

    document.addEventListener("meal-planner", (event) => {
      openPlanner(event.detail?.recipes ?? []).catch((error) => {
        console.error("Meal planner failed to open", error);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
