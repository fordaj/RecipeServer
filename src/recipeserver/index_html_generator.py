import hashlib
import html
import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from textwrap import dedent
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ._logger import logger
from .config import DEFAULT_FOOD_COLOR, DEFAULT_RECIPE_SERVER_NAME, Configuration
from .image_handler import get_first_image_in_dir
from .menu import MENU_CSS_URL, MENU_JS_URL, sandwich_menu_html
from .metadata_linter import lint_recipe_metadata

try:
    from importlib.metadata import version as _package_version

    VERSION = _package_version("recipeserver")
except Exception:  # pragma: no cover - package metadata unavailable in tests
    VERSION = "0.0.0"

from .recipe_utils import (
    display_date,
    is_date_only,
    iter_valid_rating_entries,
    normalize_reviewer_name,
    parse_metadata_datetime,
    slug_to_title,
)

FILE_PATH = Path(__file__)
ASSETS_DIR = FILE_PATH.parent / "assets"

TIME_JS_PATH = "/assets/time.js"

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
ARCHIVE_SVG = ASSETS_DIR / "archive.svg"
INFO_SVG = ASSETS_DIR / "info.svg"
SHOPPING_CART_SVG = ASSETS_DIR / "shopping-cart.svg"
PENCIL_SVG = ASSETS_DIR / "pencil.svg"

# Detail kinds that render with a mapped asset icon.
_DETAIL_ICON_URLS = {
    "makes": "/assets/chef-hat.svg",
    "difficulty": "/assets/gauge.svg",
    "meals": "/assets/utensils.svg",
    "categories": "/assets/cooking-pot.svg",
    "tags": "/assets/tag.svg",
    "cuisine": "/assets/pin.svg",
    "archived": "/assets/archive.svg",
    "status": "/assets/info.svg",
}

# Maximum number of reviewers shown in the review filter.
MAX_REVIEW_FILTER_OPTIONS = 30

# The multi-select filters in the Advanced section, in display order:
# (filter key, summary label, icon, control id, legend, "All" label).
FILTER_FIELDS = (
    ("meals", "Meals", UTENSILS_SVG, "filter-meal", "Filter by meal", "All meals"),
    ("cuisine", "Cuisine", PIN_SVG, "filter-cuisine", "Filter by cuisine", "All cuisines"),
    ("status", "Status", INFO_SVG, "filter-status", "Filter by status", "All statuses"),
    ("categories", "Categories", COOKING_POT_SVG, "filter-category", "Filter by category", "All categories"),
    ("tags", "Tags", TAG_SVG, "filter-tag", "Filter by tag", "All tags"),
    ("contributors", "Contributors", QUILL_SVG, "filter-contributor", "Filter by contributor", "All contributors"),
    ("sourceTitles", "Source Titles", BOOK_SVG, "filter-source-title", "Filter by source title", "All source titles"),
)

# Source formats that show an explicit title in the card details.
TITLED_SOURCE_FORMATS = {"website", "book"}


@dataclass
class FilterValue:
    """A filter option's display label and the number of recipes that use it."""

    label: str
    count: int = 0


