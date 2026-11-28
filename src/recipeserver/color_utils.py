"""Color helpers for page chrome derived from a recipe's hero image."""

from textwrap import dedent

from coloraide import Color

# Dark backgrounds need a brighter accent than the one sampled from the hero
# image. The accent's OKLCH lightness is remapped into the band [BASE, BASE
# + SPAN] so the result stays legible on dark surfaces; hue and chroma are
# preserved. The upper bound falls out of the formula (lightness 1.0 maps to
# BASE + SPAN), so only the two tuning constants are named here.
DARK_MODE_LIGHTNESS_BASE = 0.65
DARK_MODE_LIGHTNESS_SPAN = 0.20

# How much of the accent survives the mix used for its hover variant.
FOOD_COLOR_HOVER_MIX_PERCENT = 82


def dark_mode_color(hex_color: str) -> str:
    """Return *hex_color* adjusted for display on dark backgrounds."""
    color = Color(hex_color).convert("oklch")
    lightness, chroma, hue = color.coords()

    # Push darker accents further up the band than already-bright ones.
    brightened = DARK_MODE_LIGHTNESS_BASE + (1.0 - lightness) * DARK_MODE_LIGHTNESS_SPAN

    result = Color("oklch", [brightened, chroma, hue])
    result = result.convert("srgb").fit()

    return result.to_string(hex=True)


def accent_color_declarations(hex_color: str) -> str:
    """Return the light/dark accent CSS declarations for one accent color.

    Both page builders wrap these declarations in their own ``<style>`` block;
    the hover variant is derived here so a recipe whose hero image supplies the
    accent cannot keep the default hover color from the stylesheet.
    """
    dark = dark_mode_color(hex_color)
    return dedent(f"""\
        :root {{
            --food-color: {hex_color};
            --food-color-hover: color-mix(in srgb, {hex_color} {FOOD_COLOR_HOVER_MIX_PERCENT}%, black);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --food-color: {dark};
                --food-color-hover: color-mix(in srgb, {dark} {FOOD_COLOR_HOVER_MIX_PERCENT}%, white);
            }}
        }}""")
