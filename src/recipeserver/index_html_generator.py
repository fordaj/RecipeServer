import hashlib
import html
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from textwrap import dedent
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ._logger import logger
from .config import DEFAULT_RECIPE_SERVER_NAME, Configuration
from .image_handler import get_first_image_in_dir
from .menu import MENU_CSS_URL, MENU_JS_URL, sandwich_menu_html
from .metadata_linter import lint_recipe_metadata
from .recipe_utils import (
    iter_valid_rating_entries,
    normalize_reviewer_name,
    parse_metadata_datetime,
)

FILE_PATH = Path(__file__)
ASSETS_DIR = FILE_PATH.parent / "assets"

# ----- Asset paths and URLs ----- #
DEFINITIONS_CSS_PATH = "/assets/definitions.css"
INDEX_CSS_PATH = "/assets/index.css"
INDEX_JS_PATH = "/assets/index.js"
RECIPE_EDITOR_CSS_PATH = "/assets/recipe-editor/recipe-editor.css"
RECIPE_EDITOR_JS_PATH = "/assets/recipe-editor/recipe-editor.js"
CONFIG_EDITOR_CSS_PATH = "/assets/config-editor.css"
CONFIG_EDITOR_JS_PATH = "/assets/config-editor.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

# Inline SVG icons read from the assets directory.
TAG_SVG = ASSETS_DIR / "tag.svg"
PIN_SVG = ASSETS_DIR / "pin.svg"
UTENSILS_SVG = ASSETS_DIR / "utensils.svg"
COOKING_POT_SVG = ASSETS_DIR / "cooking-pot.svg"
QUILL_SVG = ASSETS_DIR / "quill.svg"
CALENDAR_SVG = ASSETS_DIR / "calendar.svg"
BOOK_SVG = ASSETS_DIR / "book.svg"
UP_DOWN_ARROW_SVG = ASSETS_DIR / "up-down-arrow.svg"
USER_SVG = ASSETS_DIR / "user.svg"
AI_SVG = ASSETS_DIR / "ai.svg"
LINK_SVG = ASSETS_DIR / "link.svg"
WARNING_SVG = ASSETS_DIR / "warning.svg"
PLUS_SVG = ASSETS_DIR / "plus.svg"

# Detail kinds that render with a mapped asset icon.
_DETAIL_ICON_URLS = {
    "makes": "/assets/chef-hat.svg",
    "difficulty": "/assets/gauge.svg",
    "meals": "/assets/utensils.svg",
    "categories": "/assets/cooking-pot.svg",
    "tags": "/assets/tag.svg",
    "cuisine": "/assets/pin.svg",
}

# Maximum number of reviewers shown in the review filter.
MAX_REVIEW_FILTER_OPTIONS = 30

# Source formats that show an explicit title in the card details.
TITLED_SOURCE_FORMATS = {"website", "book"}


def _versioned_asset_url(url: str) -> str:
    """Append a content hash so browsers pick up changed assets."""
    relative = url.removeprefix("/assets/")
    asset_path = ASSETS_DIR / relative
    digest = hashlib.sha1(asset_path.read_bytes()).hexdigest()[:10]
    return f"{url}?v={digest}"


DEFINITIONS_CSS_URL = _versioned_asset_url(DEFINITIONS_CSS_PATH)
INDEX_CSS_URL = _versioned_asset_url(INDEX_CSS_PATH)
INDEX_JS_URL = _versioned_asset_url(INDEX_JS_PATH)
RECIPE_EDITOR_CSS_URL = _versioned_asset_url(RECIPE_EDITOR_CSS_PATH)
RECIPE_EDITOR_JS_URL = _versioned_asset_url(RECIPE_EDITOR_JS_PATH)
CONFIG_EDITOR_CSS_URL = _versioned_asset_url(CONFIG_EDITOR_CSS_PATH)
CONFIG_EDITOR_JS_URL = _versioned_asset_url(CONFIG_EDITOR_JS_PATH)


