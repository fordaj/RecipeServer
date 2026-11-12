"""Ingredient scraping for the shopping list.

The shopping list combines the ingredients of several recipes into a single
checklist. The ingredients come from the generated recipe pages: a heading
whose text mentions "ingredient" opens an ingredients section, every list
item inside that section is an ingredient, and the next heading closes the
section again.

The scraper returns the content of the list items rather than plain text so
the shopping list keeps the quantity spans the recipe scaler needs to scale
each recipe independently. It also returns the name and the unit of every
ingredient, which is what the shopping list groups on: two ingredients that name
the same thing in the same unit are added together.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Heading levels that can open or close an ingredients section.
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# The word a heading must contain to open an ingredients section.
INGREDIENT_KEYWORD = "ingredient"

# The elements visited, in document order, while looking for ingredients.
_SCRAPE_SELECTOR = ", ".join((*HEADING_TAGS, "li"))

# Words that do not change which ingredient a line refers to.
_NAME_PREFIXES = ("of ",)

# Everything that is not a letter, a digit or a space.
_PUNCTUATION = re.compile(r"[^\w\s]")


def _normalize_name(text: str) -> str:
    """Return the part of an ingredient that names it.

    "of flour" and "flour" name the same ingredient, so a leading "of" is
    dropped and the rest is lower-cased and stripped of punctuation.
    """
    name = text.strip().lower()

    for prefix in _NAME_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break

    name = _PUNCTUATION.sub(" ", name)
    return " ".join(name.split())


def _normalize_unit(unit: str) -> str:
    """Return a unit in a form that can be compared across recipes.

    "cups" and "cup" name the same unit, so a trailing "s" is dropped.
    Units that end in "es" or "ss" are left alone ("molasses", "tomatoes").
    """
    unit = unit.strip().lower()

    if len(unit) > 2 and unit.endswith("s") and unit[-2] not in {"e", "s"}:
        unit = unit[:-1]

    return unit


def parse_ingredient(markup: str) -> dict:
    """Return the parts of an ingredient the shopping list needs.

    The name and the unit say which ingredient this is, so the shopping list can
    add the amounts of the recipes that need it together.
    """
    soup = BeautifulSoup(markup, "html.parser")

    unit = ""
    has_range = False

    quantity = soup.select_one(".quantity")
    if quantity is not None:
        unit = quantity.get("data-unit") or ""
        has_range = quantity.get("data-quantity-end") is not None
        quantity.extract()

    remainder = " ".join(soup.get_text(" ", strip=True).split())

    return {
        "html": markup,
        "name": _normalize_name(remainder),
        "unit": _normalize_unit(unit),
        "has_range": has_range,
    }


def scrape_ingredients(html: str) -> list[dict]:
    """Return the content of every ingredient list item found in *html*.

    Each entry is the inner HTML of a list item, so the caller can render
    it inside a list item of its own and keep the ``.quantity`` spans that
    carry the amount and unit of a scaled ingredient.
    """
    soup = BeautifulSoup(html, "html.parser")

    ingredients: list[dict] = []
    scraping = False

    for element in soup.select(_SCRAPE_SELECTOR):
        if element.name in HEADING_TAGS:
            heading = element.get_text(" ", strip=True)
            scraping = INGREDIENT_KEYWORD in heading.casefold()
        elif scraping:
            ingredients.append(parse_ingredient(element.decode_contents()))

    return ingredients
