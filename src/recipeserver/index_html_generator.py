import html
import json
import math
from pathlib import Path
from statistics import mean
from textwrap import dedent

from bs4 import BeautifulSoup

from .config import Configuration
from ._logger import logger
from .image_handler import get_first_image_in_dir

FILE_PATH = Path(__file__)
THEME_CSS_PATH = "/assets/theme.css"
INDEX_CSS_PATH = "/assets/index.css"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

_DETAIL_ICONS = {
    "makes": "/assets/chef-hat.svg",
    "difficulty": "/assets/gauge.svg",
    "meals": "/assets/utensils.svg",
    "categories": "/assets/cooking-pot.svg",
    "tags": "/assets/tag.svg",
    "cuisine": "/assets/pin.svg",
}


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
    def values(metadata: dict, *keys: str) -> list[str]:
        """Return metadata values consistently as a list of strings."""
        collected: list[str] = []
        seen: set[str] = set()

        for key in keys:
            value = metadata.get(key, [])

            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                continue

            for item in value:
                if item is None:
                    continue
                text = str(item)
                if text not in seen:
                    seen.add(text)
                    collected.append(text)

        return collected

    @staticmethod
    def json_attribute(value: list[str]) -> str:
        """Serialize a list safely for an HTML attribute."""
        return html.escape(json.dumps(value), quote=True)

    @staticmethod
    def _average_rating(metadata: dict) -> tuple[float | None, int]:
        ratings = metadata.get("ratings", [])
        if not isinstance(ratings, list):
            return None, 0

        scores = [
            score
            for rating in ratings
            if isinstance(rating, dict)
            and isinstance((score := rating.get("rating")), (int, float))
            and math.isfinite(score)
        ]
        return (mean(scores), len(scores)) if scores else (None, 0)

    @staticmethod
    def _icon(key: str) -> str:
        asset_url = _DETAIL_ICONS[key]
        asset_path = FILE_PATH.parent / "assets" / Path(asset_url).name
        soup = BeautifulSoup(asset_path.read_text(encoding="UTF-8"), "html.parser")
        icon = soup.find("svg")
        if icon is None:
            raise ValueError(f"No SVG element found in {asset_path}")

        icon["class"] = ["recipe-icon"]
        icon["aria-hidden"] = "true"
        icon["focusable"] = "false"
        return str(icon)

    @classmethod
    def _detail(cls, key: str, label: str, values: list[str]) -> str:
        if not values:
            return ""

        tooltip = html.escape(f"{label}: {', '.join(values)}", quote=True)
        if key in {"makes", "difficulty"}:
            content = html.escape(", ".join(values))
        else:
            content = "".join(f'<span class="recipe-chip">{html.escape(value)}</span>' for value in values)

        return (
            f'<span class="recipe-detail recipe-detail--{key}" '
            f'role="img" aria-label="{tooltip}" title="{tooltip}">'
            f'{cls._icon(key)}<span class="recipe-detail__value">'
            f"{content}</span></span>"
        )

    def convert(self):
        links: list[str] = []
        all_meals: set[str] = set()
        all_categories: set[str] = set()
        all_tags: set[str] = set()
        all_cuisine: set[str] = set()

        for recipe in self.recipes:
            metadata = recipe.metadata
            file = recipe.html_file

            relative_path = file.relative_to(self.cfg.site_directory)
            url = "/" + relative_path.as_posix()
            recipe_page = BeautifulSoup(file.read_text(encoding="UTF-8"), "html.parser")
            heading = recipe_page.find("h1")
            heading_title = heading.get_text(" ", strip=True) if heading else ""
            title = heading_title or str(metadata.get("title") or self.deslugify(file.parent.name))
            hero_image = get_first_image_in_dir(file.parent) if file.parent.is_dir() else None
            hero_url = "/" + hero_image.relative_to(self.cfg.site_directory).as_posix() if hero_image else ""

            meals = self.values(metadata, "meals")
            categories = self.values(metadata, "categories")
            tags = self.values(metadata, "tags")
            cuisine = self.values(metadata, "cuisine")

            all_meals.update(meals)
            all_categories.update(categories)
            all_tags.update(tags)
            all_cuisine.update(cuisine)

            search_text = " ".join([title, *meals, *categories, *tags, *cuisine])
            average_rating, rating_count = self._average_rating(metadata)
            rating_attribute = f"{average_rating:.6g}" if average_rating is not None else ""
            makes = metadata.get("makes")
            difficulty = metadata.get("difficulty")
            makes_value = str(makes) if isinstance(makes, (int, float)) else ""
            difficulty_value = str(difficulty) if isinstance(difficulty, (int, float)) else ""

            rating_html = ""
            if average_rating:
                rating_html = (
                    f'<span class="recipe-rating" role="img" '
                    f'aria-label="Rated {average_rating:.1f} out of 10 '
                    f'from {rating_count} ratings">'
                    f'<span class="recipe-rating__star" aria-hidden="true">★</span>'
                    f'<span class="recipe-rating__score">{average_rating:.1f}/10</span>'
                    f'<span class="recipe-rating__count">({rating_count})</span>'
                    "</span>"
                )

            image_html = (
                '<div class="recipe-card__image">'
                f'<img src="{html.escape(hero_url, quote=True)}" alt="" loading="lazy">'
                "</div>"
                if hero_url
                else ""
            )

            details = "".join(
                (
                    self._detail("makes", "Makes", [f"x{makes_value}"] if makes_value else []),
                    self._detail(
                        "difficulty",
                        "Difficulty",
                        [f"{difficulty_value}/10"] if difficulty_value else [],
                    ),
                    self._detail("meals", "Meals", meals),
                    self._detail("cuisine", "Cuisine", cuisine),
                    self._detail("categories", "Categories", categories),
                    self._detail("tags", "Tags", tags),
                )
            )

            links.append(
                f'<li class="recipe"'
                f' data-title="{html.escape(title, quote=True)}"'
                f' data-search="{html.escape(search_text, quote=True)}"'
                f' data-meals="{self.json_attribute(meals)}"'
                f' data-categories="{self.json_attribute(categories)}"'
                f' data-tags="{self.json_attribute(tags)}"'
                f' data-cuisine="{self.json_attribute(cuisine)}"'
                f' data-rating="{rating_attribute}"'
                f' data-makes="{makes_value}"'
                f' data-difficulty="{difficulty_value}">'
                f'<a class="recipe-card__link" href="{html.escape(url, quote=True)}" '
                f'aria-label="View {html.escape(title, quote=True)} recipe">'
                '<article class="recipe-card">'
                f"{image_html}"
                '<div class="recipe-card__heading">'
                f"<h2>{html.escape(title)}</h2>"
                f"{rating_html}"
                "</div>"
                f'<div class="recipe-card__details">{details}</div>'
                "</article>"
                "</a>"
                "</li>"
            )

        def options(values: set[str]) -> str:
            return "\n".join(
                f'<option value="{html.escape(v.lower(), quote=True)}">' f"{html.escape(v)}</option>"
                for v in sorted(values, key=str.casefold)
            )

        html_page = dedent(f"""\
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Ford Family Recipes</title>
                <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
                <link rel="stylesheet" href="{THEME_CSS_PATH}">
                <link rel="stylesheet" href="{INDEX_CSS_PATH}">
                <script defer>
                const initRecipeIndex = () => {{
                    const list = document.querySelector("#recipe-list");
                    const recipes = [...list.querySelectorAll(".recipe")];
                    const search = document.querySelector("#recipe-search");
                    const filters = [
                        ["meals", document.querySelector("#filter-meal")],
                        ["cuisine", document.querySelector("#filter-cuisine")],
                        ["categories", document.querySelector("#filter-category")],
                        ["tags", document.querySelector("#filter-tag")],
                    ];
                    const sort = document.querySelector("#sort-recipes");
                    const count = document.querySelector("#recipe-count");
                    const clearFilters = document.querySelector("#clear-filters");
                    const viewButtons = [...document.querySelectorAll("[data-view]")];

                    const getValues = (recipe, key) =>
                        JSON.parse(recipe.dataset[key] || "[]")
                            .map(value => value.toLowerCase());

                    const compareTitle = (a, b) =>
                        a.dataset.title.localeCompare(
                            b.dataset.title, undefined, {{ sensitivity: "base" }}
                        );

                    const update = () => {{
                        const query = search.value.trim().toLowerCase();
                        const filtering = query !== "" ||
                            filters.some(([, control]) => control.value !== "");
                        const visible = recipes.filter(recipe =>
                            recipe.dataset.search.toLowerCase().includes(query) &&
                            filters.every(([key, control]) =>
                                !control.value ||
                                getValues(recipe, key).includes(control.value)
                            )
                        );

                        const [key, direction] = sort.value.split(":");
                        visible.sort((a, b) => {{
                            if (key === "title") {{
                                return direction === "desc"
                                    ? compareTitle(b, a)
                                    : compareTitle(a, b);
                            }}

                            const aValue = a.dataset[key] === ""
                                ? null : Number(a.dataset[key]);
                            const bValue = b.dataset[key] === ""
                                ? null : Number(b.dataset[key]);
                            if (aValue === null && bValue !== null) return 1;
                            if (bValue === null && aValue !== null) return -1;
                            if (aValue !== bValue) {{
                                return (direction === "desc" ? -1 : 1) *
                                    (aValue - bValue);
                            }}
                            return compareTitle(a, b);
                        }});

                        for (const recipe of visible) {{
                            list.appendChild(recipe);
                            recipe.hidden = false;
                        }}

                        for (const recipe of recipes) {{
                            if (!visible.includes(recipe)) recipe.hidden = true;
                        }}

                        count.textContent =
                            `${{visible.length}} of ${{recipes.length}} recipes`;
                        clearFilters.hidden = !filtering;
                    }};

                    [search, ...filters.map(([, control]) => control), sort]
                        .forEach(control => control.addEventListener(
                            control === search ? "input" : "change", update
                        ));

                    clearFilters.addEventListener("click", () => {{
                        search.value = "";
                        filters.forEach(([, control]) => control.value = "");
                        update();
                        search.focus();
                    }});

                    viewButtons.forEach(button => button.addEventListener("click", () => {{
                        const view = button.dataset.view;
                        list.classList.toggle("list-view", view === "list");
                        viewButtons.forEach(item =>
                            item.setAttribute("aria-pressed", item === button)
                        );
                    }}));

                    update();
                }};

                document.addEventListener("DOMContentLoaded", initRecipeIndex);
                </script>
            </head>
            <body>
                <main class="recipes">
                    <header class="recipes-header">
                        <h1>Ford Family Recipes</h1>
                    </header>

                    <section class="recipe-toolbar" aria-label="Recipe search and filters">
                        <label class="search-control">
                            <span class="visually-hidden">Search recipes</span>
                            <input
                                id="recipe-search"
                                type="search"
                                placeholder="Search recipes, ingredients, tags..."
                                aria-label="Search recipes"
                            >
                        </label>

                        <div class="recipe-filters">
                            <select id="filter-meal" aria-label="Filter by meal">
                                <option value="">All meals</option>
                                {options(all_meals)}
                            </select>

                            <select id="filter-cuisine" aria-label="Filter by cuisine">
                                <option value="">All cuisines</option>
                                {options(all_cuisine)}
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
                                <option value="title:asc">Name: A–Z</option>
                                <option value="title:desc">Name: Z–A</option>
                                <option value="rating:desc">Highest rated</option>
                                <option value="rating:asc">Lowest rated</option>
                                <option value="makes:desc">Makes: most first</option>
                                <option value="makes:asc">Makes: fewest first</option>
                                <option value="difficulty:asc">Easiest first</option>
                                <option value="difficulty:desc">Hardest first</option>
                            </select>
                        </div>
                    </section>

                    <div class="recipe-results-bar">
                        <p id="recipe-count" aria-live="polite"></p>
                        <button id="clear-filters" type="button" hidden>Clear filters</button>
                        <div class="view-switcher" role="group" aria-label="Recipe view">
                            <button type="button" data-view="cards" aria-pressed="true">Cards</button>
                            <button type="button" data-view="list" aria-pressed="false">List</button>
                        </div>
                    </div>

                    <ul id="recipe-list" class="card-view">
                        {"".join(links)}
                    </ul>
                </main>

                <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            </body>
            </html>
        """)

        index_html = self.cfg.site_directory / "index.html"
        index_html.write_text(html_page, encoding="UTF-8", newline="\n")
        logger.debug(f"Created {index_html}")
