"""Issue #74: logo.svg uses currentColor and logo.png is generated with the food color."""

import io
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from recipeserver import logo as logo_module
from recipeserver.config import DEFAULT_FOOD_COLOR

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_png_bytes(size=16, color=(141, 85, 66, 255)):
    image = Image.new("RGBA", (size, size), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeSvg2Png:
    """Stand-in for cairosvg.svg2png that records its inputs."""

    def __init__(self):
        self.calls = []

    def svg2png(self, *, bytestring, output_width, output_height):
        self.calls.append(
            {"bytestring": bytestring, "output_width": output_width, "output_height": output_height}
        )
        return make_png_bytes(size=output_width)


@pytest.fixture
def fake_cairosvg(monkeypatch):
    fake = FakeSvg2Png()
    module = types.ModuleType("cairosvg")
    module.svg2png = fake.svg2png
    monkeypatch.setitem(sys.modules, "cairosvg", module)
    return fake


def test_logo_svg_uses_currentcolor_not_a_hardcoded_color():
    svg = logo_module.LOGO_SVG.read_text(encoding="utf-8")
    assert 'stroke="currentColor"' in svg
    assert "coral" not in svg


def test_generate_logo_png_substitutes_food_color_for_currentcolor(fake_cairosvg, tmp_path):
    logo_module.generate_logo_png("#123456", tmp_path / "logo.png")

    (call,) = fake_cairosvg.calls
    rendered = call["bytestring"].decode("utf-8")
    assert "#123456" in rendered
    assert "currentColor" not in rendered
    assert call["output_width"] == call["output_height"] == logo_module.LOGO_SIZE


def test_generate_logo_png_writes_bytes_and_returns_path(tmp_path, fake_cairosvg):
    output = tmp_path / "logo.png"
    result = logo_module.generate_logo_png("#abcdef", output)

    assert result == output
    assert Image.open(output).format == "PNG"


def test_render_logo_png_bytes_returns_png(fake_cairosvg):
    png_bytes = logo_module.render_logo_png_bytes(DEFAULT_FOOD_COLOR)
    image = Image.open(io.BytesIO(png_bytes))
    assert image.format == "PNG"
    assert image.size == (logo_module.LOGO_SIZE, logo_module.LOGO_SIZE)


def test_generate_logo_png_fails_when_logo_svg_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(logo_module, "LOGO_SVG", tmp_path / "missing.svg")
    monkeypatch.setitem(sys.modules, "cairosvg", types.ModuleType("cairosvg"))

    with pytest.raises(FileNotFoundError):
        logo_module.generate_logo_png(DEFAULT_FOOD_COLOR, tmp_path / "logo.png")


def test_generated_logo_png_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "src/recipeserver/assets/logo.png" in gitignore


def test_generated_png_pixel_color_matches_food_color():
    """Render with the real cairosvg when the native cairo library is available."""
    try:
        png_bytes = logo_module.render_logo_png_bytes("#0000ff")
    except (ImportError, OSError):
        pytest.skip("cairosvg native cairo library not available")
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    blue_pixels = [
        pixel[:3] for pixel in image.getdata() if pixel[3] > 128 and pixel[:3] != (0, 0, 0)
    ]
    assert blue_pixels, "expected non-transparent blue pixels in the rendered logo"
    assert all(pixel == (0, 0, 255) for pixel in blue_pixels)
