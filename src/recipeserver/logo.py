"""Generate the tray ``logo.png`` from ``logo.svg``.

``logo.svg`` uses ``currentColor`` (like every other icon in
``assets/``) so it can inherit colour contextually -- as the page
favicon, and for the tray icon, where the configured food color is
substituted before rasterising with ``cairosvg``. The generated PNG
is a build artifact, so it is gitignored and regenerated on app load
(see :class:`recipeserver.tray.Tray`).
"""

from pathlib import Path

from ._logger import logger
from .config import DEFAULT_FOOD_COLOR

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_SVG = ASSETS_DIR / "logo.svg"
LOGO_PNG = ASSETS_DIR / "logo.png"
LOGO_SIZE = 256


def render_logo_png_bytes(food_color: str = DEFAULT_FOOD_COLOR, size: int = LOGO_SIZE) -> bytes:
    """Rasterise ``logo.svg`` with ``food_color`` substituted for ``currentColor``."""
    svg = LOGO_SVG.read_text(encoding="utf-8").replace("currentColor", food_color)
    import cairosvg

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=size, output_height=size)


def generate_logo_png(
    food_color: str = DEFAULT_FOOD_COLOR,
    output_path: Path | None = None,
) -> Path:
    """(Re)generate ``logo.png`` from ``logo.svg`` using ``food_color``.

    Writes the PNG to ``output_path`` (default: the bundled
    ``assets/logo.png``) and returns the path. Raises
    ``FileNotFoundError`` when ``logo.svg`` is missing and propagates
    renderer errors when the SVG cannot be rendered.
    """
    output = Path(output_path) if output_path is not None else LOGO_PNG
    png_bytes = render_logo_png_bytes(food_color)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(png_bytes)
    logger.info(f"Generated tray logo at {output} in food color {food_color}")
    return output
