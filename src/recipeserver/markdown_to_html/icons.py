"""SVG icon loading shared by the recipe page builders.

Icons live as standalone ``.svg`` files in the assets directory. Reading
them through this module keeps the "never embed ad-hoc inline SVG markup"
rule in one place.
"""

from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

GAUGE_SVG = ASSETS_DIR / "gauge.svg"
CHEF_HAT_SVG = ASSETS_DIR / "chef-hat.svg"
POT_SVG = ASSETS_DIR / "cooking-pot.svg"
TAG_SVG = ASSETS_DIR / "tag.svg"
QUILL_SVG = ASSETS_DIR / "quill.svg"
UTENSILS_SVG = ASSETS_DIR / "utensils.svg"
PIN_SVG = ASSETS_DIR / "pin.svg"
BOOK_SVG = ASSETS_DIR / "book.svg"
AI_SVG = ASSETS_DIR / "ai.svg"
USER_SVG = ASSETS_DIR / "user.svg"
USER_ROUND_SVG = ASSETS_DIR / "user-round.svg"
LINK_SVG = ASSETS_DIR / "link.svg"
NOTEBOOK_SVG = ASSETS_DIR / "notebook.svg"
PENCIL_SVG = ASSETS_DIR / "pencil.svg"
PLUS_SVG = ASSETS_DIR / "plus.svg"
ARCHIVE_SVG = ASSETS_DIR / "archive.svg"
INFO_SVG = ASSETS_DIR / "info.svg"


@lru_cache(maxsize=None)
def read_svg(asset_path: Path) -> str:
    return asset_path.read_text(encoding="utf-8")


def icon_html(asset_path: Path, class_name: str | None = None) -> str:
    """Return the SVG from an assets file, optionally overriding its class."""
    svg = BeautifulSoup(read_svg(asset_path), "html.parser").find("svg")
    if svg is None:
        raise ValueError(f"No SVG element found in {asset_path}")
    if class_name is not None:
        svg["class"] = [class_name]
    return str(svg)


def append_svg_icon(parent: Tag, path: Path) -> None:
    """Append the SVG at *path* to *parent*, hidden from assistive technology."""
    svg = BeautifulSoup(read_svg(path), "html.parser").find("svg")

    if svg is None:
        raise ValueError(f"No SVG element found in {path}")

    svg["aria-hidden"] = "true"
    svg["focusable"] = "false"

    parent.append(svg)
