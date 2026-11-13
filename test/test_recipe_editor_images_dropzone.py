from pathlib import Path

BASE = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"


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
