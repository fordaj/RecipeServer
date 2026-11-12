from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import frontmatter
import pytest
from bs4 import BeautifulSoup
from types import SimpleNamespace

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.server import (
    RecipeRequestHandler,
    _apply_rating_override,
    _validate_bulk_fields,
    _validate_bulk_rating,
)


def _write_recipe(path: Path, metadata: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{metadata}---\n# Recipe\n\nBody.\n", encoding="utf-8")


@pytest.fixture()
def bulk_server(tmp_path):
    source = tmp_path / "source"
    _write_recipe(
        source / "Alpha" / "recipe.md",
        "contributor: Avery\ncategories:\n  - Old\nmeals:\n  - Dinner\nratings:\n  - name: Kim\n    rating: 5\n    id: r1\n    created: '2026-01-01T00:00:00Z'\n    updated: '2026-01-01T00:00:00Z'\n",
    )
    _write_recipe(source / "Beta" / "recipe.md", "contributor: Blair\ncategories:\n  - Other\nmeals:\n  - Lunch\n")
    saved, deleted = [], []
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=source,
        on_markdown_saved=saved.append,
        on_recipes_deleted=deleted.extend,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", source, saved, deleted
    server.shutdown()
    server.server_close()
    thread.join()


def _post(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return urlopen(request)


def test_apply_rating_override_replaces_same_name_and_adds_new(bulk_server):
    base = [{"name": "Kim", "rating": 5, "id": "r1", "created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z"}]
    overridden = _apply_rating_override(base, "kim", 9)
    assert len(overridden) == 1 and overridden[0]["rating"] == 9 and overridden[0]["id"] == "r1"
    added = _apply_rating_override(base, "Andy", 7)
    assert len(added) == 2 and added[1]["name"] == "Andy" and added[1]["id"]


def test_validate_bulk_helpers_reject_bad_input():
    with pytest.raises(ValueError):
        _validate_bulk_fields(["updatedOn"])
    with pytest.raises(ValueError):
        _validate_bulk_rating({"name": "", "rating": 5})
    assert _validate_bulk_rating({"name": "Andy", "score": 8}) == ("Andy", 8)


def test_bulk_editor_get_returns_metadata_and_ratings(bulk_server):
    base, source, _, _ = bulk_server
    query = urlencode({"path": ["Alpha/recipe.md", "Beta/recipe.md"]}, doseq=True)
    with urlopen(f"{base}/api/bulk-editor?{query}") as response:
        data = json.loads(response.read())
    assert [r["path"] for r in data["recipes"]] == ["Alpha/recipe.md", "Beta/recipe.md"]
    assert data["recipes"][0]["metadata"]["contributor"] == "Avery"
    assert data["recipes"][0]["ratings"][0]["name"] == "Kim"


def test_bulk_edit_single_field_does_not_touch_others(bulk_server):
    base, source, saved, _ = bulk_server
    with _post(
        f"{base}/api/bulk-editor",
        {"paths": ["Alpha/recipe.md", "Beta/recipe.md"], "metadata": {"categories": ["Slow Cooker"]}, "fields": ["categories"]},
    ) as response:
        assert json.loads(response.read())["count"] == 2
    alpha = frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata
    beta = frontmatter.loads((source / "Beta" / "recipe.md").read_text()).metadata
    assert alpha["categories"] == ["Slow Cooker"] and alpha["contributor"] == "Avery" and alpha["meals"] == ["Dinner"]
    assert beta["categories"] == ["Slow Cooker"] and beta["contributor"] == "Blair"
    assert len(saved) == 2


def test_bulk_edit_rating_merges_by_name(bulk_server):
    base, source, _, _ = bulk_server
    with _post(f"{base}/api/bulk-editor", {"paths": ["Alpha/recipe.md", "Beta/recipe.md"], "rating": {"name": "Kim", "rating": 9}}) as response:
        assert json.loads(response.read())["success"] is True
    alpha = frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata
    beta = frontmatter.loads((source / "Beta" / "recipe.md").read_text()).metadata
    assert alpha["ratings"][0]["rating"] == 9 and len(alpha["ratings"]) == 1
    assert beta["ratings"][0]["name"] == "Kim" and beta["ratings"][0]["rating"] == 9


def test_bulk_edit_prechecks_and_validates(bulk_server):
    base, source, _, _ = bulk_server
    with pytest.raises(HTTPError) as error:
        _post(
            f"{base}/api/bulk-editor",
            {"paths": ["Alpha/recipe.md", "Missing/recipe.md"], "metadata": {"categories": ["X"]}, "fields": ["categories"]},
        )
    assert error.value.code == 404
    # Nothing written for Alpha either.
    assert frontmatter.loads((source / "Alpha" / "recipe.md").read_text()).metadata["categories"] == ["Old"]
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/bulk-editor", {"paths": [], "metadata": {"categories": ["X"]}})
    assert error.value.code == 400


def test_bulk_delete_removes_files_and_notifies(bulk_server):
    base, source, _, deleted = bulk_server
    with _post(f"{base}/api/bulk-delete", {"paths": ["Alpha/recipe.md", "Beta/recipe.md"]}) as response:
        assert json.loads(response.read()) == {"success": True, "paths": ["Alpha/recipe.md", "Beta/recipe.md"], "count": 2}
    assert not (source / "Alpha" / "recipe.md").exists()
    assert not (source / "Beta" / "recipe.md").exists()
    assert len(deleted) == 2
    with pytest.raises(HTTPError) as error:
        _post(f"{base}/api/bulk-delete", {"paths": ["../outside.md"]})
    assert error.value.code == 400


def test_bulk_mixed_and_save_live_inside_field_labels_hidden_by_default():
    base = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
    script = (base / "recipe-editor.js").read_text(encoding="UTF-8")
    css = (base / "recipe-editor.css").read_text(encoding="UTF-8")
    markup = "".join(
        (base / name).read_text(encoding="UTF-8") for name in ("form.html", "files.html", "ai.html", "details.html", "sources.html", "ratings.html")
    )
    # Each metadata field label contains a hidden * MIXED span and a hidden Save button inside its input control.
    assert markup.count('<span class="recipe-editor__mixed" hidden>* MIXED</span>') >= 12
    assert markup.count('class="recipe-editor__bulk-field-save"') >= 12
    assert 'class="recipe-editor__field-control"' in markup
    assert 'data-field="categories"' in markup and 'data-field="source"' in markup and 'data-field="rating"' in markup
    # Old standalone bulk panel is gone.
    assert "Save Individual Fields" not in script and "Save Individual Fields" not in markup
    assert "recipe-editor__bulk-field-actions" not in script and "recipe-editor__bulk-field-actions" not in markup
    # Mixed/save are toggled (unhidden) rather than created/removed.
    assert "badge.hidden = false" in script
    assert "button.hidden = !visible" in script
    assert "dialog.classList.toggle('is-bulk', visible)" in script or 'dialog.classList.toggle("is-bulk"' in script
    assert "setupBulkFieldButtons()" in script
    assert ".recipe-editor__mixed[hidden]" in css
    assert ".recipe-editor__bulk-field-save[hidden]" in css
    assert ".recipe-editor__field-control" in css
    # Little Save buttons use the same filled styling as the main Save button.
    bulk_save = css.split(".recipe-editor__bulk-field-save {")[1].split("}")[0]
    assert "background: var(--food-color)" in bulk_save and "color: var(--page-bg)" in bulk_save
    assert "background: var(--card-bg)" not in bulk_save
    bulk_hover = css.split(".recipe-editor__bulk-field-save:hover:not(:disabled) {")[1].split("}")[0]
    assert "var(--food-color-hover)" in bulk_hover


def test_index_renders_selection_mode_and_bulk_controls(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    (recipe_path.parent / "image.webp").write_bytes(b"img")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()
    soup = BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")
    # The Selection Mode checkbox is gone: it is now a Select/Cancel
    # button in the bulk controls bar.
    assert soup.select_one("#bulk-selection-mode") is None
    assert soup.select_one(".bulk-selection-toggle") is None
    assert soup.select_one("#bulk-controls") is not None
    selection_toggle = soup.select_one("#bulk-selection-toggle")
    assert selection_toggle is not None and selection_toggle["type"] == "button"
    assert selection_toggle.get_text(strip=True) == "Select"
    assert selection_toggle.find_parent("div", class_="bulk-controls") is not None
    # The bulk actions only appear in selection mode, so they start hidden.
    assert soup.select_one("#bulk-controls").get("hidden") is None
    assert soup.select_one(".select-all-control").get("hidden") is not None
    for control_id in ("clear-selections", "bulk-delete", "shopping-list", "bulk-edit", "bulk-selection-count"):
        assert soup.select_one(f"#{control_id}").get("hidden") is not None
    assert soup.select_one("#bulk-edit").get_text(strip=True) == "Bulk Edit"
    assert soup.select_one("#clear-selections").get_text(strip=True) == "Clear Selections"
    # Select All lives in the bulk controls with the other bulk actions.
    select_all = soup.select_one("#select-all")
    assert select_all is not None and select_all["type"] == "checkbox"
    assert select_all.find_parent("div", class_="bulk-controls") is not None
    assert "Select All" in select_all.find_parent("label").get_text(strip=True)
    # Order left-to-right: Clear Selections, Delete Selected, Shopping List,
    # Bulk Edit, then the Select button on the far right.
    button_ids = [b["id"] for b in soup.select("#bulk-controls button")]
    assert button_ids == [
        "clear-selections",
        "bulk-delete",
        "shopping-list",
        "bulk-edit",
        "bulk-selection-toggle",
    ]
    # The selection count sits directly to the left of the Select button,
    # which closes the bar on the far right.
    selection_count = soup.select_one("#bulk-selection-count")
    assert selection_count.get_text(strip=True) == "0 selected"
    assert selection_count.find_next_sibling() is selection_toggle
    status_group = selection_toggle.find_parent("span", class_="bulk-controls__status")
    assert status_group is not None and selection_count.find_parent("span", class_="bulk-controls__status") is status_group
    assert soup.select_one("#bulk-controls").find_all(recursive=False)[-1] is status_group
    assert soup.select_one("#shopping-list").get_text(strip=True) == "Shopping List"
    index_css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.css").read_text(encoding="UTF-8")
    # Bulk Edit and Shopping List share the filled style.
    assert ".bulk-controls #bulk-edit,\n.bulk-controls #shopping-list {" in index_css
    assert "background: var(--food-color)" in index_css
    assert ".bulk-controls #bulk-delete" in index_css and "background: var(--danger-color)" in index_css
    # Selection mode must not show a native text highlight.
    assert ".select-all-control" in index_css
    assert "#recipe-list.selection-mode .recipe-card" in index_css and "user-select: none" in index_css
    # The hidden bulk actions have to beat their own display rules.
    assert ".bulk-controls [hidden]" in index_css
    # Select is the primary action; Cancel steps back to the outline style.
    assert ".bulk-controls #bulk-selection-toggle {" in index_css
    assert ".bulk-controls.is-selection-mode #bulk-selection-toggle {" in index_css
    index_js = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js").read_text(encoding="UTF-8")
    # The Select/Cancel button drives selection mode; the old checkbox is
    # no longer wired up.
    assert 'document.querySelector("#bulk-selection-toggle")' in index_js
    assert 'document.querySelectorAll("#bulk-controls [data-selection-only]")' in index_js
    assert 'selectionToggle.addEventListener("click", () => setSelectionMode(!selectionModeEnabled))' in index_js
    assert 'selectionToggleLabel.textContent = enabled ? "Cancel" : "Select"' in index_js
    assert "#bulk-selection-mode" not in index_js
    # Plain click toggles (no separate Ctrl behavior) and Ctrl+Shift
    # (or Cmd+Shift) adds a File Explorer-style range from the anchor.
    assert "selectionAnchor" in index_js
    assert "event.shiftKey && (event.ctrlKey || event.metaKey)" in index_js
    assert "event.shiftKey" in index_js
    assert "applyMultiSelect" in index_js
    assert "visible.slice(start, end + 1)" in index_js
    # Range adds without clearing, plain click toggles without clearing.
    range_block = index_js.split("const isRangeClick")[1].split("updateBulkControls();")[0]
    assert "selectBoxes.forEach" not in range_block
    # A click on the checkbox keeps the state the browser already toggled.
    assert "targetBox.checked = checked ?? !targetBox.checked" in index_js
    assert "selectBoxes.forEach" not in index_js.split("const applyMultiSelect")[1].split("updateBulkControls();")[0]
    # The click on the checkbox must not be cancelled, or the browser would
    # restore the state it toggled.
    checkbox_block = index_js.split("selectBoxes.forEach((box)")[1].split("});")[0]
    assert "event.preventDefault()" not in checkbox_block
    # The selection control has its own handler, so the card handler must
    # leave it alone instead of toggling the recipe a second time.
    assert 'event.target.closest(".recipe-select")' in index_js
    # Shift+click must not form a native text selection.
    assert 'list.addEventListener("mousedown"' in index_js and "event.shiftKey" in index_js
    # Select All selects/deselects recipes in view and stays synced.
    assert 'document.querySelector("#select-all")' in index_js
    assert "selectAll.indeterminate" in index_js and "visibleRecipes()" in index_js
    box = soup.select_one(".recipe-select__checkbox")
    assert box is not None and box["data-path"] == "soup/recipe.md"
    assert soup.select_one("#recipe-list .recipe")["data-path"] == "soup/recipe.md"
    # The checkbox sits inside the card so it can overlay the image (upper-left).
    assert box.find_parent("article", class_="recipe-card") is not None
