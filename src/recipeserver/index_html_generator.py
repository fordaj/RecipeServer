import html
import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from textwrap import dedent
from typing import NamedTuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ._logger import logger
from ._version import PACKAGE_VERSION as VERSION, versioned_asset_url
from .color_utils import dark_mode_color
from .config import DEFAULT_FOOD_COLOR, DEFAULT_RECIPE_SERVER_NAME, Configuration
from .image_handler import get_first_image_in_dir
from .menu import MENU_CSS_URL, MENU_JS_URL, sandwich_menu_html
from .metadata_linter import lint_recipe_metadata
from .recipe_utils import (
    iter_valid_rating_entries,
    meta_time_html,
    normalize_reviewer_name,
    parse_metadata_datetime,
    slug_to_title,
)
from .sources import TITLED_SOURCE_FORMATS, normalize_sources, source_format, source_icon_key, source_title

FILE_PATH = Path(__file__)
ASSETS_DIR = FILE_PATH.parent / "assets"

TIME_JS_PATH = "/assets/time.js"
ICONS_JS_PATH = "/assets/icons.js"

# ----- Asset paths and URLs ----- #
DEFINITIONS_CSS_PATH = "/assets/definitions.css"
INDEX_CSS_PATH = "/assets/index.css"
INDEX_JS_PATH = "/assets/index.js"
RECIPE_EDITOR_CSS_PATH = "/assets/recipe-editor/recipe-editor.css"
RECIPE_EDITOR_JS_PATH = "/assets/recipe-editor/recipe-editor.js"
METADATA_PICKER_JS_PATH = "/assets/recipe-editor/metadata-picker.js"
AI_PROGRESS_JS_PATH = "/assets/recipe-editor/ai-progress.js"
SHOPPING_LIST_CSS_PATH = "/assets/shopping-list/shopping-list.css"
SHOPPING_LIST_JS_PATH = "/assets/shopping-list/shopping-list.js"
RECIPE_SCALER_CSS_PATH = "/assets/recipe-scaler.css"
RECIPE_SCALER_JS_PATH = "/assets/recipe-scaler.js"
CONFIG_EDITOR_CSS_PATH = "/assets/config-editor.css"
CONFIG_EDITOR_JS_PATH = "/assets/config-editor.js"
PULL_DOWN_PAGE_REFRESH_CSS_PATH = "/assets/pull-down-page-refresh.css"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

# Inline SVG icons read from the assets directory.
CHEF_HAT_SVG = ASSETS_DIR / "chef-hat.svg"
GAUGE_SVG = ASSETS_DIR / "gauge.svg"
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
ARCHIVE_SVG = ASSETS_DIR / "archive.svg"
INFO_SVG = ASSETS_DIR / "info.svg"
SHOPPING_CART_SVG = ASSETS_DIR / "shopping-cart.svg"
PENCIL_SVG = ASSETS_DIR / "pencil.svg"

# Detail kinds that render with a mapped asset icon.
_DETAIL_ICON_PATHS = {
    "makes": CHEF_HAT_SVG,
    "difficulty": GAUGE_SVG,
    "meals": UTENSILS_SVG,
    "categories": COOKING_POT_SVG,
    "tags": TAG_SVG,
    "cuisine": PIN_SVG,
    "archived": ARCHIVE_SVG,
    "status": INFO_SVG,
}

# Weight of the food color in the hover/dark-mode color-mix() declarations.
FOOD_COLOR_HOVER_MIX_PERCENT = 82

# Maximum number of reviewers shown in the review filter.
MAX_REVIEW_FILTER_OPTIONS = 30


class FilterField(NamedTuple):
    """One multi-select filter in the Advanced section, in display order.

    ``key`` is the recipe list's ``data-*`` attribute name and the key used for
    the filter's option counts; ``icon_path`` is the inline SVG asset; the rest
    label the control for sighted and assistive-technology users.
    """

    key: str
    label: str
    icon_path: Path
    control_id: str
    legend: str
    all_label: str


