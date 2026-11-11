(() => {
  const MEAL_PLANNER_ID = "meal-planner-dialog";
  const MEAL_PLANNER_ASSET = "/assets/meal-planner.html";

  async function createMealPlanner() {
    const dialog = document.createElement("dialog");
    dialog.id = MEAL_PLANNER_ID;
    dialog.className = "meal-planner-dialog";
    const response = await fetch(MEAL_PLANNER_ASSET, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load meal planner (HTTP ${response.status})`);
    }
    dialog.innerHTML = await response.text();
    document.body.append(dialog);
    return dialog;
  }

  function recipeUrlFromPath(path) {
    return "/" + path.replace(/\.md$/i, ".html");
  }

  function resolveImageUrl(src, recipePath) {
    if (!src) return "";
    if (/^https?:\/\//i.test(src) || src.startsWith("/")) return src;
    const directory = recipePath.substring(0, recipePath.lastIndexOf("/") + 1);
    return "/" + (directory + src).replace(/^\/+/, "");
  }

  function parseIngredients(htmlText, recipePath) {
    const doc = new DOMParser().parseFromString(htmlText, "text/html");
    const title = (doc.querySelector("h1")?.textContent || "").trim();
    const image = resolveImageUrl(doc.querySelector("img")?.getAttribute("src"), recipePath);
    const ingredients = [];
    let SCRAPING_INGREDIENTS = false;
    const walker = doc.createTreeWalker(doc.body || doc, NodeFilter.SHOW_ELEMENT);
    let node = walker.currentNode;
    // Start before first node; use nextNode loop
    while ((node = walker.nextNode())) {
      if (/^H[1-6]$/.test(node.nodeName)) {
        SCRAPING_INGREDIENTS = /ingredient/i.test(node.textContent || "");
      } else if (node.nodeName === "LI" && SCRAPING_INGREDIENTS) {
        const text = (node.textContent || "").trim();
        if (text) ingredients.push(text);
      }
    }
    return { title, image, ingredients };
  }

  function renderRow(container, recipe) {
    const row = document.createElement("div");
    row.className = "meal-planner__recipe-row";

    const scalerWrap = document.createElement("div");
    scalerWrap.className = "meal-planner__recipe-scaler";
    scalerWrap.innerHTML = `
      <div class="recipe-scaler">
        <select id="recipe-scale-select" aria-label="Recipe scale">
          <option value="0.5">0.5</option>
          <option value="1" selected>1</option>
          <option value="1.5">1.5</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="custom">Custom</option>
        </select>
        <input id="recipe-scale-custom" min="0.125" step="0.125" type="number" value="1" aria-label="Custom recipe scale" hidden>
        <span class="scale-symbol">×</span>
      </div>
    `;

    const image = document.createElement("img");
    image.className = "meal-planner__recipe-image";
    image.src = recipe.image;
    image.alt = recipe.title;

    const name = document.createElement("div");
    name.className = "meal-planner__recipe-name";
    name.textContent = recipe.title;

    row.append(scalerWrap, image, name);
    container.append(row);

    const scaleSelect = scalerWrap.querySelector("#recipe-scale-select");
    const customInput = scalerWrap.querySelector("#recipe-scale-custom");
    scaleSelect.addEventListener("change", () => {
      const isCustom = scaleSelect.value === "custom";
      scaleSelect.hidden = isCustom;
      customInput.hidden = !isCustom;
      renderCombined();
    });
    customInput.addEventListener("input", () => {
      renderCombined();
    });

    recipe.scale = () => {
      if (scaleSelect.value === "custom") {
        return Number(customInput.value) || 1;
      }
      return Number(scaleSelect.value) || 1;
    };

    return recipe;
  }

  let dialog = null;
  let recipes = [];
  let combinedList = null;

  function renderCombined() {
    if (!combinedList) return;
    const items = [];
    for (const recipe of recipes) {
      const scale = recipe.scale ? recipe.scale() : 1;
      for (const ingredient of recipe.ingredients) {
        items.push(ingredient);
      }
    }
    items.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    combinedList.replaceChildren();
    for (const item of items) {
      const li = document.createElement("li");
      li.className = "task-list-item";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      li.append(checkbox, document.createTextNode(" " + item));
      combinedList.append(li);
    }
  }

  async function openMealPlanner(paths) {
    if (!paths?.length) return;
    if (!dialog) {
      dialog = await createMealPlanner();
      const close = dialog.querySelector(".meal-planner__close");
      const done = dialog.querySelector(".meal-planner__done");
      combinedList = dialog.querySelector(".meal-planner__ingredients");
      const recipesContainer = dialog.querySelector(".meal-planner__recipes");
      close?.addEventListener("click", () => dialog.close());
      done?.addEventListener("click", () => dialog.close());
      dialog.addEventListener("close", () => {
        recipesContainer.replaceChildren();
        if (combinedList) combinedList.replaceChildren();
        recipes = [];
      });
    }

    const recipesContainer = dialog.querySelector(".meal-planner__recipes");
    recipesContainer.replaceChildren();
    recipes = [];

    const loaded = await Promise.all(
      paths.map(async (path) => {
        try {
          const response = await fetch(recipeUrlFromPath(path), { cache: "no-store" });
          const html = await response.text();
          const parsed = parseIngredients(html, path);
          parsed.path = path;
          if (!parsed.image) {
            parsed.image = resolveImageUrl("", path);
          }
          return parsed;
        } catch (error) {
          return { title: path, image: "", ingredients: [], path };
        }
      }),
    );

    for (const recipe of loaded) {
      renderRow(recipesContainer, recipe);
      recipes.push(recipe);
    }

    renderCombined();
    if (!dialog.open) dialog.showModal();
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
