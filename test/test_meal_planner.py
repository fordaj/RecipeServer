from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


def build_index(tmp_path: Path) -> BeautifulSoup:
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    (recipe_path.parent / "image.webp").write_bytes(b"img")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()
    return BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")


def test_index_renders_plan_meals_control_and_assets(tmp_path: Path):
    soup = build_index(tmp_path)

    plan_meals = soup.select_one("#plan-meals")
    assert plan_meals is not None
    assert plan_meals.get_text(strip=True) == "Plan Meals"
    assert plan_meals.find_parent("div", class_="bulk-controls") is not None
    assert plan_meals.has_attr("disabled")

    assert soup.select_one('script[src^="/assets/meal-planner/meal-planner.js?v="]') is not None
    assert soup.select_one('link[href^="/assets/meal-planner/meal-planner.css?v="]') is not None
    assert soup.select_one('script[src^="/assets/recipe-scaler.js?v="]') is not None
    assert soup.select_one('link[href^="/assets/recipe-scaler.css?v="]') is not None
    # KaTeX renders the scaled quantities inside the planner.
    assert soup.select_one('script[src^="/assets/katex/dist/katex.min.js?v="]') is not None
    assert soup.select_one('link[href^="/assets/katex/dist/katex.min.css?v="]') is not None


def test_index_script_dispatches_meal_planner_with_selected_recipes():
    script = (ASSETS / "index.js").read_text(encoding="UTF-8")

    assert 'document.querySelector("#plan-meals")' in script
    assert "planMeals.disabled = selected.length === 0" in script
    assert 'new CustomEvent("meal-planner"' in script
    assert "paths.map((path) =>" in script
    assert 'image: image?.getAttribute("src")' in script


def test_meal_planner_markup_has_rows_combined_list_and_done_button():
    markup = (ASSETS / "meal-planner" / "meal-planner.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(markup, "html.parser")

    assert soup.select_one(".meal-planner__recipes") is not None
    assert soup.select_one(".meal-planner__combined h3").get_text(strip=True) == "Combined Ingredients"
    assert soup.select_one("ul.task-list.meal-planner__ingredients") is not None
    done = soup.select_one(".meal-planner__footer .meal-planner__done")
    assert done is not None and done.get_text(strip=True) == "Done"
    assert done["type"] == "submit"
    assert soup.select_one(".meal-planner__footer .meal-planner__copy").get_text(strip=True) == "Copy Markdown"
    assert soup.select_one(".meal-planner__footer .meal-planner__print").get_text(strip=True) == "Print / PDF"


def test_meal_planner_script_scans_headings_and_scales_per_recipe():
    script = (ASSETS / "meal-planner" / "meal-planner.js").read_text(encoding="UTF-8")

    # Ingredient scraping: an h1-h6 containing "ingredient" starts collection,
    # and each following heading re-evaluates the flag.
    assert '"h1, h2, h3, h4, h5, h6, li"' in script
    assert "/ingredient/i.test(element.textContent" in script
    assert "if (scraping) ingredients.push(element)" in script

    # Each recipe owns a cloned recipe-scaler.html and its own quantity spans.
    assert 'SCALER_MARKUP_URL = "/assets/recipe-scaler.html"' in script
    assert "new RecipeScaler(scaler" in script
    assert "quantities," in script
    assert "onUpdate: sortIngredients" in script

    # Combined list items are task-list items sorted alphabetically.
    assert 'item.className = "task-list-item"' in script
    assert "item.dataset.sortKey" in script
    assert "sortIngredients()" in script


def test_meal_planner_css_sizes_scaler_and_styles_done_like_save():
    css = (ASSETS / "meal-planner" / "meal-planner.css").read_text(encoding="UTF-8")

    rows = css.split(".meal-planner__recipe {")[1].split("}")[0]
    assert "display: grid" in rows
    assert "grid-template-columns" in rows

    scaler = css.split(".meal-planner__recipe .recipe-scaler {")[1].split("}")[0]
    assert "font-size" in scaler

    done = css.split(".meal-planner__footer .meal-planner__done {")[1].split("}")[0]
    assert "background: var(--food-color)" in done and "color: var(--page-bg)" in done

    # Printing hides the index behind the dialog and the planner controls.
    assert "@media print" in css
    assert "body > :not(.meal-planner-dialog)" in css


def test_recipe_scaler_can_be_scoped_to_one_recipe():
    script = (ASSETS / "recipe-scaler.js").read_text(encoding="UTF-8")
    markup = (ASSETS / "recipe-scaler.html").read_text(encoding="UTF-8")
    css = (ASSETS / "recipe-scaler.css").read_text(encoding="UTF-8")

    assert "constructor(root = document, options = {})" in script
    assert 'options.quantities ?? root.querySelectorAll(".quantity")' in script
    assert 'querySelector(".recipe-scale__select")' in script
    assert 'querySelector(".recipe-scale__custom")' in script
    assert "this.onUpdate" in script
    # The shared markup keeps its recipe-page IDs but gains classes so
    # cloned copies work without duplicate IDs.
    assert 'class="recipe-scale__select"' in markup
    assert 'class="recipe-scale__custom"' in markup
    assert ".recipe-scale__select," in css and ".recipe-scale__custom {" in css