FILTER_FIELDS = (
    FilterField("meals", "Meals", UTENSILS_SVG, "filter-meal", "Filter by meal", "All meals"),
    FilterField("cuisine", "Cuisine", PIN_SVG, "filter-cuisine", "Filter by cuisine", "All cuisines"),
    FilterField("status", "Status", INFO_SVG, "filter-status", "Filter by status", "All statuses"),
    FilterField("categories", "Categories", COOKING_POT_SVG, "filter-category", "Filter by category", "All categories"),
    FilterField("tags", "Tags", TAG_SVG, "filter-tag", "Filter by tag", "All tags"),
    FilterField("contributors", "Contributors", QUILL_SVG, "filter-contributor", "Filter by contributor", "All contributors"),
    FilterField("sourceTitles", "Source Titles", BOOK_SVG, "filter-source-title", "Filter by source title", "All source titles"),
)

# Index cards show an explicit "Source" detail only for TITLED_SOURCE_FORMATS.
_SOURCE_ICON_PATHS = {"website": LINK_SVG, "book": BOOK_SVG, "ai": AI_SVG, "user": USER_SVG}


@dataclass
class FilterValue:
    """A filter option's display label and the number of recipes that use it."""

    label: str
    count: int = 0


# Filter option counts keyed by filter key, then option key (lower-cased value).
FilterValuesByField = dict[str, dict[str, FilterValue]]


