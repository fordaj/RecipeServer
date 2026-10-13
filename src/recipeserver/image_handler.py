from PIL import Image
import colorsys
from .pallette import Pallette
from pathlib import Path

RGB = tuple[int, int, int]

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
}


def get_first_image_in_dir(directory: Path) -> Path | None:
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            return path
    return None


class ImageToColorConverter:
    def __init__(self):
        self.hex: str = Pallette.DEFAULT_TITLE
        self.rgb = self.get_RGB(self.hex)

    @staticmethod
    def get_RGB(hex: str) -> RGB:
        hex = hex.lstrip("#")

        if len(hex) != 6:
            raise ValueError(f"Invalid RGB hex color: {hex!r}")

        return (
            int(hex[0:2], 16),
            int(hex[2:4], 16),
            int(hex[4:6], 16),
        )

    @staticmethod
    def get_hex(rgb: RGB) -> str:
        if len(rgb) != 3 or any(not 0 <= value <= 255 for value in rgb):
            raise ValueError(f"Invalid RGB value: {rgb!r}")

        return "#{:02X}{:02X}{:02X}".format(*rgb)

    @staticmethod
    def get_hex_color_from_image(image: Path) -> str:
        image = Image.open(image).convert("RGB")

        # Shrink the image so we're not processing millions of pixels.
        image.thumbnail((200, 200))

        # Reduce the image to a small palette.
        quantized = image.quantize(colors=16).convert("RGB")

        pixels = list(quantized.get_flattened_data())

        candidates = []

        for color in set(pixels):
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

            count = pixels.count(color)

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


def main():
    image = Path("Chocolate Chip Cookies/image.png")
    image = Path("Chocolate Chip Cookies/image-2.png")
    print(ImageToColorConverter.get_hex_color_from_image(image))