class Recipe:
    """Recipe metadata and the generated HTML page it came from."""

    def __init__(self, metadata: dict, html_file: Path, title: str | None = None):
        self.metadata = metadata
        self.html_file = html_file
        self.title = title


class IndexHTMLGenerator:
    """Build the searchable recipe index page."""

    def __init__(self, cfg: Configuration):
        self.recipes: list[Recipe] = []
        self.cfg = cfg

    def add(self, recipe: Recipe) -> None:
        self.recipes.append(recipe)

    # ----- Metadata helpers ----- #

    @staticmethod
    def title_from_slug(slug: str) -> str:
        return slug.replace("-", " ").title()

    @staticmethod
    def collect_metadata_values(metadata: dict, *keys: str) -> list[str]:
        """Return metadata values consistently as a deduplicated string list."""
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
    def serialize_for_html_attribute(value: list[object]) -> str:
        """Serialize a list safely for an HTML attribute."""
        return html.escape(json.dumps(value), quote=True)

    @staticmethod
    def _reviewer_key(name: str) -> str:
        return normalize_reviewer_name(name)

    @staticmethod
    def _valid_ratings(metadata: dict) -> list[tuple[str, int | float]]:
        return list(iter_valid_rating_entries(metadata.get("ratings", [])))

    @classmethod
    def _average_rating(cls, metadata: dict) -> tuple[float | None, int]:
        scores = [score for _, score in cls._valid_ratings(metadata)]
        return (mean(scores), len(scores)) if scores else (None, 0)

    @staticmethod
    def _contribution_date(value: object) -> date | None:
        parsed = parse_metadata_datetime(value)
        return parsed.date() if parsed else None

    @staticmethod
    def _updated_date(value: object) -> datetime | None:
        return parse_metadata_datetime(value)

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
        if source_format not in TITLED_SOURCE_FORMATS:
            return ""
        title = source.get("title") or (source.get("company") if source_format == "website" else "")
        return str(title or "").strip()

    @staticmethod
    def _warning_for(warnings_by_field: dict[str, dict], *fields: str) -> dict | None:
        for field in fields:
            warning = warnings_by_field.get(field)
            if warning is not None:
                return warning
        return None

    # ----- Icon rendering ----- #

    @classmethod
    def _icon_for_detail(cls, detail_kind: str) -> str:
        asset_url = _DETAIL_ICON_URLS[detail_kind]
        return cls._svg_icon(ASSETS_DIR / Path(asset_url).name)

    @staticmethod
    @lru_cache(maxsize=None)
    def _svg_icon(asset_path: Path) -> str:
        soup = BeautifulSoup(asset_path.read_text(encoding="UTF-8"), "html.parser")
        icon = soup.find("svg")
        if icon is None:
            raise ValueError(f"No SVG element found in {asset_path}")

        icon["class"] = ["recipe-icon"]
        icon["aria-hidden"] = "true"
        icon["focusable"] = "false"
        return str(icon)

    @staticmethod
    def _source_icon(source_format: str) -> Path:
        if source_format == "website":
            return LINK_SVG
        if source_format == "book":
            return BOOK_SVG
        if source_format == "ai":
            return AI_SVG
        return USER_SVG

    # ----- Card detail fragments ----- #

    @classmethod
    def _detail_html(cls, detail_kind: str, label: str, values: list[str]) -> str:
        if not values:
            return ""

        tooltip = html.escape(f"{label}: {', '.join(values)}", quote=True)
        if detail_kind in {"makes", "difficulty"}:
            content = html.escape(", ".join(values))
        else:
            content = "".join(f'<span class="recipe-chip">{html.escape(value)}</span>' for value in values)

        return (
            f'<span class="recipe-detail recipe-detail--{detail_kind}" '
            f'role="img" aria-label="{tooltip}" title="{tooltip}">'
            f'{cls._icon_for_detail(detail_kind)}<span class="recipe-detail__value">'
            f"{content}</span></span>"
        )

    @classmethod
    def _metadata_detail_html(cls, icon_path: Path, label: str, content: str) -> str:
        if not content:
            return ""

        class_name = label.lower().replace(" ", "-")
        return (
            f'<span class="recipe-detail recipe-detail--{class_name}" '
            f'title="{html.escape(label, quote=True)}">'
            f'{cls._svg_icon(icon_path)}<span class="recipe-detail__value">'
            f"{content}</span></span>"
        )

    @classmethod
    def _warning_detail_html(
        cls,
        detail_kind: str,
        label: str,
        warning: dict,
        icon_path: Path | None = None,
    ) -> str:
        message = str(warning.get("message") or f"Missing {label}")
        escaped_message = html.escape(message, quote=True)
        icon_html = cls._svg_icon(icon_path) if icon_path else cls._icon_for_detail(detail_kind)

        return (
            f'<span class="recipe-detail recipe-detail--{detail_kind} '
            f'recipe-detail--warning" hidden '
            f'title="{escaped_message}" role="img" '
            f'aria-label="{escaped_message}">'
            f"{icon_html}"
            f'<span class="recipe-detail__value">'
            f'<span class="recipe-chip recipe-warning-chip">'
            f"{cls._svg_icon(WARNING_SVG)}"
            f" {html.escape(label)}"
            f"</span></span></span>"
        )

    @classmethod
    def _detail_with_warning(
        cls,
        detail_kind: str,
        label: str,
        values: list[str],
        warning_fields: tuple[str, ...],
        warnings_by_field: dict[str, dict],
        icon_path: Path | None = None,
    ) -> str:
        if icon_path is None:
            detail = cls._detail_html(detail_kind, label, values)
        else:
            escaped_content = ", ".join(html.escape(value) for value in values)
            detail = cls._metadata_detail_html(icon_path, label, escaped_content)

        if detail:
            return detail

        warning = cls._warning_for(warnings_by_field, *warning_fields)
        if warning is None:
            return ""
        return cls._warning_detail_html(detail_kind, label, warning, icon_path)

    @classmethod
    def _rating_html(cls, average_rating: float | None, rating_count: int, warning: dict | None) -> str:
        if average_rating is not None and rating_count:
            return (
                f'<span class="recipe-rating" role="img" '
                f'aria-label="Rated {average_rating:.1f} out of 10 '
                f'from {rating_count} ratings">'
                f'<span class="recipe-rating__star" aria-hidden="true">★</span>'
                f'<span class="recipe-rating__score">{average_rating:.1f}/10</span>'
                f'<span class="recipe-rating__count">({rating_count})</span>'
                "</span>"
            )

        if warning is not None:
            message = html.escape(str(warning.get("message") or "Missing rating"), quote=True)
            return (
                '<span class="recipe-detail recipe-detail--rating '
                'recipe-detail--warning" hidden '
                f'title="{message}" aria-label="{message}">'
                '<span class="recipe-detail__value">'
                '<span class="recipe-chip recipe-warning-chip">'
                f"{cls._svg_icon(WARNING_SVG)} Ratings"
                "</span></span></span>"
            )

        return ""

    @classmethod
    def _source_detail_html(cls, source: dict) -> str:
        source_format = str(source.get("format", "")).lower()
        title = cls._source_title(source)
        if not title:
            return ""

        content = html.escape(title)
        if source_format == "website":
            url = str(source.get("url") or "").strip()
            parsed_url = urlsplit(url)
            is_http_url = parsed_url.scheme.lower() in {"http", "https"} and parsed_url.netloc
            if is_http_url:
                content = (
                    f'<a href="{html.escape(url, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer">{content}</a>'
                )

        return cls._metadata_detail_html(cls._source_icon(source_format), "Source", content)

    # ----- Per-recipe data ----- #

    def _resolve_title(self, recipe: Recipe, html_path: Path, metadata: dict) -> str:
        if recipe.title:
            return recipe.title

        if html_path.exists():
            recipe_page = BeautifulSoup(html_path.read_text(encoding="UTF-8"), "html.parser")
            heading = recipe_page.find("h1")
            heading_title = heading.get_text(" ", strip=True) if heading else ""
            if heading_title:
                return heading_title

        return str(metadata.get("title") or self.title_from_slug(html_path.parent.name))

    def _build_recipe_item(self, recipe: Recipe, filter_values: dict[str, set[str]]) -> str:
        metadata = recipe.metadata
        html_path = recipe.html_file
        metadata_warnings = lint_recipe_metadata(metadata)
        warnings_by_field = {warning["field"]: warning for warning in metadata_warnings}

        relative_path = html_path.relative_to(self.cfg.site_directory)
        url = "/" + relative_path.as_posix()
        markdown_path = relative_path.with_suffix(".md").as_posix()

        title = self._resolve_title(recipe, html_path, metadata)
        hero_image = get_first_image_in_dir(html_path.parent) if html_path.parent.is_dir() else None
        hero_url = "/" + hero_image.relative_to(self.cfg.site_directory).as_posix() if hero_image else ""

        # ----- Collect filterable metadata values ----- #
        meals = self.collect_metadata_values(metadata, "meals")
        categories = self.collect_metadata_values(metadata, "categories", "category")
        tags = self.collect_metadata_values(metadata, "tags")
        cuisine = self.collect_metadata_values(metadata, "cuisine")
        contributors = [
            value.strip() for value in self.collect_metadata_values(metadata, "contributor") if value.strip()
        ]
        sources = self._sources(metadata)
        source_titles = [source_title for source in sources if (source_title := self._source_title(source))]

        filter_values["meals"].update(meals)
        filter_values["categories"].update(categories)
        filter_values["tags"].update(tags)
        filter_values["cuisine"].update(cuisine)
        filter_values["contributors"].update(contributors)
        filter_values["source_titles"].update(source_titles)

        # ----- Compute sort and search attributes ----- #
        search_text = " ".join([title, *meals, *categories, *tags, *cuisine, *contributors, *source_titles])
        reviewer_ratings = [
            {"name": self._reviewer_key(name) if name else "", "rating": score}
            for name, score in self._valid_ratings(metadata)
        ]
        average_rating, rating_count = self._average_rating(metadata)
        rating_attribute = f"{average_rating:.6g}" if average_rating is not None else ""

        makes = metadata.get("makes")
        difficulty = metadata.get("difficulty")
        makes_value = str(makes) if isinstance(makes, (int, float)) else ""
        difficulty_value = str(difficulty) if isinstance(difficulty, (int, float)) else ""

        contribution_date = self._contribution_date(metadata.get("createdOn"))
        updated_on = self._updated_date(metadata.get("updatedOn"))
        date_value = contribution_date.isoformat() if contribution_date else ""
        updated_on_value = updated_on.isoformat() if updated_on else ""

        # ----- Render card fragments ----- #
        rating_html = self._rating_html(
            average_rating,
            rating_count,
            self._warning_for(warnings_by_field, "ratings", "rating"),
        )

        select_html = (
            '<label class="recipe-select" hidden>'
            f'<input type="checkbox" class="recipe-select__checkbox" '
            f'data-path="{html.escape(markdown_path, quote=True)}"'
            f' aria-label="Select {html.escape(title, quote=True)} for bulk editing">'
            '<span class="recipe-select__box" aria-hidden="true"></span>'
            "</label>"
        )

        image_html = (
            f'<a class="recipe-card__image" href="{html.escape(url, quote=True)}" '
            f'aria-label="View {html.escape(title, quote=True)} recipe">'
            f'<img src="{html.escape(hero_url, quote=True)}" alt="" loading="lazy">'
            "</a>"
            if hero_url
            else ""
        )

        details_html = self._build_card_details(
            makes_value=makes_value,
            difficulty_value=difficulty_value,
            meals=meals,
            cuisine=cuisine,
            categories=categories,
            tags=tags,
            contributors=contributors,
            contribution_date=contribution_date,
            sources=sources,
            warnings_by_field=warnings_by_field,
        )

        return (
            f'<li class="recipe"'
            f' data-path="{html.escape(markdown_path, quote=True)}"'
            f' data-title="{html.escape(title, quote=True)}"'
            f' data-search="{html.escape(search_text, quote=True)}"'
            f' data-meals="{self.serialize_for_html_attribute(meals)}"'
            f' data-categories="{self.serialize_for_html_attribute(categories)}"'
            f' data-tags="{self.serialize_for_html_attribute(tags)}"'
            f' data-cuisine="{self.serialize_for_html_attribute(cuisine)}"'
            f' data-contributors="{self.serialize_for_html_attribute(contributors)}"'
            f' data-source-titles="{self.serialize_for_html_attribute(source_titles)}"'
            f' data-ratings="{self.serialize_for_html_attribute(reviewer_ratings)}"'
            f' data-rating="{rating_attribute}"'
            f' data-makes="{makes_value}"'
            f' data-difficulty="{difficulty_value}"'
            f' data-edited="{updated_on_value}"'
            f' data-date="{date_value}">'
            '<article class="recipe-card">'
            f"{select_html}"
            f"{image_html}"
            '<div class="recipe-card__heading">'
            f'<h2><a class="recipe-card__link" href="{html.escape(url, quote=True)}">'
            f"{html.escape(title)}</a></h2>"
            "</div>"
            f'<div class="recipe-card__details">{rating_html}{details_html}</div>'
            "</article>"
            "</li>"
        )

    def _build_card_details(
        self,
        *,
        makes_value: str,
        difficulty_value: str,
        meals: list[str],
        cuisine: list[str],
        categories: list[str],
        tags: list[str],
        contributors: list[str],
        contribution_date: date | None,
        sources: list[dict],
        warnings_by_field: dict[str, dict],
    ) -> str:
        parts: list[str] = [
            self._detail_with_warning(
                "makes",
                "Makes",
                [f"x{makes_value}"] if makes_value else [],
                ("makes",),
                warnings_by_field,
            ),
            self._detail_with_warning(
                "difficulty",
                "Difficulty",
                [f"{difficulty_value}/10"] if difficulty_value else [],
                ("difficulty",),
                warnings_by_field,
            ),
            self._detail_with_warning("meals", "Meals", meals, ("meals",), warnings_by_field),
            self._detail_with_warning("cuisine", "Cuisine", cuisine, ("cuisine",), warnings_by_field),
            self._detail_with_warning(
                "categories",
                "Categories",
                categories,
                ("categories", "category"),
                warnings_by_field,
            ),
            self._detail_with_warning("tags", "Tags", tags, ("tags",), warnings_by_field),
            self._detail_with_warning(
                "contributor",
                "Contributor",
                contributors,
                ("contributor",),
                warnings_by_field,
                icon_path=QUILL_SVG,
            ),
            self._detail_with_warning(
                "contribution-date",
                "Contribution date",
                [str(contribution_date.year)] if contribution_date else [],
                ("createdOn", "contribution_date"),
                warnings_by_field,
                icon_path=CALENDAR_SVG,
            ),
        ]

        # Titled sources render as individual details; warn only when none exist.
        titled_sources = [self._source_detail_html(source) for source in sources if self._source_title(source)]
        parts.extend(titled_sources)
        if not titled_sources:
            source_warning = self._warning_for(warnings_by_field, "source")
            if source_warning is not None:
                parts.append(self._warning_detail_html("source", "Source", source_warning, LINK_SVG))

        return "".join(parts)

    # ----- Aggregation and page rendering ----- #

    def _aggregate_reviewers(self) -> list[tuple[str, int, str]]:
        reviewer_names: dict[str, str] = {}
        reviewer_counts: dict[str, int] = {}

        for recipe in self.recipes:
            for name, _ in self._valid_ratings(recipe.metadata):
                if not name:
                    continue
                key = self._reviewer_key(name)
                reviewer_counts[key] = reviewer_counts.get(key, 0) + 1
                reviewer_names.setdefault(key, name)

        ranked = sorted(
            reviewer_counts.items(),
            key=lambda item: (-item[1], reviewer_names[item[0]].casefold()),
        )
        return [(key, count, reviewer_names[key]) for key, count in ranked[:MAX_REVIEW_FILTER_OPTIONS]]

    @staticmethod
    def _build_select_options_html(values: set[str]) -> str:
        return "\n".join(
            f'<option value="{html.escape(value.lower(), quote=True)}">' f"{html.escape(value)}</option>"
            for value in sorted(values, key=str.casefold)
        )

    @staticmethod
    def _build_reviewer_options_html(
        reviewer_entries: list[tuple[str, int, str]],
    ) -> str:
        options: list[str] = []
        for key, count, display_name in reviewer_entries:
            options.append(
                '<label class="review-filter__option">'
                '<input type="checkbox" class="filter-reviews"'
                f' value="{html.escape(key, quote=True)}">'
                f"<span>{html.escape(display_name)}</span>"
                f'<span class="review-filter__count">{count}</span>'
                "</label>"
            )
        return "\n".join(options)

    def _server_name(self) -> str:
        return (
            str(getattr(self.cfg, "recipe_server_name", "") or "").strip()
            or str(getattr(self.cfg, "server_name", "") or "").strip()
            or DEFAULT_RECIPE_SERVER_NAME
        )

    @staticmethod
    def _inline_svg(icon_path: Path) -> str:
        return icon_path.read_text(encoding="UTF-8", newline="\n")

    def _render_page(
        self,
        *,
        recipe_items_html: str,
        filter_values: dict[str, set[str]],
        reviewer_options_html: str,
    ) -> str:
        server_name_html = html.escape(self._server_name())
        meal_options = self._build_select_options_html(filter_values["meals"])
        cuisine_options = self._build_select_options_html(filter_values["cuisine"])
        category_options = self._build_select_options_html(filter_values["categories"])
        tag_options = self._build_select_options_html(filter_values["tags"])
        contributor_options = self._build_select_options_html(filter_values["contributors"])
        source_title_options = self._build_select_options_html(filter_values["source_titles"])

        return dedent(f"""\
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{server_name_html}</title>
                <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
                <link rel="stylesheet" href="{DEFINITIONS_CSS_URL}">
                <link rel="stylesheet" href="{MENU_CSS_URL}">
                <link rel="stylesheet" href="{INDEX_CSS_URL}">
                <link rel="stylesheet" href="{RECIPE_EDITOR_CSS_URL}">
                <link rel="stylesheet" href="{CONFIG_EDITOR_CSS_URL}">
                <script src="{MENU_JS_URL}" defer></script>
                <script src="{INDEX_JS_URL}" defer></script>
                <script src="{RECIPE_EDITOR_JS_URL}" defer></script>
                <script src="{CONFIG_EDITOR_JS_URL}" defer></script>
            </head>
            <body>
                <main class="recipes">
                    <header class="recipes-header">
                        {sandwich_menu_html()}
                        <h1>{server_name_html}</h1>
                        <button id="create-recipe" class="create-recipe" type="button"
                            aria-label="Create recipe" title="Create recipe">
                            {self._inline_svg(PLUS_SVG)}
                        </button>
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
                                {self._inline_svg(UTENSILS_SVG)}
                                <select id="filter-meal" aria-label="Filter by meal">
                                    <option value="">All meals</option>
                                    {meal_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(PIN_SVG)}
                                <select id="filter-cuisine" aria-label="Filter by cuisine">
                                    <option value="">All cuisines</option>
                                    {cuisine_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(COOKING_POT_SVG)}
                                <select id="filter-category" aria-label="Filter by category">
                                    <option value="">All categories</option>
                                    {category_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(TAG_SVG)}
                                <select id="filter-tag" aria-label="Filter by tag">
                                    <option value="">All tags</option>
                                    {tag_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(QUILL_SVG)}
                                <select id="filter-contributor" aria-label="Filter by contributor">
                                    <option value="">All contributors</option>
                                    {contributor_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(BOOK_SVG)}
                                <select id="filter-source-title" aria-label="Filter by source title">
                                    <option value="">All source titles</option>
                                    {source_title_options}
                                </select>
                            </label>

                            <label class="filter-control">
                                {self._inline_svg(UP_DOWN_ARROW_SVG)}
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
                                <details class="filter-control review-filter" id="review-filter">
                                    <summary>
                                        {self._inline_svg(USER_SVG)}
                                        <span id="review-filter-label">Filter Reviews: All</span>
                                    </summary>

                                    <fieldset class="review-filter__menu">
                                        <legend class="visually-hidden">Filter Reviews</legend>
                                        <label class="review-filter__option">
                                            <input type="checkbox" id="filter-reviews-all" checked>
                                            <span>All reviews</span>
                                        </label>
                                        {reviewer_options_html}
                                    </fieldset>
                                </details>

                                <label class="metadata-status-toggle">
                                    <input
                                        id="metadata-status"
                                        type="checkbox"
                                        aria-controls="recipe-list"
                                    >
                                    <span>Metadata Status</span>
                                </label>

                                <label class="metadata-status-toggle bulk-selection-toggle">
                                    <input
                                        id="bulk-selection-mode"
                                        type="checkbox"
                                        aria-controls="recipe-list bulk-controls"
                                    >
                                    <span>Selection Mode</span>
                                </label>
                            </div>
                        </details>
                    </section>

                    <div class="recipe-results-bar">
                        <p id="recipe-count" aria-live="polite"></p>
                        <div id="bulk-controls" class="bulk-controls" hidden>
                            <span id="bulk-selection-count" aria-live="polite">0 selected</span>
                            <button id="clear-selections" type="button">Clear Selections</button>
                            <button id="bulk-delete" class="bulk-delete" type="button" disabled>Delete Selected</button>
                            <button id="bulk-edit" class="bulk-edit" type="button" disabled>Bulk Edit</button>
                        </div>
                        <button id="clear-filters" type="button" hidden>Clear filters</button>
                        <div class="view-switcher" role="group" aria-label="Recipe view">
                            <button type="button" data-view="list" aria-pressed="true">List</button>
                            <button type="button" data-view="cards" aria-pressed="false">Cards</button>
                        </div>
                    </div>

                    <ul id="recipe-list" class="list-view">
                        {recipe_items_html}
                    </ul>
                </main>

                <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            </body>
            </html>
        """)

    # ----- Entry point ----- #

    def convert(self) -> None:
        """Generate index.html from the collected recipes."""
        filter_values: dict[str, set[str]] = {
            "meals": set(),
            "categories": set(),
            "tags": set(),
            "cuisine": set(),
            "contributors": set(),
            "source_titles": set(),
        }

        reviewer_entries = self._aggregate_reviewers()
        recipe_items = [self._build_recipe_item(recipe, filter_values) for recipe in self.recipes]

        page_html = self._render_page(
            recipe_items_html="".join(recipe_items),
            filter_values=filter_values,
            reviewer_options_html=self._build_reviewer_options_html(reviewer_entries),
        )

        index_html = self.cfg.site_directory / "index.html"
        index_html.write_text(page_html, encoding="UTF-8", newline="\n")
        logger.debug(f"Created {index_html}")
