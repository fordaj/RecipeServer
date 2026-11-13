import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
CLIPBOARD_PASTE_TEST = Path(__file__).parent / "js" / "clipboard_paste_test.js"


def test_images_dropzone_styling_and_behaviour():
    markup = (BASE / "files.html").read_text(encoding="UTF-8")
    css = (BASE / "recipe-editor.css").read_text(encoding="UTF-8")
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")

    # The images controls sit inside a dropzone wrapper.
    assert 'class="recipe-editor__images recipe-editor__recipe-images"' in markup
    assert 'id="recipe-editor-images"' in markup
    # The help text advertises drag-and-drop, paste, and click-to-choose.
    assert "Drag &amp; drop images here" in markup
    assert "paste them from your clipboard" in markup
    assert "click to choose files" in markup

    # The dropzone is a lighter gray with a dashed outline.
    dropzone = css.split(".recipe-editor__images {")[1].split("}")[0]
    assert "border: 2px dashed" in dropzone
    assert "background: var(--hover-bg)" in dropzone
    assert ".recipe-editor__images:focus-within" in css
    dragging = css.split(".recipe-editor__images.is-dragging {")[1].split("}")[0]
    assert "var(--food-color)" in dragging

    # Drag-and-drop and click-to-browse are wired up by the shared picker.
    assert '"dragover"' in script or "'dragover'" in script
    assert "createImagePicker" in script
    assert "is-dragging" in script


def test_ai_image_picker_reuses_the_images_dropzone():
    markup = (BASE / "ai.html").read_text(encoding="UTF-8")
    css = (BASE / "recipe-editor.css").read_text(encoding="UTF-8")
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")

    # The AI images picker is the same dashed dropzone as the recipe images.
    assert 'class="recipe-editor__images recipe-editor__ai-images"' in markup
    assert 'id="recipe-editor-ai-image"' in markup
    assert "multiple" in markup
    assert "paste them from your clipboard" in markup
    assert "Each image is transcribed in the order it is added." in markup
    # The AI picker keeps its comma-joined name line (it has no staged rows).
    assert "recipe-editor__images-selected" in markup

    # Both pickers come from the shared helper so paste and drag-and-drop
    # behave the same everywhere.
    assert "refs.recipeImages = createImagePicker({" in script
    assert "refs.aiImages = createImagePicker({" in script
    assert 'body.append("images"' in script
    assert "appendImages" not in script

    # The dropzone styling is not duplicated for the AI picker.
    assert ".recipe-editor__ai-images" not in css


def test_images_dropzones_have_a_paste_from_clipboard_button():
    files_markup = (BASE / "files.html").read_text(encoding="UTF-8")
    ai_markup = (BASE / "ai.html").read_text(encoding="UTF-8")
    css = (BASE / "recipe-editor.css").read_text(encoding="UTF-8")
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")
    icon = BASE.parent / "clipboard-paste.svg"

    # Both dropzones carry a "Paste from clipboard" button that starts hidden
    # and is revealed only when the async Clipboard API is available.
    for markup in (files_markup, ai_markup):
        assert 'class="recipe-editor__paste-clipboard" hidden' in markup
        assert "Paste from clipboard" in markup
        assert "recipe-editor__paste-clipboard-icon" in markup

    # The button reads the clipboard through the async Clipboard API, stages
    # the image files, and keeps the dropzone click from opening the picker.
    assert "navigator.clipboard.read" in script
    assert ".recipe-editor__paste-clipboard" in script
    assert icon.is_file()

    # The button is styled as a secondary action and hides when [hidden].
    assert ".recipe-editor__paste-clipboard {" in css
    assert ".recipe-editor__paste-clipboard[hidden]" in css


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_paste_from_clipboard_stages_clipboard_images():
    result = subprocess.run(
        [shutil.which("node"), str(CLIPBOARD_PASTE_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "clipboard paste checks passed" in result.stdout
