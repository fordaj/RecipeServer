import html
import json
from pathlib import Path
from textwrap import dedent
from .config import Configuration
from .pallette import Pallette

FILE_PATH = Path(__file__)
INDEX_CSS_PATH = FILE_PATH.parent / "assets" / "index.css"
PULL_DOWN_PAGE_REFRESH_JS = FILE_PATH.parent / "assets" / "pull-down-page-refresh.js"


class Recipe:
    def __init__(self, metadata: dict, html_file: Path):
        self.metadata = metadata
        self.html_file = html_file


class IndexHTMLGenerator:
    def __init__(self, cfg: Configuration):
        self.recipes: list[Recipe] = []
        self.cfg = cfg

    def add(self, recipe: Recipe):
        self.recipes.append(recipe)

    @staticmethod
    def deslugify(slug: str) -> str:
        return slug.replace("-", " ").title()

    @staticmethod
    def values(metadata: dict, key: str) -> list[str]:
        """Return metadata values consistently as a list of strings."""
        value = metadata.get(key, [])

        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []

        return [str(item) for item in value if item is not None]

    @staticmethod
    def json_attribute(value: list[str]) -> str:
        """Serialize a list safely for an HTML attribute."""
        return html.escape(json.dumps(value), quote=True)

    def convert(self):
        links: list[str] = []
        all_meals: set[str] = set()
        all_categories: set[str] = set()
        all_tags: set[str] = set()

        for recipe in self.recipes:
            metadata = recipe.metadata
            file = recipe.html_file.relative_to(self.cfg.working_directory)

            title = str(metadata.get("title") or self.deslugify(file.parent.name))

            meals = self.values(metadata, "meals")
            categories = self.values(metadata, "categories")
            tags = self.values(metadata, "tags")

            all_meals.update(meals)
            all_categories.update(categories)
            all_tags.update(tags)

            search_text = " ".join([title, *meals, *categories, *tags])

            links.append(
                f'<li class="recipe"'
                f' data-title="{html.escape(title, quote=True)}"'
                f' data-search="{html.escape(search_text, quote=True)}"'
                f' data-meals="{self.json_attribute(meals)}"'
                f' data-categories="{self.json_attribute(categories)}"'
                f' data-tags="{self.json_attribute(tags)}">'
                f'<a href="{html.escape(file.as_posix(), quote=True)}">'
                f"{html.escape(title)}</a>"
                f"</li>"
            )

        def options(values: set[str]) -> str:
            return "\n".join(
                f'<option value="{html.escape(v.lower(), quote=True)}">' f"{html.escape(v)}</option>"
                for v in sorted(values, key=str.casefold)
            )

        css = INDEX_CSS_PATH.read_text(encoding="UTF-8")

        html_page = dedent(f"""\
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Recipe Server</title>
                <style>
                {css}
                </style>
                <script defer>
                const initRecipeIndex = () => {{
                    const list = document.querySelector("#recipe-list");
                    const recipes = [...list.querySelectorAll(".recipe")];
                    const search = document.querySelector("#recipe-search");
                    const meal = document.querySelector("#filter-meal");
                    const category = document.querySelector("#filter-category");
                    const tag = document.querySelector("#filter-tag");
                    const sort = document.querySelector("#sort-recipes");
                    const count = document.querySelector("#recipe-count");

                    const getValues = (recipe, key) =>
                        JSON.parse(recipe.dataset[key] || "[]")
                            .map(value => value.toLowerCase());

                    const update = () => {{
                        const query = search.value.trim().toLowerCase();
                        const selectedMeal = meal.value;
                        const selectedCategory = category.value;
                        const selectedTag = tag.value;

                        const visible = recipes.filter(recipe => {{
                            const matchesSearch =
                                recipe.dataset.search.toLowerCase().includes(query);

                            const matchesMeal =
                                !selectedMeal ||
                                getValues(recipe, "meals").includes(selectedMeal);

                            const matchesCategory =
                                !selectedCategory ||
                                getValues(recipe, "categories").includes(selectedCategory);

                            const matchesTag =
                                !selectedTag ||
                                getValues(recipe, "tags").includes(selectedTag);

                            return matchesSearch && matchesMeal &&
                                matchesCategory && matchesTag;
                        }});

                        const direction = sort.value === "za" ? -1 : 1;
                        visible.sort((a, b) =>
                            direction * a.dataset.title.localeCompare(
                                b.dataset.title, undefined,
                                {{ sensitivity: "base" }}
                            )
                        );

                        for (const recipe of visible) {{
                            list.appendChild(recipe);
                            recipe.hidden = false;
                        }}

                        for (const recipe of recipes) {{
                            if (!visible.includes(recipe)) {{
                                recipe.hidden = true;
                            }}
                        }}

                        count.textContent =
                            `${{visible.length}} of ${{recipes.length}} recipes`;
                    }};

                    [search, meal, category, tag, sort].forEach(control =>
                        control.addEventListener(
                            control === search ? "input" : "change", update
                        )
                    );

                    update();
                }};

                document.addEventListener("DOMContentLoaded", initRecipeIndex);
                </script>
            </head>
            <body>
                <main class="recipes">
                    <h1>Recipes</h1>

                    <div class="recipe-controls">
                        <input
                            id="recipe-search"
                            type="search"
                            placeholder="Search recipes, ingredients, tags..."
                            aria-label="Search recipes"
                        >

                        <select id="filter-meal" aria-label="Filter by meal">
                            <option value="">All meals</option>
                            {options(all_meals)}
                        </select>

                        <select id="filter-category" aria-label="Filter by category">
                            <option value="">All categories</option>
                            {options(all_categories)}
                        </select>

                        <select id="filter-tag" aria-label="Filter by tag">
                            <option value="">All tags</option>
                            {options(all_tags)}
                        </select>

                        <select id="sort-recipes" aria-label="Sort recipes">
                            <option value="az">Name: A–Z</option>
                            <option value="za">Name: Z–A</option>
                        </select>
                    </div>

                    <p id="recipe-count" aria-live="polite"></p>

                    <ul id="recipe-list">
                        {"".join(links)}
                    </ul>
                </main>
                <script defer>
                {PULL_DOWN_PAGE_REFRESH_JS.read_text(encoding="UTF-8", newline="\n")}
                </script>
            </body>
            </html>
        """)

        index_html = self.cfg.working_directory / "index.html"
        index_html.write_text(html_page, encoding="UTF-8", newline="\n")
