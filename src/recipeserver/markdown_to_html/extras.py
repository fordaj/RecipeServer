"""Build the trailing extras blocks: contributor, sources, and version.

All three blocks end the ``<main>`` element. They share the "·" separator
plus ``<time>`` construction used for human-readable timestamps, factored
into ``recipe_utils.meta_time_html``.
"""

from bs4 import BeautifulSoup, Tag

from .._version import PACKAGE_VERSION
from ..recipe_utils import meta_time_html
from ..sources import normalize_sources, source_format, source_icon_key, source_title
from .icons import AI_SVG, BOOK_SVG, LINK_SVG, QUILL_SVG, TAG_SVG, USER_SVG, append_svg_icon

_SOURCE_ICONS = {"website": LINK_SVG, "book": BOOK_SVG, "ai": AI_SVG, "user": USER_SVG}


def _append_meta_time(label: Tag, soup: BeautifulSoup, raw_value: object, *, text_prefix: str = "") -> None:
    """Append "· <time>" to *label* when *raw_value* parses as a datetime."""
    fragment = meta_time_html(raw_value, text_prefix)
    if fragment:
        label.append(BeautifulSoup(fragment, "html.parser"))


def _append_to_main(soup: BeautifulSoup, node: Tag | None) -> None:
    main = soup.find("main", class_="recipe")
    if node is not None and main is not None:
        main.append(node)


# ----- Contributor ----- #


def _build_contributor(metadata: dict, soup: BeautifulSoup) -> Tag | None:
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
    _append_to_main(soup, _build_contributor(metadata, soup))


# ----- Sources ----- #


def _build_sources(metadata: dict, soup: BeautifulSoup) -> Tag | None:
    container = soup.new_tag(
        "div",
        attrs={"class": "recipe-sources"},
    )

    for source in normalize_sources(metadata):
        item = _build_source_item(source, soup)
        if item is not None:
            container.append(item)

    return container if container.contents else None


def _build_source_item(source: dict, soup: BeautifulSoup) -> Tag | None:
    fmt = source_format(source)
    title = source_title(source)
    author = str(source.get("author") or "").strip()
    url = str(source.get("url") or "").strip()

    if not title:
        return None

    item = soup.new_tag(
        "span",
        attrs={"class": "recipe-sources__item"},
    )

    append_svg_icon(item, _SOURCE_ICONS[source_icon_key(fmt)])

    if fmt == "website" and url:
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
    _append_to_main(soup, _build_sources(metadata, soup))


# ----- Version ----- #


def _build_version(metadata: dict, soup: BeautifulSoup) -> Tag:
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
    _append_to_main(soup, _build_version(metadata, soup))
