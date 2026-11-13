"""Inline-code quantity parsing and scaler-span rewriting.

Recipes write quantities as inline code such as ``1 1/2 tbsp`` or
``1-2 cups``. This module parses those strings and replaces the
corresponding ``<code>`` elements with ``<span class="quantity">``
elements that the recipe scaler can scale.

Unparseable inline code is left alone; the HTML linter flags it.
"""

import re
from fractions import Fraction

from bs4 import BeautifulSoup

# Canonical abbreviations for the spelled-out units that commonly appear
# in inline-code quantities.
UNIT_ALIASES = {
    "tablespoons": "tbsp",
    "tablespoon": "tbsp",
    "teaspoons": "tsp",
    "teaspoon": "tsp",
    "cups": "cup",
    "milliliters": "mL",
    "milliliter": "mL",
    "ml": "mL",
    "l": "L",
    "lbs": "lb",
    "ounces": "oz",
    "ounce": "oz",
    "grams": "g",
    "gram": "g",
}

_NUMBER = r"(?:\d+/\d+|\d+(?:\.\d+)?)"
_MIXED_NUMBER = rf"(?:\d+\s+\d+/\d+|{_NUMBER})"

# Ranges such as "1-2 tbsp", "1/2-3/4 tsp", or "1 1/2 - 2 1/2 tbsp".
# The dash may be a hyphen, en dash, or em dash.
_RANGE_QUANTITY = re.compile(
    rf"""
    (?P<start>{_MIXED_NUMBER})  # first amount in the range
    \s*
    [-–—]                       # dash between the amounts
    \s*
    (?P<end>{_MIXED_NUMBER})    # second amount in the range
    \s*
    (?P<unit>.*)                # whatever follows is the unit
    """,
    re.VERBOSE,
)

# Mixed numbers such as "1 1/2 tbsp".
_MIXED_NUMBER_QUANTITY = re.compile(
    rf"""
    (?P<whole>\d+)          # whole-number part
    \s+
    (?P<fraction>\d+/\d+)   # fractional part
    \s*
    (?P<unit>.*)            # whatever follows is the unit
    """,
    re.VERBOSE,
)

# Single numbers and fractions such as "2 eggs", "1/2 cup", or "1.5 cups".
_SINGLE_NUMBER_QUANTITY = re.compile(
    rf"""
    (?P<amount>{_NUMBER})   # integer, decimal, or fraction
    \s*
    (?P<unit>.*)            # whatever follows is the unit (may be empty)
    """,
    re.VERBOSE,
)


def sanitize_unit(unit: str) -> str:
    """Return the canonical unit spelling, or the trimmed input if unknown."""
    normalized = unit.strip().lower()
    return UNIT_ALIASES.get(normalized, unit.strip())


def _quantity_amount_to_float(amount: str) -> float:
    """Convert a number, fraction, or mixed number string to a float."""
    parts = amount.split()
    if len(parts) == 2:
        return float(Fraction(parts[0])) + float(Fraction(parts[1]))
    return float(Fraction(amount))


def parse_quantity_code(value: str) -> tuple[float, str, float | None] | None:
    """Parse an inline quantity such as ``1 1/2 tbsp`` or ``1-2 cups``.

    Returns ``(start, unit, end)`` where ``end`` is set for ranges.
    """
    value = value.strip()
    if not value:
        return None

    ranged = _RANGE_QUANTITY.fullmatch(value)
    if ranged:
        return (
            _quantity_amount_to_float(ranged.group("start")),
            ranged.group("unit").strip(),
            _quantity_amount_to_float(ranged.group("end")),
        )

    mixed = _MIXED_NUMBER_QUANTITY.fullmatch(value)
    if mixed:
        whole = Fraction(mixed.group("whole"))
        fraction = Fraction(mixed.group("fraction"))
        return float(whole + fraction), mixed.group("unit").strip(), None

    single = _SINGLE_NUMBER_QUANTITY.fullmatch(value)
    if single:
        return float(Fraction(single.group("amount"))), single.group("unit").strip(), None

    return None


def convert_quantity_code_spans(soup: BeautifulSoup) -> None:
    """Replace inline ``<code>`` quantities with scaler ``<span>`` elements."""
    for code in soup.find_all("code"):
        parsed = parse_quantity_code(code.get_text(strip=True))
        if parsed is None:
            continue

        quantity, unit, quantity_end = parsed
        unit = sanitize_unit(unit)

        span = soup.new_tag("span")
        span["class"] = "quantity"
        span["data-quantity"] = str(quantity)
        span["data-unit"] = unit

        if quantity_end is not None:
            span["data-quantity-end"] = str(quantity_end)

        code.replace_with(span)
