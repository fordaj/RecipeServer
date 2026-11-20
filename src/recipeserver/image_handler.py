from PIL import Image
import colorsys
from collections import Counter
from pathlib import Path

from ._logger import logger

DEFAULT_TITLE = "#4169E1"

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".svg",
    ".avif",
}


def get_first_image_in_dir(directory: Path) -> Path | None:
    # Sort so the chosen hero image is stable across filesystems.
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path
    return None


class ImageToColorConverter:
    @staticmethod
    def get_hex_color_from_image(image: Path) -> str:
        with Image.open(image) as opened:
            rgb_image = opened.convert("RGB")

        # Shrink the image so we're not processing millions of pixels.
        rgb_image.thumbnail((200, 200))

        # Reduce the image to a small palette.
        quantized = rgb_image.quantize(colors=16).convert("RGB")

        counts = Counter(quantized.get_flattened_data())

        candidates = []

        for color, count in counts.items():
            r, g, b = color

            # Convert RGB -> HSV
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

            # Ignore near-white / near-black / gray colors.
            if v > 0.92:
                continue

            if v < 0.15:
                continue

            if s < 0.18:
                continue

            # Favor colors that are:
            #   - common
            #   - reasonably saturated
            #   - reasonably bright
            score = count * (0.5 + s) * (0.5 + v)

            candidates.append((score, color))

        if not candidates:
            return "#888888"

        _, (r, g, b) = max(candidates)

        return f"#{r:02X}{g:02X}{b:02X}"


def get_recipe_accent_color(directory: Path, fallback: str) -> str:
    """Return the ``--food-color`` accent a recipe page derives from its hero image.

    Returns the dominant color of the directory's first image
    (``ImageToColorConverter``), or ``fallback`` when there is no usable
    image or the color cannot be read. Shared by the converter, which paints
    recipe pages with the returned color, and the index generator, which
    paints its cards with the same value so a card always shows the color of
    the page of the recipe it links to.
    """
    image = get_first_image_in_dir(directory) if directory.is_dir() else None
    if image is None:
        return fallback
    logger.file(f"Found image: {image}")
    try:
        return ImageToColorConverter().get_hex_color_from_image(image)
    except (OSError, ValueError) as exc:
        logger.warning(f'Could not derive an accent color from "{image}": {exc}')
        return fallback
