"""Source-level checks for the Files section: the existing-images list,
the click-to-set main image UI, and the rename/delete controls."""

import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).parents[1] / "src" / "recipeserver"
ASSETS = BASE / "assets" / "recipe-editor"
STAGED_IMAGES_TEST = Path(__file__).parent / "js" / "recipe_editor_staged_images_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_staged_images_upload_and_delete_flow():
    result = subprocess.run(
        [shutil.which("node"), str(STAGED_IMAGES_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "staged images flow checks passed" in result.stdout


def test_files_section_shows_existing_images_without_dropdown():
    markup = (ASSETS / "files.html").read_text(encoding="utf-8")

    # The main-image dropdown/preview/description are gone; thumbnails and
    # list rows only.
    assert 'id="recipe-editor-main-image"' not in markup
    assert "recipe-editor__main-image" not in markup
    assert "recipe-editor__image-list" in markup
    assert "recipe-editor__staged-images" in markup


def test_thumbnail_button_marks_and_sets_main_image():
    script = (ASSETS / "recipe-editor.js").read_text(encoding="utf-8")
    css = (ASSETS / "recipe-editor.css").read_text(encoding="utf-8")

    # Clicking a thumbnail toggles the hero by rewriting the first image link.
    assert "setMainImage" in script
    assert "recipe-editor__image-main" in script
    assert "aria-pressed" in script
    # The fallback check after a delete points the hero at an alphabetically
    # first remaining image.
    assert "applyMainImageFallback" in script
    assert "renameOccurrences" in script
    # The main image gets a food-color outline and a subtle MAIN badge.
    assert ".recipe-editor__image-main.is-main" in css
    assert ".recipe-editor__main-badge" in css
    assert "var(--food-color)" in css


def test_files_section_stages_uploads_and_deletes_images():
    markup = (ASSETS / "files.html").read_text(encoding="utf-8")
    script = (ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    # Staged images get a row with an Upload button and an X to discard them.
    assert "recipe-editor__staged-images" in markup
    assert "renderStagedImages" in script
    assert "uploadStagedImage" in script
    assert "/api/recipe-images/upload" in script
    # Uploaded images get an X to delete them, inline with rename and the name.
    assert "deleteExistingImage" in script
    assert "/api/recipe-images/delete" in script
    # Both delete paths confirm with the user before acting.
    assert script.count("confirm(") >= 2


def test_staged_upload_wiring_uses_the_assembled_context():
    # Regression: the picker's onChange used to build a partial { refs, state }
    # context without the UI collaborators, so clicking Upload threw before
    # any request was made and the user saw nothing.
    script = (ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert "onChange: () => refs.stagedChangeHandler?.()" in script
    assert "ctx.refs.stagedChangeHandler = () => renderStagedImages(ctx)" in script


def test_main_image_dropdown_is_replaced_by_thumbnail_toggle():
    script = (ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert "mainImageSelect" not in script
    assert "mainImagePreview" not in script
    assert "applyMainImageSelection" not in script
    # The rename flow still reports/rewrites the first img link in the Markdown.
    assert "findFirstImageReference" in script
    assert "/api/recipe-images/rename" in script
    assert "renameOccurrences" in script


def test_rename_endpoint_is_registered_and_images_are_listed():
    server = (BASE / "server.py").read_text(encoding="utf-8")

    assert '"/api/recipe-images/rename"' in server
    assert "_handle_recipe_images_rename_post" in server
    # The editor payload carries the images sitting next to the Markdown file.
    assert '"images": self._list_recipe_images(file_path)' in server
    # The delete endpoint falls the hero back to an alphabetically first image.
    assert "_fallback_main_image" in server


def test_main_image_styles_keep_fields_at_least_16px():
    css = (ASSETS / "recipe-editor.css").read_text(encoding="utf-8")

    for selector in (
        ".recipe-editor__image-name",
        ".recipe-editor__image-rename",
    ):
        block = css.split(f"{selector} {{")[1].split("}")[0]
        assert "2.5rem" in block or "1rem" in block

    assert ".recipe-editor__existing-images[hidden]" in css
    assert "object-fit: cover" in css
