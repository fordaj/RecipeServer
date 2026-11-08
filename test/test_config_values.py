"""Issue #35: configurable server port and food color are wired through."""

from pathlib import Path
from types import SimpleNamespace

from recipeserver.config import Configuration
from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.markdown_to_html import MarkdownToHTMLConverter
from recipeserver.server import Server


def test_server_uses_configured_port():
    config = Configuration()
    config.server_port = 9000

    server = Server(config)

    assert server.port == 9000


def test_server_falls_back_to_default_port_without_config_value():
    server = Server(SimpleNamespace())

    assert server.port == 8000


def test_recipe_page_without_image_uses_configured_food_color(tmp_path: Path):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "plain-rice"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text("# Plain Rice\n\nCook.", encoding="utf-8")
    html_file = site / "plain-rice" / "recipe.html"
    html_file.parent.mkdir(parents=True)

    config = Configuration()
    config.food_color = "#123456"
    converter = MarkdownToHTMLConverter(
        SimpleNamespace(source_directory=source, site_directory=site, food_color=config.food_color)
    )
    converter.convert(recipe, html_file)

    raw_html = html_file.read_text(encoding="utf-8")
    assert converter.heading_color == "#123456"
    assert "--food-color: #123456" in raw_html


def test_index_page_uses_configured_food_color(tmp_path: Path):
    recipe_path = tmp_path / "rice" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<main><h1>Rice</h1></main>", encoding="UTF-8")

    generator = IndexHTMLGenerator(
        SimpleNamespace(site_directory=tmp_path, food_color="#123456")
    )
    generator.add(Recipe({"title": "Rice", "ratings": [{"rating": 8}]}, recipe_path))
    generator.convert()

    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "--food-color: #123456" in index_html
