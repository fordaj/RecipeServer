from pathlib import Path

BASE = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"


def test_images_dropzone_styling_and_behaviour():
    markup = (BASE / "files.html").read_text(encoding="UTF-8")
    css = (BASE / "recipe-editor.css").read_text(encoding="UTF-8")
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")

    # The images controls sit inside a dropzone wrapper.
    assert 'class="recipe-editor__images"' in markup
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

    # Drag-and-drop and click-to-browse are wired up in the script.
    assert '"dragover"' in script or "'dragover'" in script
    assert "imageDropzone" in script
    assert "is-dragging" in script
    assert "appendImages" in script
