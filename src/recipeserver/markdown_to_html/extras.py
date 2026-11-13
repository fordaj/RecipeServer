"""Build the trailing extras blocks: contributor, sources, and version.

All three blocks end the ``<main>`` element. They share the "·" separator
plus ``<time>`` construction used for human-readable timestamps, factored
into ``_append_meta_time``.
"""

from bs4 import BeautifulSoup, Tag

from .._version import PACKAGE_VERSION
from ..recipe_utils import display_date, is_date_only, parse_metadata_datetime
from .icons import AI_SVG, BOOK_SVG, LINK_SVG, QUILL_SVG, TAG_SVG, USER_SVG, append_svg_icon

_META_SEPARATOR = "·"
_SEPARATOR_CLASS = "recipe-meta__separator"


def _append_meta_time(label: Tag, soup: BeautifulSoup, raw_value: object, *, text_prefix: str = "") -> None:
    """Append "· <time>" to *label* when *raw_value* parses as a datetime.

    Date-only values render as a bare calendar date. Timestamps render in
    browser-local time via ``data-local-time``; *text_prefix* (for example
    ``"Edited "``) is prepended to the displayed text and emitted as
    ``data-time-prefix`` so the browser-side script can rebuild the label.
    """
    parsed = parse_metadata_datetime(raw_value)
    if parsed is None:
        return

    separator = soup.new_tag("span", attrs={"class": _SEPARATOR_CLASS})
    separator.string = _META_SEPARATOR
    label.append(separator)

    if is_date_only(raw_value):
        time_attrs = {"datetime": parsed.date().isoformat()}
    else:
        time_attrs = {"datetime": parsed.isoformat(), "data-local-time": "true"}
        if text_prefix:
            time_attrs["data-time-prefix"] = text_prefix

    time_element = soup.new_tag("time", attrs=time_attrs)
    time_element.string = f"{text_prefix}{display_date(parsed)}"
    label.append(time_element)


# ----- Contributor ----- #


def build_recipe_contributor(metadata: dict, soup: BeautifulSoup) -> Tag | None:
    contributor = metadata.get("contributor", "")

    if isinstance(contributor, (list, tuple)):
        contributor = ", ".join(str(value) for value in contributor if value)

    if not isinstance(contributor, str):
        contributor = str(contributor or "")

    contributor = contributor.strip()

    if not contributor:
        return None

    item = soup.new_tag(
        "div",
        attrs={"class": "recipe-contributor"},
    )

    append_svg_icon(item, QUILL_SVG)

    label = soup.new_tag("span")
    label.string = f"by {contributor}"

    _append_meta_time(label, soup, metadata.get("createdOn"))

    item.append(label)

    return item


def inject_recipe_contributor(soup: BeautifulSoup, metadata: dict) -> None:
    main = soup.find("main", class_="recipe")
    if main is None:
        return

    contributor = build_recipe_contributor(metadata, soup)
    if contributor:
        main.append(contributor)


# ----- Sources ----- #


def build_recipe_sources(metadata: dict, soup: BeautifulSoup) -> Tag | None:
    sources = metadata.get("source")

    if isinstance(sources, dict):
        sources = [sources]
    elif not isinstance(sources, list):
        sources = []

    container = soup.new_tag(
        "div",
        attrs={"class": "recipe-sources"},
    )

    for source in sources:
        if not isinstance(source, dict):
            continue

        item = _build_source_item(source, soup)
        if item is not None:
            container.append(item)

    return container if container.contents else None


def _build_source_item(source: dict, soup: BeautifulSoup) -> Tag | None:
    source_format = str(source.get("format") or "").lower()
    title = str(source.get("title") or "").strip()
    author = str(source.get("author") or "").strip()
    url = str(source.get("url") or "").strip()

    if source_format == "website":
        title = title or str(source.get("company") or "").strip()
        icon = LINK_SVG
    elif source_format == "book":
        icon = BOOK_SVG
    elif source_format == "ai":
        icon = AI_SVG
    else:
        icon = USER_SVG

    if not title:
        return None

    item = soup.new_tag(
        "span",
        attrs={"class": "recipe-sources__item"},
    )

    append_svg_icon(item, icon)

    if source_format == "website" and url:
        label = soup.new_tag(
            "a",
            href=url,
            attrs={
                "target": "_blank",
                "rel": "noopener noreferrer",
            },
        )
    else:
        label = soup.new_tag("span")

    label.string = title
    item.append(label)

    if author:
        item.append(_build_source_author(author, soup))

    return item


def _build_source_author(author: str, soup: BeautifulSoup) -> Tag:
    author_group = soup.new_tag(
        "span",
        attrs={"class": "recipe-sources__author"},
    )

    append_svg_icon(author_group, USER_SVG)

    label = soup.new_tag("span")
    label.string = author
    author_group.append(label)

    return author_group


def inject_recipe_sources(soup: BeautifulSoup, metadata: dict) -> None:
    main = soup.find("main", class_="recipe")
    if main is None:
        return

    sources = build_recipe_sources(metadata, soup)
    if sources:
        main.append(sources)


# ----- Version ----- #


def build_recipe_version(metadata: dict, soup: BeautifulSoup) -> Tag:
    version_element = soup.new_tag(
        "div",
        attrs={"class": "recipe-version recipe-extras"},
    )

    append_svg_icon(version_element, TAG_SVG)

    label = soup.new_tag("span")
    label.append(f"v{PACKAGE_VERSION}")

    _append_meta_time(label, soup, metadata.get("updatedOn"), text_prefix="Edited ")

    version_element.append(label)

    return version_element


def inject_recipe_version(soup: BeautifulSoup, metadata: dict) -> None:
    main = soup.find("main", class_="recipe")
    if main is None:
        return

    version_element = build_recipe_version(metadata, soup)
    main.append(version_element)
