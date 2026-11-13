from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from types import SimpleNamespace

import frontmatter
import pytest
from bs4 import BeautifulSoup

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.markdown_to_html.overview import build_recipe_overview
from recipeserver.server import (
    RecipeRequestHandler,
    _editor_metadata,
    _validate_editor_metadata,
)


def _write_recipe(path: Path, metadata: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{metadata}---\n# Recipe\n\nBody.\n", encoding="utf-8")


@pytest.fixture()
def archived_server(tmp_path):
    source = tmp_path / "source"
    _write_recipe(source / "Alpha" / "recipe.md", "contributor: Avery\n")
    _write_recipe(source / "Beta" / "recipe.md", "contributor: Blair\narchived: true\n")
    saved = []
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=source,
        on_markdown_saved=saved.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", source
    server.shutdown()
    server.server_close()
    thread.join()


def _post(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return urlopen(request)


def test_editor_metadata_defaults_archived_to_false():
    assert _editor_metadata({})["archived"] is False
    assert _editor_metadata({"archived": True})["archived"] is True
    assert _editor_metadata({"archived": "yes"})["archived"] is False


def test_validate_editor_metadata_rejects_non_boolean_archived():
    assert _validate_editor_metadata({"archived": True})["archived"] is True
    assert _validate_editor_metadata({"archived": False})["archived"] is False
    with pytest.raises(ValueError, match="archived.*boolean"):
        _validate_editor_metadata({"archived": "true"})


def test_index_marks_archived_and_has_unchecked_show_archived(tmp_path):
    for slug, metadata in (("active", {}), ("old", {"archived": True})):
        recipe_path = tmp_path / slug / "index.html"
        recipe_path.parent.mkdir()
        recipe_path.write_text(f"<h1>{slug.title()}</h1>", encoding="UTF-8")
        generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
        generator.add(Recipe(metadata, recipe_path))
        generator.convert()
    # Rebuild with both recipes on one generator for a realistic index.
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    for slug, metadata in (("active", {}), ("old", {"archived": True})):
        generator.add(Recipe(metadata, tmp_path / slug / "index.html"))
    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")
    active = soup.select_one('#recipe-list .recipe[data-title="Active"]')
    old = soup.select_one('#recipe-list .recipe[data-title="Old"]')
    assert active is not None and active["data-archived"] == "false"
    assert old is not None and old["data-archived"] == "true"
    assert old.select_one(".recipe-detail--archived") is not None
    assert "Archived" in old.select_one(".recipe-detail--archived").get_text()
    assert active.select_one(".recipe-detail--archived") is None

    advanced = soup.select_one(".recipe-advanced__content")
    assert advanced is not None
    show_archived = advanced.select_one("#show-archived")
    assert show_archived is not None
    assert show_archived.get("type") == "checkbox"
    assert not show_archived.has_attr("checked")
    assert "Show Archived" in show_archived.parent.get_text()

    index_script = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js").read_text(encoding="UTF-8")
    assert 'recipe.dataset.archived !== "true"' in index_script
    assert 'showArchived.addEventListener("change", update)' in index_script


def test_archived_metadata_api_defaults_false_and_validates(archived_server):
    base, source = archived_server
    query = urlencode({"path": "Alpha/recipe.md"})
    with urlopen(f"{base}/api/metadata/archived?{query}") as response:
        assert json.loads(response.read()) == {"value": False}
    with _post(f"{base}/api/metadata/archived", {"path": "Alpha/recipe.md", "value": True}) as response:
        assert json.loads(response.read())["success"] is True
    assert frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata["archived"] is True
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/metadata/archived", {"path": "Alpha/recipe.md", "value": "yes"})
    assert error.value.code == 400


def test_editor_save_persists_archived(archived_server):
    base, source = archived_server
    with _post(
        f"{base}/api/recipe-editor",
        {
            "path": "Alpha/recipe.md",
            "content": "# Recipe\n\nBody.\n",
            "metadata": {"contributor": "Avery", "archived": True},
        },
    ) as response:
        assert json.loads(response.read())["success"] is True
    metadata = frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata
    assert metadata["archived"] is True


def test_recipe_page_overview_shows_archived_only_when_true():
    archived = build_recipe_overview(
        {"archived": True, "meals": ["Dinner"], "cuisine": ["Thai"]},
        BeautifulSoup("", "html.parser"),
    )
    assert archived is not None
    assert archived.select_one(".recipe-overview__archived") is not None
    assert "Archived" in archived.select_one(".recipe-overview__archived").get_text()
    assert "archive" in str(archived.select_one(".recipe-overview__archived")).lower()

    # Archived lives in its own third row, after the primary and secondary rows.
    tertiary = archived.select_one(".recipe-overview__tertiary")
    assert tertiary is not None
    assert tertiary.select_one(".recipe-overview__archived") is not None
    assert archived.select_one(".recipe-overview__primary .recipe-overview__archived") is None
    assert archived.select_one(".recipe-overview__secondary .recipe-overview__archived") is None
    rows = [child.get("class", [""])[0] for child in archived.find_all("div", recursive=False)]
    assert rows == ["recipe-overview__primary", "recipe-overview__secondary", "recipe-overview__tertiary"]

    active = build_recipe_overview({"archived": False}, BeautifulSoup("", "html.parser"))
    assert active is None or active.select_one(".recipe-overview__archived") is None


def test_archived_overview_icon_has_spacing_and_checkbox_uses_default_size():
    assets = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
    style = (assets / "style.css").read_text(encoding="UTF-8")
    assert ".recipe-overview__archived > svg" in style
    assert ".recipe-overview__tertiary" in style

    editor_css = (assets / "recipe-editor" / "recipe-editor.css").read_text(encoding="UTF-8")
    checkbox_rule = editor_css.split('.recipe-editor__checkbox input[type="checkbox"]')[1].split("}")[0]
    assert "appearance: auto" in checkbox_rule
    assert "width: auto" in checkbox_rule
    assert "height: auto" in checkbox_rule


def test_recipe_editor_has_archived_checkbox():
    base = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
    markup = (base / "details.html").read_text(encoding="UTF-8")
    script = (base / "recipe-editor.js").read_text(encoding="UTF-8")
    assert 'name="archived" type="checkbox"' in markup
    assert 'data-field="archived"' in markup
    assert 'form.elements.namedItem("archived").checked = metadata.archived === true' in script
    assert 'archived: Boolean(refs.form.elements.namedItem("archived")?.checked)' in script
