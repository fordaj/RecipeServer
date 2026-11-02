import html
import json
import math
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from textwrap import dedent
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .config import Configuration
from ._logger import logger
from .image_handler import get_first_image_in_dir
from .metadata_linter import lint_recipe_metadata

FILE_PATH = Path(__file__)
THEME_CSS_PATH = "/assets/theme.css"
INDEX_CSS_PATH = "/assets/index.css"
INDEX_JS_PATH = "/assets/index.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"
TAG_SVG = FILE_PATH.parent / "assets" / "tag.svg"
PIN_SVG = FILE_PATH.parent / "assets" / "pin.svg"
UTENSILS_SVG = FILE_PATH.parent / "assets" / "utensils.svg"
COOKING_POT_SVG = FILE_PATH.parent / "assets" / "cooking-pot.svg"
QUILL_SVG = FILE_PATH.parent / "assets" / "quill.svg"
CALENDAR_SVG = FILE_PATH.parent / "assets" / "calendar.svg"
BOOK_SVG = FILE_PATH.parent / "assets" / "book.svg"
UP_DOWN_ARROW_SVG = FILE_PATH.parent / "assets" / "up-down-arrow.svg"
USER_SVG = FILE_PATH.parent / "assets" / "user.svg"
AI_SVG = FILE_PATH.parent / "assets" / "ai.svg"
LINK_SVG = FILE_PATH.parent / "assets" / "link.svg"
WARNING_SVG = FILE_PATH.parent / "assets" / "warning.svg"

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
        return IndexHTMLGenerator._icon_path(asset_path)

    @staticmethod
    def _icon_path(asset_path: Path) -> str:
        soup = BeautifulSoup(asset_path.read_text(encoding="UTF-8"), "html.parser")
        icon = soup.find("svg")
        if icon is None:
            raise ValueError(f"No SVG element found in {asset_path}")

        icon["class"] = ["recipe-icon"]
        icon["aria-hidden"] = "true"
        icon["focusable"] = "false"
        return str(icon)

    @staticmethod
    def _contribution_date(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    @staticmethod
    def _updated_date(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _sources(metadata: dict) -> list[dict]:
        sources = metadata.get("source", [])
        if isinstance(sources, dict):
            sources = [sources]
        if not isinstance(sources, list):
            return []
        return [source for source in sources if isinstance(source, dict)]

    @staticmethod
    def _source_title(source: dict) -> str:
        source_format = str(source.get("format", "")).lower()
        if source_format not in {"website", "book"}:
            return ""
        title = source.get("title") or (source.get("company") if source_format == "website" else "")
        return str(title or "").strip()

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

    @classmethod
    def _metadata_detail(cls, icon: Path, label: str, content: str) -> str:
        if not content:
            return ""
        class_name = label.lower().replace(" ", "-")
        return (
            f'<span class="recipe-detail recipe-detail--{class_name}" '
            f'title="{html.escape(label, quote=True)}">'
            f'{cls._icon_path(icon)}<span class="recipe-detail__value">{content}</span></span>'
        )

    @classmethod
    def _warning_detail(
        cls,
        key: str,
        label: str,
        warning: dict,
        icon: Path | None = None,
    ) -> str:
        message = str(warning.get("message") or f"Missing {label}")
        escaped_message = html.escape(message, quote=True)

        icon_html = cls._icon_path(icon) if icon else cls._icon(key)

        return (
            f'<span class="recipe-detail recipe-detail--{key} '
            f'recipe-detail--warning" hidden '
            f'title="{escaped_message}" role="img" '
            f'aria-label="{escaped_message}">'
            f"{icon_html}"
            f'<span class="recipe-detail__value">'
            f'<span class="recipe-chip recipe-warning-chip">'
            f"{cls._icon_path(WARNING_SVG)}"
            f" {html.escape(label)}"
            f"</span></span></span>"
        )

    @classmethod
    def _source_detail(cls, source: dict) -> str:
        source_format = str(source.get("format", "")).lower()
        title = cls._source_title(source)
        if not title:
            return ""

        content = html.escape(title)
        if source_format == "website":
            url = str(source.get("url") or "").strip()
            parsed_url = urlsplit(url)
            if parsed_url.scheme.lower() in {"http", "https"} and parsed_url.netloc:
                content = (
                    f'<a href="{html.escape(url, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer">{content}</a>'
                )

        icon = LINK_SVG if source_format == "website" else BOOK_SVG
        if source_format == "website":
            icon = LINK_SVG
        elif source_format == "book":
            icon = BOOK_SVG
        elif source_format == "ai":
            icon = AI_SVG
        else:  # fallback to person
            icon = USER_SVG
        return cls._metadata_detail(icon, "Source", content)

    def convert(self):
        links: list[str] = []
        all_meals: set[str] = set()
        all_categories: set[str] = set()
        all_tags: set[str] = set()
        all_cuisine: set[str] = set()
        all_contributors: set[str] = set()
        all_source_titles: set[str] = set()

        for recipe in self.recipes:
            metadata = recipe.metadata
            file = recipe.html_file
            metadata_warnings = lint_recipe_metadata(metadata)

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
            contributors = [value.strip() for value in self.values(metadata, "contributor") if value.strip()]
            sources = self._sources(metadata)
            source_titles = [source_title for source in sources if (source_title := self._source_title(source))]

            all_meals.update(meals)
            all_categories.update(categories)
            all_tags.update(tags)
            all_cuisine.update(cuisine)
            all_contributors.update(contributors)
            all_source_titles.update(source_titles)

            search_text = " ".join([title, *meals, *categories, *tags, *cuisine, *contributors, *source_titles])
            average_rating, rating_count = self._average_rating(metadata)
            rating_attribute = f"{average_rating:.6g}" if average_rating is not None else ""
            makes = metadata.get("makes")
            difficulty = metadata.get("difficulty")
            makes_value = str(makes) if isinstance(makes, (int, float)) else ""
            difficulty_value = str(difficulty) if isinstance(difficulty, (int, float)) else ""
            contribution_date = self._contribution_date(metadata.get("createdOn"))
            date_value = contribution_date.isoformat() if contribution_date else ""
            updated_on = self._updated_date(metadata.get("updatedOn"))
            updated_on_value = updated_on.isoformat() if updated_on else ""

            warnings_by_field = {warning["field"]: warning for warning in metadata_warnings}

            def warning_for(*fields: str) -> dict | None:
                return next(
                    (warnings_by_field[field] for field in fields if field in warnings_by_field),
                    None,
                )

            rating_html = ""

            if average_rating is not None and rating_count:
                rating_html = (
                    f'<span class="recipe-rating" role="img" '
                    f'aria-label="Rated {average_rating:.1f} out of 10 '
                    f'from {rating_count} ratings">'
                    f'<span class="recipe-rating__star" aria-hidden="true">★</span>'
                    f'<span class="recipe-rating__score">{average_rating:.1f}/10</span>'
                    f'<span class="recipe-rating__count">({rating_count})</span>'
                    "</span>"
                )
            elif warning := warning_for("ratings", "rating"):
                rating_html = (
                    '<span class="recipe-detail recipe-detail--rating '
                    'recipe-detail--warning" hidden '
                    f'title="{html.escape(warning.get("message") or "Missing rating", quote=True)}" '
                    f'aria-label="{html.escape(warning.get("message") or "Missing rating", quote=True)}">'
                    '<span class="recipe-detail__value">'
                    '<span class="recipe-chip recipe-warning-chip">'
                    f"{self._icon_path(WARNING_SVG)} Rating"
                    "</span></span></span>"
                )
            else:
                rating_html = ""

            image_html = (
                f'<a class="recipe-card__image" href="{html.escape(url, quote=True)}" '
                f'aria-label="View {html.escape(title, quote=True)} recipe">'
                f'<img src="{html.escape(hero_url, quote=True)}" alt="" loading="lazy">'
                "</a>"
                if hero_url
                else ""
            )

            details = "".join(
                (
                    self._detail("makes", "Makes", [f"x{makes_value}"] if makes_value else [])
                    or (self._warning_detail("makes", "Makes", warning) if (warning := warning_for("makes")) else ""),
                    self._detail(
                        "difficulty",
                        "Difficulty",
                        [f"{difficulty_value}/10"] if difficulty_value else [],
                    )
                    or (
                        self._warning_detail("difficulty", "Difficulty", warning)
                        if (warning := warning_for("difficulty"))
                        else ""
                    ),
                    self._detail("meals", "Meals", meals)
                    or (self._warning_detail("meals", "Meals", warning) if (warning := warning_for("meals")) else ""),
                    self._detail("cuisine", "Cuisine", cuisine)
                    or (
                        self._warning_detail("cuisine", "Cuisine", warning)
                        if (warning := warning_for("cuisine"))
                        else ""
                    ),
                    self._detail("categories", "Categories", categories)
                    or (
                        self._warning_detail("categories", "Categories", warning)
                        if (warning := warning_for("categories", "category"))
                        else ""
                    ),
                    self._detail("tags", "Tags", tags)
                    or (self._warning_detail("tags", "Tags", warning) if (warning := warning_for("tags")) else ""),
                    self._metadata_detail(
                        QUILL_SVG,
                        "Contributor",
                        ", ".join(html.escape(value) for value in contributors),
                    )
                    or (
                        self._warning_detail("contributor", "Contributor", warning, QUILL_SVG)
                        if (warning := warning_for("contributor"))
                        else ""
                    ),
                    self._metadata_detail(
                        CALENDAR_SVG,
                        "Contribution date",
                        html.escape(str(contribution_date.year)) if contribution_date else "",
                    )
                    or (
                        self._warning_detail(
                            "contribution-date",
                            "Contribution date",
                            warning,
                            CALENDAR_SVG,
                        )
                        if (warning := warning_for("createdOn", "contribution_date"))
                        else ""
                    ),
                    *(self._source_detail(source) for source in sources if self._source_title(source)),
                    (
                        self._warning_detail("source", "Source", warning, LINK_SVG)
                        if (
                            not any(self._source_title(source) for source in sources)
                            and (warning := warning_for("source"))
                        )
                        else ""
                    ),
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
                f' data-contributors="{self.json_attribute(contributors)}"'
                f' data-source-titles="{self.json_attribute(source_titles)}"'
                f' data-rating="{rating_attribute}"'
                f' data-makes="{makes_value}"'
                f' data-difficulty="{difficulty_value}"'
                f' data-edited="{updated_on_value}"'
                f' data-date="{date_value}">'
                '<article class="recipe-card">'
                f"{image_html}"
                '<div class="recipe-card__heading">'
                f'<h2><a class="recipe-card__link" href="{html.escape(url, quote=True)}">'
                f"{html.escape(title)}</a></h2>"
                "</div>"
                f'<div class="recipe-card__details">{rating_html}{details}</div>'
                "</article>"
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
                <script src="{INDEX_JS_PATH}" defer></script>
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
                            <label class="filter-control">
                                {UTENSILS_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-meal" aria-label="Filter by meal">
                                    <option value="">All meals</option>
                                    {options(all_meals)}
                                </select>
                            </label>

                            <label class="filter-control">
                                {PIN_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-cuisine" aria-label="Filter by cuisine">
                                    <option value="">All cuisines</option>
                                    {options(all_cuisine)}
                                </select>
                            </label>

                            <label class="filter-control">
                                {COOKING_POT_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-category" aria-label="Filter by category">
                                    <option value="">All categories</option>
                                    {options(all_categories)}
                                </select>
                            </label>

                            <label class="filter-control">
                                {TAG_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-tag" aria-label="Filter by tag">
                                    <option value="">All tags</option>
                                    {options(all_tags)}
                                </select>
                            </label>

                            <label class="filter-control">
                                {QUILL_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-contributor" aria-label="Filter by contributor">
                                    <option value="">All contributors</option>
                                    {options(all_contributors)}
                                </select>
                            </label>

                            <label class="filter-control">
                                {BOOK_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="filter-source-title" aria-label="Filter by source title">
                                    <option value="">All source titles</option>
                                    {options(all_source_titles)}
                                </select>
                            </label>


                            <label class="filter-control">
                                {UP_DOWN_ARROW_SVG.read_text(encoding="UTF-8", newline="\n")}
                                <select id="sort-recipes" aria-label="Sort recipes">
                                    <option value="title:asc">Name: A–Z</option>
                                    <option value="title:desc">Name: Z–A</option>
                                    <option value="rating:desc">Highest rated</option>
                                    <option value="rating:asc">Lowest rated</option>
                                    <option value="makes:desc">Makes: most first</option>
                                    <option value="makes:asc">Makes: fewest first</option>
                                    <option value="difficulty:asc">Easiest first</option>
                                    <option value="difficulty:desc">Hardest first</option>
                                    <option value="date:desc">Contribution date: newest first</option>
                                    <option value="date:asc">Contribution date: oldest first</option>
                                    <option value="edited:desc">Last edit: newest first</option>
                                    <option value="edited:asc">Last edit: oldest first</option>
                                </select>
                            </label>
                        </div>

                        <details class="recipe-advanced">
                            <summary>
                                <span>Advanced</span>
                            </summary>

                            <div class="recipe-advanced__content">
                                <label class="metadata-status-toggle">
                                    <input
                                        id="metadata-status"
                                        type="checkbox"
                                        aria-controls="recipe-list"
                                    >
                                    <span>Metadata Status</span>
                                </label>
                            </div>
                        </details>
                    </section>

                    <div class="recipe-results-bar">
                        <p id="recipe-count" aria-live="polite"></p>
                        <button id="clear-filters" type="button" hidden>Clear filters</button>
                        <div class="view-switcher" role="group" aria-label="Recipe view">
                            <button type="button" data-view="list" aria-pressed="true">List</button>
                            <button type="button" data-view="cards" aria-pressed="false">Cards</button>
                        </div>
                    </div>

                    <ul id="recipe-list" class="list-view">
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