@dataclass
class _RecipeCard:
    """Everything computed for one recipe card, ready to render."""

    url: str
    markdown_path: str
    title: str
    hero_url: str
    archived: bool
    search_text: str
    meals: list[str]
    categories: list[str]
    tags: list[str]
    cuisine: list[str]
    status: list[str]
    contributors: list[str]
    source_titles: list[str]
    sources: list[dict]
    reviewer_ratings: list[dict]
    average_rating: float | None
    rating_count: int
    rating_attribute: str
    makes_value: str
    difficulty_value: str
    contribution_date: date | None
    updated_on_value: str
    date_value: str
    warnings_by_field: dict[str, dict]


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
    def _valid_ratings(metadata: dict) -> list[tuple[str, int | float]]:
        return list(iter_valid_rating_entries(metadata.get("ratings", [])))

    @classmethod
    def _average_rating(cls, metadata: dict) -> tuple[float | None, int]:
        scores = [score for _, score in cls._valid_ratings(metadata)]
        return (mean(scores), len(scores)) if scores else (None, 0)

    def _latest_updated_on(self) -> tuple[datetime | None, object]:
        latest: datetime | None = None
        latest_raw: object = None
        for recipe in self.recipes:
            raw = recipe.metadata.get("updatedOn")
            parsed = parse_metadata_datetime(raw)
            if parsed is not None and (latest is None or parsed > latest):
                latest = parsed
                latest_raw = raw
        return latest, latest_raw

    def _version_footer_html(self) -> str:
        latest, latest_raw = self._latest_updated_on()
        icon = self._svg_icon(TAG_SVG)
        label = f"v{VERSION}"
        if latest is not None:
            label += meta_time_html(latest_raw, "Edited ") or ""
        return f'<footer class="recipe-version" aria-label="App version">{icon}<span>{label}</span></footer>'

    @staticmethod
    def _source_title(source: dict) -> str:
        if source_format(source) not in TITLED_SOURCE_FORMATS:
            return ""
        return source_title(source)

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
        return cls._svg_icon(_DETAIL_ICON_PATHS[detail_kind])

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
    def _warning_chip_html(cls, label: str) -> str:
        """Warning chip shown in place of a missing required value."""
        return f'<span class="recipe-chip recipe-warning-chip">{cls._svg_icon(WARNING_SVG)} {html.escape(label)}</span>'

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
        if icon_path is None:
            icon_path = _DETAIL_ICON_PATHS.get(detail_kind)
        icon_html = cls._svg_icon(icon_path) if icon_path is not None else ""

        return (
            f'<span class="recipe-detail recipe-detail--{detail_kind} '
            f'recipe-detail--warning" hidden '
            f'title="{escaped_message}" role="img" '
            f'aria-label="{escaped_message}">'
            f"{icon_html}"
            f'<span class="recipe-detail__value">'
            f"{cls._warning_chip_html(label)}"
            f"</span></span>"
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
            return cls._warning_detail_html("rating", "Ratings", warning)

        return ""

    @classmethod
    def _source_detail_html(cls, source: dict) -> str:
        fmt = source_format(source)
        title = cls._source_title(source)
        if not title:
            return ""

        content = html.escape(title)
        if fmt == "website":
            url = str(source.get("url") or "").strip()
            parsed_url = urlsplit(url)
            is_http_url = parsed_url.scheme.lower() in {"http", "https"} and parsed_url.netloc
            if is_http_url:
                content = f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{content}</a>'

        return cls._metadata_detail_html(_SOURCE_ICON_PATHS[source_icon_key(fmt)], "Source", content)

    # ----- Per-recipe data ----- #

    def _resolve_title(self, recipe: Recipe, html_path: Path, metadata: dict) -> str:
        if recipe.title:
            return recipe.title

        # Production callers always build Recipe with the converter's title,
        # which is the rendered <h1> text. Tests construct Recipe objects
        # directly without a title, so fall back to the generated page's
        # heading — the same text the converter would have stored — before
        # the front matter title and the directory name.
        if html_path.exists():
            recipe_page = BeautifulSoup(html_path.read_text(encoding="UTF-8"), "html.parser")
            heading = recipe_page.find("h1")
            heading_title = heading.get_text(" ", strip=True) if heading else ""
            if heading_title:
                return heading_title

        return str(metadata.get("title") or slug_to_title(html_path.parent.name))

    # ----- Card model ----- #

    def _hero_image_url(self, html_path: Path) -> str:
        hero_image = get_first_image_in_dir(html_path.parent) if html_path.parent.is_dir() else None
        if hero_image is None:
            return ""
        return "/" + hero_image.relative_to(self.cfg.site_directory).as_posix()

    def _collect_filter_values(self, metadata: dict, sources: list[dict]) -> dict[str, list[str]]:
        """Collect the filterable values, keyed by filter key.

        The keys match ``FILTER_FIELDS``; ``sourceTitles`` is the camel-cased
        exception shared with the browser's ``data-source-titles`` attribute.
        """
        source_titles = [source_title for source in sources if (source_title := self._source_title(source))]
        contributors = [value.strip() for value in self.collect_metadata_values(metadata, "contributor") if value.strip()]
        return {
            "meals": self.collect_metadata_values(metadata, "meals"),
            "categories": self.collect_metadata_values(metadata, "categories", "category"),
            "tags": self.collect_metadata_values(metadata, "tags"),
            "cuisine": self.collect_metadata_values(metadata, "cuisine"),
            # Status is a single string value; only the first value is used.
            "status": self.collect_metadata_values(metadata, "status")[:1],
            "contributors": contributors,
            "sourceTitles": source_titles,
        }

    def _record_filter_counts(self, filter_values: FilterValuesByField, collected: dict[str, list[str]], *, archived: bool) -> None:
        # Archived recipes are hidden by default, so they do not add to the
        # visible option counts until "Show Archived" is turned on in the browser.
        for key, values in collected.items():
            self._record_filter_values(filter_values[key], values, count=not archived)

    @classmethod
    def _reviewer_rating_entries(cls, metadata: dict) -> list[dict]:
        return [{"name": normalize_reviewer_name(name) if name else "", "rating": score} for name, score in cls._valid_ratings(metadata)]

    @staticmethod
    def _numeric_front_matter_value(metadata: dict, key: str) -> str:
        value = metadata.get(key)
        return str(value) if isinstance(value, (int, float)) else ""

    def _prepare_card(self, recipe: Recipe, filter_values: FilterValuesByField) -> _RecipeCard:
        metadata = recipe.metadata
        html_path = recipe.html_file
        warnings_by_field = {warning["field"]: warning for warning in lint_recipe_metadata(metadata)}

        relative_path = html_path.relative_to(self.cfg.site_directory)
        url = "/" + relative_path.as_posix()
        markdown_path = relative_path.with_suffix(".md").as_posix()

        title = self._resolve_title(recipe, html_path, metadata)
        hero_url = self._hero_image_url(html_path)
        archived = metadata.get("archived") is True

        # ----- Filters and filter option counts ----- #
        sources = normalize_sources(metadata)
        collected = self._collect_filter_values(metadata, sources)
        self._record_filter_counts(filter_values, collected, archived=archived)

        # ----- Sort and search attributes ----- #
        search_text = " ".join(
            [
                title,
                *collected["meals"],
                *collected["categories"],
                *collected["tags"],
                *collected["cuisine"],
                *collected["status"],
                *collected["contributors"],
                *collected["sourceTitles"],
            ]
        )
        average_rating, rating_count = self._average_rating(metadata)
        rating_attribute = f"{average_rating:.6g}" if average_rating is not None else ""
        reviewer_ratings = self._reviewer_rating_entries(metadata)

        makes_value = self._numeric_front_matter_value(metadata, "makes")
        difficulty_value = self._numeric_front_matter_value(metadata, "difficulty")

        parsed_contribution = parse_metadata_datetime(metadata.get("createdOn"))
        contribution_date = parsed_contribution.date() if parsed_contribution else None
        updated_on = parse_metadata_datetime(metadata.get("updatedOn"))

        return _RecipeCard(
            url=url,
            markdown_path=markdown_path,
            title=title,
            hero_url=hero_url,
            archived=archived,
            search_text=search_text,
            meals=collected["meals"],
            categories=collected["categories"],
            tags=collected["tags"],
            cuisine=collected["cuisine"],
            status=collected["status"],
            contributors=collected["contributors"],
            source_titles=collected["sourceTitles"],
            sources=sources,
            reviewer_ratings=reviewer_ratings,
            average_rating=average_rating,
            rating_count=rating_count,
            rating_attribute=rating_attribute,
            makes_value=makes_value,
            difficulty_value=difficulty_value,
            contribution_date=contribution_date,
            updated_on_value=updated_on.isoformat() if updated_on else "",
            date_value=contribution_date.isoformat() if contribution_date else "",
            warnings_by_field=warnings_by_field,
        )

    def _card_attributes_html(self, card: _RecipeCard) -> str:
        serialize = self.serialize_for_html_attribute
        return (
            f'<li class="recipe"'
            f' data-path="{html.escape(card.markdown_path, quote=True)}"'
            f' data-title="{html.escape(card.title, quote=True)}"'
            f' data-search="{html.escape(card.search_text, quote=True)}"'
            f' data-meals="{serialize(card.meals)}"'
            f' data-categories="{serialize(card.categories)}"'
            f' data-tags="{serialize(card.tags)}"'
            f' data-cuisine="{serialize(card.cuisine)}"'
            f' data-status="{serialize(card.status)}"'
            f' data-contributors="{serialize(card.contributors)}"'
            f' data-source-titles="{serialize(card.source_titles)}"'
            f' data-ratings="{serialize(card.reviewer_ratings)}"'
            f' data-rating="{card.rating_attribute}"'
            f' data-makes="{card.makes_value}"'
            f' data-difficulty="{card.difficulty_value}"'
            f' data-archived="{"true" if card.archived else "false"}"'
            f' data-edited="{card.updated_on_value}"'
            f' data-date="{card.date_value}">'
        )

    def _build_recipe_item(self, recipe: Recipe, filter_values: FilterValuesByField) -> str:
        card = self._prepare_card(recipe, filter_values)

        rating_html = self._rating_html(
            card.average_rating,
            card.rating_count,
            self._warning_for(card.warnings_by_field, "ratings", "rating"),
        )
        select_html = (
            '<label class="recipe-select" hidden>'
            f'<input type="checkbox" class="recipe-select__checkbox" '
            f'data-path="{html.escape(card.markdown_path, quote=True)}"'
            f' aria-label="Select {html.escape(card.title, quote=True)} for bulk editing">'
            '<span class="recipe-select__box" aria-hidden="true"></span>'
            "</label>"
        )
        image_html = (
            f'<a class="recipe-card__image" href="{html.escape(card.url, quote=True)}" '
            f'aria-label="View {html.escape(card.title, quote=True)} recipe">'
            f'<img src="{html.escape(card.hero_url, quote=True)}" alt="" loading="lazy">'
            "</a>"
            if card.hero_url
            else ""
        )

        return (
            f"{self._card_attributes_html(card)}"
            '<article class="recipe-card">'
            f"{select_html}"
            f"{image_html}"
            '<div class="recipe-card__heading">'
            f'<h2><a class="recipe-card__link" href="{html.escape(card.url, quote=True)}">'
            f"{html.escape(card.title)}</a></h2>"
            "</div>"
            f'<div class="recipe-card__details">{rating_html}{self._build_card_details(card)}</div>'
            "</article>"
            "</li>"
        )

    def _build_card_details(self, card: _RecipeCard) -> str:
        warnings = card.warnings_by_field
        parts: list[str] = [
            self._detail_with_warning(
                "makes",
                "Makes",
                [f"x{card.makes_value}"] if card.makes_value else [],
                ("makes",),
                warnings,
            ),
            self._detail_with_warning(
                "difficulty",
                "Difficulty",
                [f"{card.difficulty_value}/10"] if card.difficulty_value else [],
                ("difficulty",),
                warnings,
            ),
            self._detail_with_warning("meals", "Meals", card.meals, ("meals",), warnings),
            self._detail_with_warning("cuisine", "Cuisine", card.cuisine, ("cuisine",), warnings),
            self._detail_with_warning("status", "Status", card.status, ("status",), warnings),
            self._detail_with_warning(
                "categories",
                "Categories",
                card.categories,
                ("categories", "category"),
                warnings,
            ),
            self._detail_with_warning("tags", "Tags", card.tags, ("tags",), warnings),
            self._detail_with_warning(
                "contributor",
                "Contributor",
                card.contributors,
                ("contributor",),
                warnings,
                icon_path=QUILL_SVG,
            ),
            self._detail_with_warning(
                "contribution-date",
                "Contribution date",
                [str(card.contribution_date.year)] if card.contribution_date else [],
                ("createdOn", "contribution_date"),
                warnings,
                icon_path=CALENDAR_SVG,
            ),
        ]

        if card.archived:
            parts.append(self._detail_html("archived", "Archived", ["Archived"]))

        # Titled sources render as individual details; warn only when none exist.
        titled_sources = [self._source_detail_html(source) for source in card.sources if self._source_title(source)]
        parts.extend(titled_sources)
        if not titled_sources:
            source_warning = self._warning_for(warnings, "source")
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
                key = normalize_reviewer_name(name)
                reviewer_counts[key] = reviewer_counts.get(key, 0) + 1
                reviewer_names.setdefault(key, name)

        ranked = sorted(
            reviewer_counts.items(),
            key=lambda item: (-item[1], reviewer_names[item[0]].casefold()),
        )
        return [(key, count, reviewer_names[key]) for key, count in ranked[:MAX_REVIEW_FILTER_OPTIONS]]

    @staticmethod
    def _record_filter_values(
        entries: dict[str, FilterValue],
        values: list[str],
        *,
        count: bool = True,
    ) -> None:
        """Add a recipe's values to one filter's option list.

        Values are keyed by their lower-cased form because the browser filters
        on lower-cased ``data-*`` attributes. The first spelling seen becomes
        the label, so ``Dinner`` and ``dinner`` share one option.
        """
        seen: set[str] = set()
        for value in values:
            key = value.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            entry = entries.setdefault(key, FilterValue(label=value))
            if count:
                entry.count += 1

    @staticmethod
    def _build_filter_options_html(
        entries: dict[str, FilterValue],
        *,
        control_id: str,
        all_label: str,
        total_count: int,
    ) -> str:
        options = [
            '<label class="filter-menu__option filter-menu__option--all">'
            f'<input type="checkbox" class="filter-option-all" id="{control_id}-all" checked>'
            f"<span>{html.escape(all_label)}</span>"
            f'<span class="filter-menu__count">{total_count}</span>'
            "</label>"
        ]
        for key, entry in sorted(entries.items(), key=lambda item: item[1].label.casefold()):
            options.append(
                '<label class="filter-menu__option">'
                f'<input type="checkbox" class="filter-option" value="{html.escape(key, quote=True)}">'
                f"<span>{html.escape(entry.label)}</span>"
                f'<span class="filter-menu__count">{entry.count}</span>'
                "</label>"
            )
        return "\n".join(options)

    @classmethod
    def _build_filter_menu_html(
        cls,
        field: FilterField,
        entries: dict[str, FilterValue],
        *,
        total_count: int,
    ) -> str:
        options_html = cls._build_filter_options_html(
            entries,
            control_id=field.control_id,
            all_label=field.all_label,
            total_count=total_count,
        )
        return (
            f'<details class="filter-control filter-menu" id="{field.control_id}"'
            f' data-filter="{field.key}" data-filter-label="{html.escape(field.label, quote=True)}">'
            "<summary>"
            f"{cls._inline_svg(field.icon_path)}"
            f'<span class="filter-menu__label" id="{field.control_id}-label">{html.escape(field.label)}: All</span>'
            "</summary>"
            f'<fieldset class="filter-menu__menu">'
            f'<legend class="visually-hidden">{html.escape(field.legend)}</legend>'
            f"{options_html}"
            "</fieldset>"
            "</details>"
        )

    @staticmethod
    def _build_reviewer_options_html(
        reviewer_entries: list[tuple[str, int, str]],
    ) -> str:
        options: list[str] = []
        for key, count, display_name in reviewer_entries:
            options.append(
                '<label class="filter-menu__option">'
                '<input type="checkbox" class="filter-reviews"'
                f' value="{html.escape(key, quote=True)}">'
                f"<span>{html.escape(display_name)}</span>"
                f'<span class="filter-menu__count">{count}</span>'
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

    # ----- Page section builders ----- #

    @staticmethod
    def _food_color_style(food_color: str) -> str:
        dark_food_color = dark_mode_color(food_color)
        return dedent(f"""\
<style>
    :root {{
        --food-color: {food_color};
        --food-color-hover: color-mix(in srgb, {food_color} {FOOD_COLOR_HOVER_MIX_PERCENT}%, black);
    }}
    @media (prefers-color-scheme: dark) {{
        :root {{
            --food-color: {dark_food_color};
            --food-color-hover: color-mix(in srgb, {dark_food_color} {FOOD_COLOR_HOVER_MIX_PERCENT}%, white);
        }}
    }}
</style>
""").rstrip("\n")

    @staticmethod
    def _versioned_asset_urls() -> dict[str, str]:
        """Content-hash every local asset the page references, keyed by template name."""
        paths = {
            "definitions_css": DEFINITIONS_CSS_PATH,
            "index_css": INDEX_CSS_PATH,
            "index_js": INDEX_JS_PATH,
            "icons_js": ICONS_JS_PATH,
            "recipe_editor_css": RECIPE_EDITOR_CSS_PATH,
            "recipe_editor_js": RECIPE_EDITOR_JS_PATH,
            "metadata_picker_js": METADATA_PICKER_JS_PATH,
            "ai_progress_js": AI_PROGRESS_JS_PATH,
            "shopping_list_css": SHOPPING_LIST_CSS_PATH,
            "shopping_list_js": SHOPPING_LIST_JS_PATH,
            "recipe_scaler_css": RECIPE_SCALER_CSS_PATH,
            "recipe_scaler_js": RECIPE_SCALER_JS_PATH,
            "config_editor_css": CONFIG_EDITOR_CSS_PATH,
            "config_editor_js": CONFIG_EDITOR_JS_PATH,
            "pull_down_page_refresh_css": PULL_DOWN_PAGE_REFRESH_CSS_PATH,
            "pull_down_page_refresh_js": PULL_DOWN_PAGE_REFRESH_JS,
            "time_js": TIME_JS_PATH,
            "logo": LOGO_SVG,
        }
        return {name: versioned_asset_url(path) for name, path in paths.items()}

    def _filter_menus_html(self, filter_values: FilterValuesByField) -> str:
        total_count = sum(1 for recipe in self.recipes if recipe.metadata.get("archived") is not True)
        return "\n".join(self._build_filter_menu_html(field, filter_values[field.key], total_count=total_count) for field in FILTER_FIELDS)

    @staticmethod
    def _page_head_html(server_name_html: str, food_color_style: str, urls: dict[str, str]) -> str:
        return dedent(f"""\
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{server_name_html}</title>
    <link rel="icon" type="image/svg+xml" href="{urls['logo']}">
    <link rel="stylesheet" href="{urls['definitions_css']}">
{food_color_style}
    <link rel="stylesheet" href="{MENU_CSS_URL}">
    <link rel="stylesheet" href="{urls['index_css']}">
    <link rel="stylesheet" href="{urls['recipe_editor_css']}">
    <link rel="stylesheet" href="{urls['recipe_scaler_css']}">
    <link rel="stylesheet" href="{urls['shopping_list_css']}">
    <link rel="stylesheet" href="{urls['config_editor_css']}">
    <link rel="stylesheet" href="{urls['pull_down_page_refresh_css']}">
    <script src="{MENU_JS_URL}" defer></script>
    <script src="{urls['icons_js']}" defer></script>
    <script src="{urls['index_js']}" defer></script>
    <script src="{urls['metadata_picker_js']}" defer></script>
    <script src="{urls['ai_progress_js']}" defer></script>
    <script src="{urls['recipe_editor_js']}" defer></script>
    <script src="{urls['recipe_scaler_js']}" defer></script>
    <script src="{urls['shopping_list_js']}" defer></script>
    <script src="{urls['config_editor_js']}" defer></script>
</head>
""").rstrip("\n")

    def _page_header_html(self, server_name_html: str) -> str:
        return dedent(f"""\
<header class="recipes-header">
    {sandwich_menu_html()}
    <h1>{server_name_html}</h1>
    <button id="create-recipe" class="create-recipe" type="button"
        aria-label="Create recipe" title="Create recipe">
        {self._inline_svg(PLUS_SVG)}
    </button>
</header>
""").rstrip("\n")

    def _sort_control_html(self) -> str:
        # Option values are "<field>:<direction>" with direction "asc" or
        # "desc" (for example "edited:desc"). index.js splits the value on
        # ":" and sorts on the field; keep the format in sync with the
        # SORT_* constants there.
        return dedent(f"""\
<label class="filter-control">
    {self._inline_svg(UP_DOWN_ARROW_SVG)}
    <select id="sort-recipes" aria-label="Sort recipes">
        <option value="edited:desc">Last Edited (Newest First)</option>
        <option value="edited:asc">Last Edited (Oldest First)</option>
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
    </select>
</label>
""").rstrip("\n")

    def _review_filter_html(self, reviewer_options_html: str) -> str:
        return dedent(f"""\
<details class="filter-control filter-menu review-filter" id="review-filter">
    <summary>
        {self._inline_svg(USER_SVG)}
        <span class="filter-menu__label" id="review-filter-label">Filter Reviews: All</span>
    </summary>
    <fieldset class="filter-menu__menu">
        <legend class="visually-hidden">Filter Reviews</legend>
        <label class="filter-menu__option filter-menu__option--all">
            <input type="checkbox" id="filter-reviews-all" checked>
            <span>All reviews</span>
            <span class="filter-menu__count"></span>
        </label>
        {reviewer_options_html}
    </fieldset>
</details>
""").rstrip("\n")

    def _toolbar_html(self, filter_menus_html: str, reviewer_options_html: str) -> str:
        return dedent(f"""\
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
    <details class="recipe-advanced">
        <summary>
            <span>Advanced</span>
        </summary>
        <div class="recipe-advanced__content">
            <div class="recipe-filters">
                {self._sort_control_html()}
                {filter_menus_html}
                {self._review_filter_html(reviewer_options_html)}
            </div>
            <label class="metadata-status-toggle">
                <input
                    id="metadata-status"
                    type="checkbox"
                    aria-controls="recipe-list"
                >
                <span>Metadata Status</span>
            </label>
            <label class="metadata-status-toggle show-archived-toggle">
                <input
                    id="show-archived"
                    type="checkbox"
                    aria-controls="recipe-list"
                >
                <span>Show Archived</span>
            </label>
        </div>
    </details>
</section>
""").rstrip("\n")

    def _results_bar_html(self) -> str:
        return dedent(f"""\
<div class="recipe-results-bar">
    <p id="recipe-count" aria-live="polite"></p>
    <div id="bulk-controls" class="bulk-controls">
        <label class="select-all-control" data-selection-only hidden>
            <input type="checkbox" id="select-all">
            <span>Select All</span>
        </label>
        <button id="clear-selections" type="button" data-selection-only hidden>Clear Selections</button>
        <button id="bulk-delete" class="bulk-delete" type="button" data-selection-only hidden disabled>Delete Selected</button>
        <button id="shopping-list" class="shopping-list-button" type="button" data-selection-only hidden disabled>
            {self._inline_svg(SHOPPING_CART_SVG)}
            <span>Shopping List</span>
        </button>
        <button id="bulk-edit" class="bulk-edit" type="button" data-selection-only hidden disabled>
            {self._inline_svg(PENCIL_SVG)}
            <span>Bulk Edit</span>
        </button>
        <span class="bulk-controls__status">
            <span id="bulk-selection-count" aria-live="polite" data-selection-only hidden>0 selected</span>
            <button
                id="bulk-selection-toggle"
                class="bulk-selection-button"
                type="button"
                aria-controls="recipe-list"
            >
                <span data-selection-label>Select</span>
            </button>
        </span>
    </div>
    <button id="clear-filters" type="button" hidden>Clear filters</button>
    <div class="results-controls">
        <div class="card-zoom" id="card-zoom-control" title="Smaller shows more">
            <label class="card-zoom__label" for="card-zoom">Size</label>
            <input
                class="card-zoom__slider"
                id="card-zoom"
                type="range"
                min="180"
                max="440"
                step="20"
                value="280"
                aria-label="Size"
                aria-describedby="card-zoom-hint"
                title="Smaller shows more"
            >
            <span class="visually-hidden card-zoom__hint" id="card-zoom-hint">Smaller shows more</span>
        </div>
        <div class="view-switcher" role="group" aria-label="Recipe view">
            <button type="button" data-view="list" aria-pressed="true">List</button>
            <button type="button" data-view="cards" aria-pressed="false">Cards</button>
        </div>
    </div>
</div>
""").rstrip("\n")

    def _render_page(
        self,
        *,
        recipe_items_html: str,
        filter_values: FilterValuesByField,
        reviewer_options_html: str,
    ) -> str:
        server_name_html = html.escape(self._server_name())
        food_color = getattr(self.cfg, "food_color", None) or DEFAULT_FOOD_COLOR
        food_color_style = self._food_color_style(food_color)
        filter_menus_html = self._filter_menus_html(filter_values)
        asset_urls = self._versioned_asset_urls()

        return dedent(f"""\
<!DOCTYPE html>
<html lang="en">
{self._page_head_html(server_name_html, food_color_style, asset_urls)}
<body>
<main class="recipes">
{self._page_header_html(server_name_html)}
{self._toolbar_html(filter_menus_html, reviewer_options_html)}
{self._results_bar_html()}
<ul id="recipe-list" class="list-view">
{recipe_items_html}
</ul>
{self._version_footer_html()}
</main>
<script defer src="{asset_urls['time_js']}"></script>
<script defer src="{asset_urls['pull_down_page_refresh_js']}"></script>
</body>
</html>""")

    # ----- Entry point ----- #

    def convert(self) -> None:
        """Generate index.html from the collected recipes."""
        filter_values: FilterValuesByField = {field.key: {} for field in FILTER_FIELDS}

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
