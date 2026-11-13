"""Color helpers for page chrome derived from a recipe's hero image."""

from coloraide import Color

# Dark backgrounds need a brighter accent than the one sampled from the hero
# image. The accent's OKLCH lightness is remapped into the band [BASE, BASE
# + SPAN] so the result stays legible on dark surfaces; hue and chroma are
# preserved. The upper bound falls out of the formula (lightness 1.0 maps to
# BASE + SPAN), so only the two tuning constants are named here.
DARK_MODE_LIGHTNESS_BASE = 0.65
DARK_MODE_LIGHTNESS_SPAN = 0.20


def dark_mode_color(hex_color: str) -> str:
    """Return *hex_color* adjusted for display on dark backgrounds."""
    color = Color(hex_color).convert("oklch")
    lightness, chroma, hue = color.coords()

    # Push darker accents further up the band than already-bright ones.
    brightened = DARK_MODE_LIGHTNESS_BASE + (1.0 - lightness) * DARK_MODE_LIGHTNESS_SPAN

    result = Color("oklch", [brightened, chroma, hue])
    result = result.convert("srgb").fit()

    return result.to_string(hex=True)
