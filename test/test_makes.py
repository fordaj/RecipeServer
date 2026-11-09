from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import frontmatter
import pytest

from recipeserver.server import RecipeRequestHandler, _validate_makes


@pytest.mark.parametrize("value", [None, 0, 1, 42])
def test_validate_makes_accepts_non_negative_integers(value):
    assert _validate_makes(value) == value


@pytest.mark.parametrize("value", [-1, 1.5, True, False, "3", [3], {"value": 3}])
def test_validate_makes_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        _validate_makes(value)


def request_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    if payload is None:
        request = Request(url, method="GET")
    else:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def start_server(source: Path, on_markdown_saved=None):
    saved_paths: list[Path] = []
    callback = on_markdown_saved if on_markdown_saved is not None else saved_paths.append
    handler = partial(
        RecipeRequestHandler,
        directory=str(source),
        source_directory=source,
        on_markdown_saved=callback,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    return server, thread, saved_paths


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join()


def test_makes_metadata_endpoint_increments_and_preserves_edit_time(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text(
        '---\nupdatedOn: "2024-06-20T12:30:00Z"\ncustomField: keep me\n---\n# Soup\n',
        encoding="utf-8",
    )
    server, thread, saved_paths = start_server(source)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        # A recipe without a makes field reads as "not found" (client treats it as 0).
        status, body = request_json(f"{base_url}/api/metadata/makes?{urlencode({'path': 'recipe.md'})}")
        assert status == 404

        status, body = request_json(f"{base_url}/api/metadata/makes", {"path": "recipe.md", "value": 3})
        assert status == 200
        assert body == {"success": True, "field": "makes"}
        assert saved_paths == [recipe]

        status, body = request_json(f"{base_url}/api/metadata/makes?{urlencode({'path': 'recipe.md'})}")
        assert status == 200
        assert body == {"value": 3}

        # Invalid values are rejected without touching the file.
        before = recipe.read_bytes()
        for invalid in (-1, 1.5, True, "3", [3]):
            status, _ = request_json(f"{base_url}/api/metadata/makes", {"path": "recipe.md", "value": invalid})
            assert status == 400, invalid
        assert recipe.read_bytes() == before
        assert saved_paths == [recipe]
    finally:
        stop_server(server, thread)

    post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
    assert post.metadata["makes"] == 3
    assert post.metadata["customField"] == "keep me"
    # Per-field saves (like ratings/comments) must not bump updatedOn.
    assert post.metadata["updatedOn"] == "2024-06-20T12:30:00Z"


def test_makes_metadata_endpoint_reports_saved_but_regeneration_failed(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text("---\nmeals: []\n---\n# Soup\n", encoding="utf-8")

    def fail_regen(_path):
        raise RuntimeError("regen failed")

    server, thread, _ = start_server(source, on_markdown_saved=fail_regen)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body = request_json(f"{base_url}/api/metadata/makes", {"path": "recipe.md", "value": 1})
    finally:
        stop_server(server, thread)

    assert status == 500
    assert "saved, but" in body["error"].lower()
    # The make was still written to the file.
    assert frontmatter.loads(recipe.read_text(encoding="utf-8")).metadata["makes"] == 1


def _asset(name: str) -> str:
    assets = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
    path = assets / name
    if not path.exists() and name in {"recipe-editor.js", "recipe-editor.css"}:
        path = assets / "recipe-editor" / name
    return path.read_text(encoding="UTF-8")


def _editor_template(name: str) -> str:
    path = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor" / name
    return path.read_text(encoding="UTF-8")


def test_recipe_editor_made_this_button_is_in_header_and_hidden_when_creating():
    script = _asset("recipe-editor.js")
    form = _editor_template("form.html")

    header = form.split('<header class="recipe-editor__header">')[1].split("</header>")[0]
    assert "recipe-editor__made-this" in header
    assert "I made this!" in header
    assert "hidden" in header
    # The count sits immediately to the left of the button, like the overview.
    assert header.index("recipe-editor__makes-count") < header.index("recipe-editor__made-this")

    # Shown only for existing recipes, mirroring the delete button.
    assert "madeThisButton.hidden = false" in script
    assert "madeThisButton.hidden = true" in script
    assert "madeThisCount.hidden = false" in script
    assert "madeThisCount.hidden = true" in script
    assert 'madeThisButton.addEventListener("click", recordMadeThis)' in script
    # Disabled while the editor is busy, like the other actions.
    assert "madeThisButton.disabled = value" in script


def test_recipe_editor_makes_count_shows_chef_hat_x_count():
    script = _asset("recipe-editor.js")
    form = _editor_template("form.html")
    chef_hat = _asset("chef-hat.svg")

    # The icon is loaded from the shared chef-hat asset, not inlined in JS.
    assert "/assets/chef-hat.svg" in script
    assert "loadSvgIcon" in script
    assert "recipe-editor__makes-icon" in form
    assert "<svg" not in script
    for path_data in (
        "M17 21a1 1 0 0 0 1-1v-5.35c0-.457.316-.844.727-1.041a4 4 0 0 0-2.134-7.589",
        "M6 17h12",
    ):
        assert path_data in chef_hat
    assert 'aria-hidden="true"' in form
    assert 'focusable="false"' in form

    # Count is rendered as x<makecount> beside the button, not in its label.
    assert "function makesCountLabel(makes)" in script
    assert "return `x${makes}`" in script
    assert "madeThisValue.textContent = makesCountLabel(makes)" in script
    assert "I made this! (${" not in script
    assert "madeThisLabel" not in script
    assert "updateMadeThisCount(normalizeMakes(result.metadata.makes))" in script


def test_recipe_editor_markdown_is_in_closed_details():
    script = _asset("recipe-editor.js")
    form = _editor_template("form.html")

    details = form.split('<details class="recipe-editor__details recipe-editor__markdown-details">')[1]
    details = details.split("</details>")[0]
    assert "<summary>Markdown</summary>" in details
    assert 'id="recipe-editor-source"' in details
    assert "recipe-editor__markdown-label" in details
    # Closed by default (no open attribute) and reset every time the dialog opens.
    assert "markdownDetails.open = false" in script
    # A required control inside closed <details> is unfocusable; only require
    # the textarea while the Markdown section is visible.
    assert 'markdownDetails.addEventListener("toggle"' in script
    assert "textarea.required = markdownDetails.open" in script


def test_recipe_editor_made_this_increments_via_metadata_api_with_feedback():
    script = _asset("recipe-editor.js")

    assert "/api/metadata/makes" in script
    assert "getMakes(path)" in script
    assert "saveMakes(path, makes)" in script
    assert "makes = (await getMakes(path)) + 1" in script

    # Full success, saved-but-not-refreshed, and failed saves are distinct.
    assert "Your make was recorded" in script
    assert "Saved your make" in script
    assert "page could not be refreshed" in script
    assert "Couldn't record your make" in script
    assert "/saved, but/i" in script

    # The in-progress editor form/baseline stay in sync after a make.
    assert 'form.elements.namedItem("makes").value' in script
    assert "baseline.makes = makes" in script

    # Fun feedback: sparkle particles + pop animation.
    assert "recipe-editor__sparkle" in script
    assert "is-celebrating" in script
    assert "prefers-reduced-motion" in script


def test_recipe_editor_made_this_css_has_sparkle_animation_and_reduced_motion():
    css = _asset("recipe-editor.css")

    assert ".recipe-editor__made-this" in css
    assert ".recipe-editor__made-this.is-celebrating" in css
    assert "@keyframes recipe-editor-sparkle" in css
    assert "@keyframes recipe-editor-made-this-pop" in css
    assert ".recipe-editor__sparkle" in css
    assert ".recipe-editor__made-this[hidden]" in css

    reduced = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert ".recipe-editor__made-this.is-celebrating" in reduced
    assert ".recipe-editor__sparkle" in reduced
    assert "animation: none" in reduced


def test_recipe_editor_made_this_css_matches_save_button():
    css = _asset("recipe-editor.css")

    made_this = css.split(".recipe-editor__made-this {")[1].split("}")[0]
    save = css.split(".recipe-editor__footer .recipe-editor__save {")[1].split("}")[0]

    # Same filled look as Save: less round than a pill, food-colored fill.
    assert "border-radius: 6px" in made_this
    assert "999px" not in made_this
    assert "background: var(--food-color)" in made_this
    assert "color: var(--page-bg)" in made_this
    assert "border: 1px solid var(--food-color)" in made_this
    assert "background: var(--food-color)" in save
    assert "color: var(--page-bg)" in save

    hover = css.split(".recipe-editor__made-this:hover:not(:disabled) {")[1].split("}")[0]
    assert "var(--food-color-hover)" in hover

    # Only Lato Regular (400) is loaded, so a heavier weight would be
    # synthesized by the browser and render unevenly ("partly bolded").
    assert "font-weight" not in made_this

    # A smidge of extra space before the close button.
    assert "margin-right: 0.35rem" in made_this


def test_recipe_editor_makes_count_css_matches_overview():
    css = _asset("recipe-editor.css")

    count = css.split(".recipe-editor__makes-count {")[1].split("}")[0]
    assert "inline-flex" in count
    assert ".recipe-editor__makes-count[hidden]" in css
    assert ".recipe-editor__makes-count svg" in css


def test_recipe_editor_markdown_details_css():
    css = _asset("recipe-editor.css")

    assert ".recipe-editor__markdown-details .recipe-editor__markdown-label" in css
    assert ".recipe-editor__markdown-details .recipe-editor__source" in css
