"""The service worker (assets/sw.js) makes /assets/* resilient to flaky networks.

Both generated page types must register it, and the registration must use a
scope the browser allows from /assets/sw.js (its own directory).
"""

from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess

import pytest

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.markdown_to_html import MarkdownToHTMLConverter

ASSETS_DIR = Path(__file__).resolve().parent.parent / "src" / "recipeserver" / "assets"
SNIPPET_MARKERS = ("serviceWorker", "/assets/sw.js", '"/assets/"', ".register(")


def test_service_worker_file_caches_content_hashed_assets_first():
    sw = (ASSETS_DIR / "sw.js").read_text(encoding="utf-8")

    assert "recipe-assets-v" in sw
    # Content-hashed (?v=...) assets are immutable, so cache-first is correct.
    assert "/assets/" in sw
    # Pages themselves are never cached: the server sends no-store for HTML.
    assert "index.html" not in sw


def test_service_worker_is_valid_javascript():
    if shutil.which("node") is None:
        pytest.skip("node is not available to syntax-check sw.js")
    result = subprocess.run(["node", "--check", str(ASSETS_DIR / "sw.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _make_index(tmp_path: Path) -> str:
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()
    return (tmp_path / "index.html").read_text(encoding="utf-8")


def test_index_page_registers_the_service_worker(tmp_path: Path):
    index = _make_index(tmp_path)

    head = index[index.index("<head>") : index.index("</head>")]
    for marker in SNIPPET_MARKERS:
        assert marker in head


def test_recipe_page_registers_the_service_worker(tmp_path: Path):
    source = tmp_path / "recipes" / "soup"
    source.mkdir(parents=True)
    (source / "recipe.md").write_text("# Soup\n\n## Ingredients\n\n- flour\n", encoding="utf-8")
    html_file = tmp_path / "site" / "soup" / "recipe.html"
    html_file.parent.mkdir(parents=True)
    converter = MarkdownToHTMLConverter(SimpleNamespace(source_directory=tmp_path / "recipes", site_directory=tmp_path / "site"))
    converter.convert(source / "recipe.md", html_file)

    page = html_file.read_text(encoding="utf-8")
    head = page[page.index("<head>") : page.index("</head>")]
    for marker in SNIPPET_MARKERS:
        assert marker in head
