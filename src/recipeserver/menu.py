"""Reusable sandwich (hamburger) menu.

The menu is deliberately independent of any one page: ``sandwich_menu_html()``
returns the markup, ``MENU_CSS_URL``/``MENU_JS_URL`` point at the shared
assets, and both read every colour from ``definitions.css`` so the menu picks
up the light/dark themes automatically. The index page includes it today; a
recipe page can include the same helper, stylesheet and script to get the
identical menu (it just needs a positioned ancestor, e.g. a ``position:
relative`` page header, for the top-left anchoring in ``menu.css``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

FILE_PATH = Path(__file__)
MENU_SVG = FILE_PATH.parent / "assets" / "menu.svg"
MENU_CSS_PATH = "/assets/menu.css"
MENU_JS_PATH = "/assets/menu.js"


def _versioned_asset_url(url: str) -> str:
    """Append a content hash so browsers pick up changed assets."""
    asset_path = FILE_PATH.parent / "assets" / Path(url).name
    digest = hashlib.sha1(asset_path.read_bytes()).hexdigest()[:10]
    return f"{url}?v={digest}"


MENU_CSS_URL = _versioned_asset_url(MENU_CSS_PATH)
MENU_JS_URL = _versioned_asset_url(MENU_JS_PATH)


def _menu_icon_html() -> str:
    """Return the menu.svg icon, inlined so it inherits ``currentColor``."""
    soup = BeautifulSoup(MENU_SVG.read_text(encoding="UTF-8"), "html.parser")
    icon = soup.find("svg")
    if icon is None:
        raise ValueError(f"No SVG element found in {MENU_SVG}")
    icon["class"] = ["sandwich-menu__icon"]
    icon["aria-hidden"] = "true"
    icon["focusable"] = "false"
    return str(icon)


def sandwich_menu_html() -> str:
    """Render the sandwich menu markup for any page that wants it."""
    return (
        '<nav class="sandwich-menu" aria-label="Site menu">'
        '<button class="sandwich-menu__toggle" type="button" '
        'aria-expanded="false" aria-haspopup="menu" '
        'aria-label="Menu" title="Menu">'
        f"{_menu_icon_html()}"
        "</button>"
        '<div class="sandwich-menu__panel" hidden role="menu">'
        '<button class="sandwich-menu__item" type="button" '
        'data-archive="source" role="menuitem">Download Source Archive</button>'
        '<button class="sandwich-menu__item" type="button" '
        'data-archive="site" role="menuitem">Download Site Archive</button>'
        '<p class="sandwich-menu__status" role="status" '
        'aria-live="polite" hidden></p>'
        "</div>"
        "</nav>"
    )
