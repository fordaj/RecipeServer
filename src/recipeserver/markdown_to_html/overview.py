"""Build the recipe overview block shown above the hero image.

The overview has three rows: rating/makes/difficulty/meals, then
status/cuisine/categories/tags, then an archived badge. Each row is built
only when at least one of its values is present.
"""

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ..recipe_utils import as_list, iter_valid_rating_entries
from .icons import (
    ARCHIVE_SVG,
    CHEF_HAT_SVG,
    GAUGE_SVG,
    INFO_SVG,
    PIN_SVG,
    POT_SVG,
    TAG_SVG,
    UTENSILS_SVG,
    append_svg_icon,
)

# Icons for the secondary row, keyed by metadata field name.
_DETAIL_ICONS = {
    "status": INFO_SVG,
    "cuisine": PIN_SVG,
    "categories": POT_SVG,
    "tags": TAG_SVG,
}


def first_scalar(value: object) -> object:
    """Return a scalar metadata value, unwrapping a single-item list."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def build_recipe_overview(metadata: dict, soup: BeautifulSoup) -> Tag | None:
    """Build the overview rows shown above the hero image."""
    overview = soup.new_tag("div", attrs={"class": "recipe-overview"})

    for row in (_build_primary_row(metadata, soup), _build_secondary_row(metadata, soup), _build_tertiary_row(metadata, soup)):
        if row.contents:
            overview.append(row)

    return overview if overview.contents else None


def inject_recipe_overview(soup: BeautifulSoup, metadata: dict) -> None:
    """Insert the overview block ahead of the hero image, after the title."""
    title = soup.find("h1")
    if title is None:
        return

    hero = title.find_next("img")
    if hero is None:
        return

    overview = build_recipe_overview(metadata, soup)
    if overview:
        hero.parent.insert_before(overview)


# ----- Primary row: rating, makes, difficulty, meals ----- #


def _build_primary_row(metadata: dict, soup: BeautifulSoup) -> Tag:
    primary = soup.new_tag("div", attrs={"class": "recipe-overview__primary"})

    _append_rating(primary, metadata, soup)
    _append_icon_value(
        primary,
        soup,
        icon_path=CHEF_HAT_SVG,
        class_name="recipe-overview__makes",
        value=first_scalar(metadata.get("makes")),
        formatter=lambda value: f"x{value}",
        tag_name="button",
        attrs={
            "type": "button",
            "class": "recipe-overview__makes",
            "aria-label": "Record that you made this recipe",
            "title": "I made this!",
        },
        data_attrs=lambda value: {"makes": str(value)},
    )
    _append_icon_value(
        primary,
        soup,
        icon_path=GAUGE_SVG,
        class_name="recipe-overview__difficulty",
        value=first_scalar(metadata.get("difficulty")),
        formatter=lambda value: f"{value}/10",
    )
    _append_icon_value(
        primary,
        soup,
        icon_path=UTENSILS_SVG,
        class_name="recipe-overview__meals",
        value=as_list(metadata.get("meals")),
        formatter=lambda values: ", ".join(str(value) for value in values),
    )

    return primary


def _append_rating(container: Tag, metadata: dict, soup: BeautifulSoup) -> None:
    rating_scores = [score for _, score in iter_valid_rating_entries(metadata.get("ratings"))]
    if not rating_scores:
        return

    average = sum(rating_scores) / len(rating_scores)
    rating = soup.new_tag("span", attrs={"class": "recipe-overview__rating"})
    rating.string = f"★ {average:.1f}/10"
    container.append(rating)


def _append_icon_value(
    container: Tag,
    soup: BeautifulSoup,
    *,
    icon_path: Path,
    class_name: str,
    value: object,
    formatter,
    tag_name: str = "span",
    attrs: dict[str, str] | None = None,
    data_attrs: object = None,
) -> None:
    """Append an icon+text overview item when *value* is present."""
    if value is None or value == "" or value == []:
        return

    item_attrs = dict(attrs) if attrs is not None else {"class": class_name}
    item = soup.new_tag(tag_name, attrs=item_attrs)
    if data_attrs is not None:
        for name, attr_value in data_attrs(value).items():
            item[f"data-{name}"] = attr_value
    append_svg_icon(item, icon_path)
    text = soup.new_tag("span", attrs={"class": "recipe-overview__value"})
    text.string = formatter(value)
    item.append(text)
    container.append(item)


# ----- Secondary row: status, cuisine, categories, tags ----- #


def _build_secondary_row(metadata: dict, soup: BeautifulSoup) -> Tag:
    secondary = soup.new_tag("div", attrs={"class": "recipe-overview__secondary"})

    for key, icon_path in _DETAIL_ICONS.items():
        values = as_list(metadata.get(key))
        if key == "status":
            values = values[:1]
        if key == "categories" and not values:
            values = as_list(metadata.get("category"))
        if not values:
            continue

        group = soup.new_tag("span", attrs={"class": f"recipe-overview__{key}"})
        append_svg_icon(group, icon_path)

        for index, value in enumerate(values):
            if index:
                group.append(", ")
            label = soup.new_tag("span")
            label.string = str(value)
            group.append(label)

        secondary.append(group)

    return secondary


# ----- Tertiary row: archived badge ----- #


def _build_tertiary_row(metadata: dict, soup: BeautifulSoup) -> Tag:
    tertiary = soup.new_tag("div", attrs={"class": "recipe-overview__tertiary"})

    if metadata.get("archived") is True:
        _append_icon_value(
            tertiary,
            soup,
            icon_path=ARCHIVE_SVG,
            class_name="recipe-overview__archived",
            value="Archived",
            formatter=lambda value: str(value),
        )

    return tertiary
