from datetime import date
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

import py7zr
import pytest
from bs4 import BeautifulSoup

from recipeserver.archive import (
    archive_filename,
    create_archive,
    resolve_archive_date,
)
from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.menu import MENU_CSS_URL, MENU_JS_URL, sandwich_menu_html
from recipeserver.server import RecipeRequestHandler


def _start_server(tmp_path: Path) -> tuple[ThreadingHTTPServer, str]:
    source = tmp_path / "source"
    (source / "Recipe" / "nested").mkdir(parents=True)
    (source / "Recipe" / "recipe.md").write_text("# Sample\n", encoding="utf-8")
    (source / "Recipe" / "nested" / "note.txt").write_text("note\n", encoding="utf-8")
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<h1>Index</h1>", encoding="utf-8")

    handler = partial(
        RecipeRequestHandler,
        directory=str(site),
        source_directory=source,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_archive_filename_uses_browser_date_and_kind():
    assert archive_filename("source", date(2026, 11, 6)) == "2026-11-06_RecipeServer_Source.7z"
    assert archive_filename("site", date(2026, 11, 6)) == "2026-11-06_RecipeServer_Site.7z"

    with pytest.raises(ValueError):
        archive_filename("unknown", date(2026, 11, 6))


def test_resolve_archive_date_parses_browser_date_and_rejects_bad_values():
    assert resolve_archive_date("2026-11-06") == date(2026, 11, 6)
    # No date from the browser: fall back to the supplied (UTC) date.
    assert resolve_archive_date(None, fallback=date(2026, 11, 7)) == date(2026, 11, 7)
    assert resolve_archive_date("", fallback=date(2026, 11, 7)) == date(2026, 11, 7)

    for bad in ("2026/11/06", "not-a-date", "2026-13-01", "20261106", "../2026-11-06"):
        with pytest.raises(ValueError):
            resolve_archive_date(bad)


def test_create_archive_roundtrips_directory_contents(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Breads" / "Baguette").mkdir(parents=True)
    (source / "Breads" / "Baguette" / "recipe.md").write_text("# Baguette\n", encoding="utf-8")
    (source / "Breads" / "Baguette" / "photo.png").write_bytes(b"\x89PNG")

    archive_path = tmp_path / "out.7z"
    create_archive(source, archive_path)

    assert archive_path.is_file() and archive_path.stat().st_size > 0
    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        names = {name.replace("\\", "/") for name in archive.getnames()}
    assert any(name.endswith("Breads/Baguette/recipe.md") for name in names)
    assert any(name.endswith("Breads/Baguette/photo.png") for name in names)


def test_sandwich_menu_html_uses_menu_icon_and_both_downloads():
    html = sandwich_menu_html()
    soup = BeautifulSoup(html, "html.parser")

    menu = soup.select_one(".sandwich-menu")
    assert menu is not None
    toggle = menu.select_one(".sandwich-menu__toggle")
    assert toggle is not None
    assert toggle.get("aria-expanded") == "false"
    assert toggle.get("aria-label") == "Menu"
    # menu.svg (three strokes, Lucide "menu") threaded through verbatim.
    assert toggle.select_one("svg") is not None
    assert 'd="M4 5h16"' in html
    assert 'd="M4 12h16"' in html
    assert 'd="M4 19h16"' in html

    items = menu.select(".sandwich-menu__item")
    archive_items = [
        (item["data-archive"], item.get_text(strip=True))
        for item in items
        if item.has_attr("data-archive")
    ]
    assert archive_items == [
        ("source", "Download Source Archive"),
        ("site", "Download Site Archive"),
    ]
    config_items = [
        item for item in items if item.get("data-config") == "open"
    ]
    assert [item.get_text(strip=True) for item in config_items] == ["Configuration"]


def test_index_page_includes_sandwich_menu_and_assets(tmp_path: Path):
    recipe_path = tmp_path / "cinnamon-rolls" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Cinnamon Rolls</h1>", encoding="UTF-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"title": "Cinnamon Rolls"}, recipe_path))
    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")

    # Menu sits top-left of the header, mirrored against the + button.
    header = soup.select_one(".recipes-header")
    assert header is not None
    menu = header.select_one(".sandwich-menu")
    assert menu is not None
    assert header.index(menu) < header.index(soup.select_one("h1"))

    hrefs = [link["href"] for link in soup.select('link[rel="stylesheet"]')]
    assert MENU_CSS_URL in hrefs
    srcs = [script["src"] for script in soup.select("script[src]")]
    assert MENU_JS_URL in srcs
    assert 'data-archive="source"' in page
    assert 'data-archive="site"' in page
    assert "Download Source Archive" in page
    assert "Download Site Archive" in page
    assert 'data-config="open"' in page


def test_archive_endpoints_download_7z_with_browser_date_filename(tmp_path: Path):
    server, base_url = _start_server(tmp_path)
    try:
        for kind, filename in (
            ("source", "2026-11-06_RecipeServer_Source.7z"),
            ("site", "2026-11-06_RecipeServer_Site.7z"),
        ):
            with urlopen(f"{base_url}/api/archive/{kind}?date=2026-11-06") as response:
                assert response.headers["Content-Type"] == "application/x-7z-compressed"
                assert response.headers["Content-Disposition"] == f'attachment; filename="{filename}"'
                body = response.read()
            assert body[:6] == b"7z\xbc\xaf\x27\x1c"

            archive_path = tmp_path / filename
            archive_path.write_bytes(body)
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                names = {name.replace("\\", "/") for name in archive.getnames()}
            if kind == "source":
                assert any(name.endswith("Recipe/recipe.md") for name in names)
            else:
                assert any(name.endswith("index.html") for name in names)

        # Bad date is rejected with the local browser date format.
        with pytest.raises(HTTPError) as error:
            urlopen(f"{base_url}/api/archive/site?date=not-a-date")
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
