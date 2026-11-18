"""Reusable sandwich (hamburger) menu.

The menu is deliberately independent of any one page: ``sandwich_menu_html()``
returns the markup, ``MENU_CSS_URL``/``MENU_JS_URL`` point at the shared
assets, and both read every colour from ``definitions.css`` so the menu picks
up the light/dark themes automatically. The index page includes the default
menu; a recipe page can include the same helper with ``recipe_page=True`` to
get the menu carrying the **Edit Recipe** and **Timeline** entries (it just
needs a positioned ancestor, e.g. a ``position: relative`` page header, for
the top-left anchoring in ``menu.css``).
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from ._version import versioned_asset_url

FILE_PATH = Path(__file__)
ASSETS_DIR = FILE_PATH.parent / "assets"
MENU_SVG = ASSETS_DIR / "menu.svg"
MENU_CSS_PATH = "/assets/menu.css"
MENU_JS_PATH = "/assets/menu.js"

# The icon that sits on the left of each menu entry.
SETTINGS_SVG = ASSETS_DIR / "settings.svg"
FILE_DATABASE_SVG = ASSETS_DIR / "file-database.svg"
FILE_CODE_CORNER_SVG = ASSETS_DIR / "file-code-corner.svg"
PENCIL_SVG = ASSETS_DIR / "pencil.svg"
ROTATE_CW_CLOCK_SVG = ASSETS_DIR / "rotate-cw-clock.svg"

MENU_CSS_URL = versioned_asset_url(MENU_CSS_PATH)
MENU_JS_URL = versioned_asset_url(MENU_JS_PATH)


def _menu_icon_html(icon_path: Path, class_name: str) -> str:
    """Return an icon, inlined so it inherits ``currentColor``."""
    soup = BeautifulSoup(icon_path.read_text(encoding="UTF-8"), "html.parser")
    icon = soup.find("svg")
    if icon is None:
        raise ValueError(f"No SVG element found in {icon_path}")

    # The class of the asset is kept, so every icon stays recognisable.
    classes = [name for name in icon.get("class", []) if name]
    icon["class"] = [*classes, class_name]
    icon["aria-hidden"] = "true"
    icon["focusable"] = "false"
    return str(icon)


def _menu_item_html(icon_path: Path, label: str, **attributes: str) -> str:
    """Return a menu entry with its icon on the left."""
    attributes_html = "".join(f' {name.replace("_", "-")}="{value}"' for name, value in attributes.items())
    icon = _menu_icon_html(icon_path, "sandwich-menu__item-icon")
    return f'<button class="sandwich-menu__item" type="button"{attributes_html} role="menuitem">{icon}<span>{label}</span></button>'


def sandwich_menu_html(*, recipe_page: bool = False) -> str:
    """Render the sandwich menu markup for any page that wants it.

    ``recipe_page=True`` renders the recipe-page menu: an **Edit Recipe**
    entry (pencil icon), wired to open the editor by ``recipe-editor.js``
    (its ``id="edit-recipe"``), and a **Timeline** entry (rotate-cw-clock
    icon), wired to open the Version History dialog by ``timeline.js`` (its
    ``data-timeline="open"``). The default menu renders the entries used by
    the index page (Configuration and the two archive downloads).
    """
    if recipe_page:
        items = [
            _menu_item_html(PENCIL_SVG, "Edit Recipe", id="edit-recipe"),
            _menu_item_html(ROTATE_CW_CLOCK_SVG, "Timeline", data_timeline="open"),
        ]
    else:
        items = [
            _menu_item_html(SETTINGS_SVG, "Configuration", data_config="open"),
            _menu_item_html(FILE_CODE_CORNER_SVG, "Download Source Archive", data_archive="source"),
            _menu_item_html(FILE_DATABASE_SVG, "Download Site Archive", data_archive="site"),
        ]

    return (
        '<nav class="sandwich-menu" aria-label="Site menu">'
        '<button class="sandwich-menu__toggle" type="button" '
        'aria-expanded="false" aria-haspopup="menu" '
        'aria-label="Menu" title="Menu">'
        f"{_menu_icon_html(MENU_SVG, 'sandwich-menu__icon')}"
        "</button>"
        '<div class="sandwich-menu__panel" hidden role="menu">'
        f"{''.join(items)}"
        '<p class="sandwich-menu__status" role="status" '
        'aria-live="polite" hidden></p>'
        "</div>"
        "</nav>"
    )
