"""Ingredient scraping for the meal planner.

The meal planner combines the ingredients of several recipes into a single
checklist. The ingredients come from the generated recipe pages: a heading
whose text mentions "ingredient" opens an ingredients section, every list
item inside that section is an ingredient, and the next heading closes the
section again.

The scraper returns the content of the list items rather than plain text so
the meal planner keeps the quantity spans the recipe scaler needs to scale
each recipe independently.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# Heading levels that can open or close an ingredients section.
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# The word a heading must contain to open an ingredients section.
INGREDIENT_KEYWORD = "ingredient"

# The elements visited, in document order, while looking for ingredients.
_SCRAPE_SELECTOR = ", ".join((*HEADING_TAGS, "li"))


def scrape_ingredients(html: str) -> list[str]:
    """Return the content of every ingredient list item found in *html*.

    Each entry is the inner HTML of a list item, so the caller can render
    it inside a list item of its own and keep the ``.quantity`` spans that
    carry the amount and unit of a scaled ingredient.
    """
    soup = BeautifulSoup(html, "html.parser")

    ingredients: list[str] = []
    scraping = False

    for element in soup.select(_SCRAPE_SELECTOR):
        if element.name in HEADING_TAGS:
            heading = element.get_text(" ", strip=True)
            scraping = INGREDIENT_KEYWORD in heading.casefold()
        elif scraping:
            ingredients.append(element.decode_contents())

    return ingredients