@lru_cache(maxsize=None)
def _versioned_asset_url(url: str) -> str:
    """Append a content hash so browsers pick up changed assets."""
    relative = url.removeprefix("/assets/")
    asset_path = ASSETS_DIR / relative
    digest = hashlib.sha1(asset_path.read_bytes()).hexdigest()[:10]
    return f"{url}?v={digest}"


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
        label_parts = [f"v{VERSION}"]
        if latest is not None:
            if is_date_only(latest_raw):
                time_attrs = f'datetime="{html.escape(latest.date().isoformat(), quote=True)}"'
            else:
                time_attrs = f'datetime="{html.escape(latest.isoformat(), quote=True)}" ' 'data-local-time="true" data-time-prefix="Edited "'
            label_parts.append(
                f'<span class="recipe-meta__separator" aria-hidden="true">·</span>'
                f"<time {time_attrs}>Edited {html.escape(display_date(latest))}</time>"
            )
        label = "".join(label_parts)
        return f'<footer class="recipe-version" aria-label="App version">' f"{icon}<span>{label}</span>" f"</footer>"

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
                content = f'<a href="{html.escape(url, quote=True)}" ' f'target="_blank" rel="noopener noreferrer">{content}</a>'

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

        return str(metadata.get("title") or slug_to_title(html_path.parent.name))

    def _build_recipe_item(self, recipe: Recipe, filter_values: dict[str, dict[str, FilterValue]]) -> str:
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

        archived = metadata.get("archived") is True

        # ----- Collect filterable metadata values ----- #
        meals = self.collect_metadata_values(metadata, "meals")
        categories = self.collect_metadata_values(metadata, "categories", "category")
        tags = self.collect_metadata_values(metadata, "tags")
        cuisine = self.collect_metadata_values(metadata, "cuisine")
        # Status is a single string value; only the first value is used.
        status = self.collect_metadata_values(metadata, "status")[:1]
        contributors = [value.strip() for value in self.collect_metadata_values(metadata, "contributor") if value.strip()]
        sources = self._sources(metadata)
        source_titles = [source_title for source in sources if (source_title := self._source_title(source))]

        # Archived recipes are hidden by default, so they do not add to the
        # visible option counts until "Show Archived" is turned on in the browser.
        for key, values in (
            ("meals", meals),
            ("categories", categories),
            ("tags", tags),
            ("cuisine", cuisine),
            ("status", status),
            ("contributors", contributors),
            ("sourceTitles", source_titles),
        ):
            self._record_filter_values(filter_values[key], values, count=not archived)

        # ----- Compute sort and search attributes ----- #
        search_text = " ".join([title, *meals, *categories, *tags, *cuisine, *status, *contributors, *source_titles])
        reviewer_ratings = [{"name": normalize_reviewer_name(name) if name else "", "rating": score} for name, score in self._valid_ratings(metadata)]
        average_rating, rating_count = self._average_rating(metadata)
        rating_attribute = f"{average_rating:.6g}" if average_rating is not None else ""

        makes = metadata.get("makes")
        difficulty = metadata.get("difficulty")
        makes_value = str(makes) if isinstance(makes, (int, float)) else ""
        difficulty_value = str(difficulty) if isinstance(difficulty, (int, float)) else ""

        parsed_contribution = parse_metadata_datetime(metadata.get("createdOn"))
        contribution_date = parsed_contribution.date() if parsed_contribution else None
        updated_on = parse_metadata_datetime(metadata.get("updatedOn"))
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
            status=status,
            categories=categories,
            tags=tags,
            contributors=contributors,
            contribution_date=contribution_date,
            sources=sources,
            archived=archived,
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
            f' data-status="{self.serialize_for_html_attribute(status)}"'
            f' data-contributors="{self.serialize_for_html_attribute(contributors)}"'
            f' data-source-titles="{self.serialize_for_html_attribute(source_titles)}"'
            f' data-ratings="{self.serialize_for_html_attribute(reviewer_ratings)}"'
            f' data-rating="{rating_attribute}"'
            f' data-makes="{makes_value}"'
            f' data-difficulty="{difficulty_value}"'
            f' data-archived="{"true" if archived else "false"}"'
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
        status: list[str],
        categories: list[str],
        tags: list[str],
        contributors: list[str],
        contribution_date: date | None,
        sources: list[dict],
        archived: bool = False,
        warnings_by_field: dict[str, dict] | None = None,
    ) -> str:
        warnings_by_field = warnings_by_field or {}
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
            self._detail_with_warning("status", "Status", status, ("status",), warnings_by_field),
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

        if archived:
            parts.append(self._detail_html("archived", "Archived", ["Archived"]))

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
        field: tuple[str, str, Path, str, str, str],
        entries: dict[str, FilterValue],
        *,
        total_count: int,
    ) -> str:
        key, label, icon_path, control_id, legend, all_label = field
        options_html = cls._build_filter_options_html(
            entries,
            control_id=control_id,
            all_label=all_label,
            total_count=total_count,
        )
        return (
            f'<details class="filter-control filter-menu" id="{control_id}"'
            f' data-filter="{key}" data-filter-label="{html.escape(label, quote=True)}">'
            "<summary>"
            f"{cls._inline_svg(icon_path)}"
            f'<span class="filter-menu__label" id="{control_id}-label">{html.escape(label)}: All</span>'
            "</summary>"
            f'<fieldset class="filter-menu__menu">'
            f'<legend class="visually-hidden">{html.escape(legend)}</legend>'
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

    def _render_page(
        self,
        *,
        recipe_items_html: str,
        filter_values: dict[str, dict[str, FilterValue]],
        reviewer_options_html: str,
    ) -> str:
        server_name_html = html.escape(self._server_name())
        food_color = getattr(self.cfg, "food_color", None) or DEFAULT_FOOD_COLOR
        from .markdown_to_html import dark_mode_color

        food_color_style = dedent(f"""\
            <style>
                :root {{
                    --food-color: {food_color};
                    --food-color-hover: color-mix(in srgb, {food_color} 82%, black);
                }}
                @media (prefers-color-scheme: dark) {{
                    :root {{
                        --food-color: {dark_mode_color(food_color)};
                        --food-color-hover: color-mix(in srgb, {dark_mode_color(food_color)} 82%, white);
                    }}
                }}
            </style>
            """)
        review_filter_icon = self._inline_svg(USER_SVG)
        total_count = sum(1 for recipe in self.recipes if recipe.metadata.get("archived") is not True)
        filter_menus_html = "\n".join(
            self._build_filter_menu_html(field, filter_values[field[0]], total_count=total_count) for field in FILTER_FIELDS
        )

        definitions_css_url = _versioned_asset_url(DEFINITIONS_CSS_PATH)
        index_css_url = _versioned_asset_url(INDEX_CSS_PATH)
        index_js_url = _versioned_asset_url(INDEX_JS_PATH)
        recipe_editor_css_url = _versioned_asset_url(RECIPE_EDITOR_CSS_PATH)
        recipe_editor_js_url = _versioned_asset_url(RECIPE_EDITOR_JS_PATH)
        metadata_picker_js_url = _versioned_asset_url(METADATA_PICKER_JS_PATH)
        ai_progress_js_url = _versioned_asset_url(AI_PROGRESS_JS_PATH)
        shopping_list_css_url = _versioned_asset_url(SHOPPING_LIST_CSS_PATH)
        shopping_list_js_url = _versioned_asset_url(SHOPPING_LIST_JS_PATH)
        recipe_scaler_css_url = _versioned_asset_url(RECIPE_SCALER_CSS_PATH)
        recipe_scaler_js_url = _versioned_asset_url(RECIPE_SCALER_JS_PATH)
        config_editor_css_url = _versioned_asset_url(CONFIG_EDITOR_CSS_PATH)
        config_editor_js_url = _versioned_asset_url(CONFIG_EDITOR_JS_PATH)
        return dedent(f"""\
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{server_name_html}</title>
                <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
                <link rel="stylesheet" href="{definitions_css_url}">
                {food_color_style}
                <link rel="stylesheet" href="{MENU_CSS_URL}">
                <link rel="stylesheet" href="{index_css_url}">
                <link rel="stylesheet" href="{recipe_editor_css_url}">
                <link rel="stylesheet" href="{recipe_scaler_css_url}">
                <link rel="stylesheet" href="{shopping_list_css_url}">
                <link rel="stylesheet" href="{config_editor_css_url}">
                <script src="{MENU_JS_URL}" defer></script>
                <script src="{index_js_url}" defer></script>
                <script src="{metadata_picker_js_url}" defer></script>
                <script src="{ai_progress_js_url}" defer></script>
                <script src="{recipe_editor_js_url}" defer></script>
                <script src="{recipe_scaler_js_url}" defer></script>
                <script src="{shopping_list_js_url}" defer></script>
                <script src="{config_editor_js_url}" defer></script>
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

                        <details class="recipe-advanced">
                            <summary>
                                <span>Advanced</span>
                            </summary>

                            <div class="recipe-advanced__content">
                                <div class="recipe-filters">
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
                                    {filter_menus_html}
                                </div>

                                <details class="filter-control filter-menu review-filter" id="review-filter">
                                    <summary>
                                        {review_filter_icon}
                                        <span class="filter-menu__label" id="review-filter-label">Filter Reviews: All</span>
                                    </summary>

                                    <fieldset class="filter-menu__menu">
                                        <legend class="visually-hidden">Filter Reviews</legend>
                                        <label class="filter-menu__option filter-menu__option--all">
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

                    <ul id="recipe-list" class="list-view">
                        {recipe_items_html}
                    </ul>

                    {self._version_footer_html()}
                </main>

                <script defer src="{TIME_JS_PATH}"></script>
                <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            </body>
            </html>
        """)

    # ----- Entry point ----- #

    def convert(self) -> None:
        """Generate index.html from the collected recipes."""
        filter_values: dict[str, dict[str, FilterValue]] = {field[0]: {} for field in FILTER_FIELDS}

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
