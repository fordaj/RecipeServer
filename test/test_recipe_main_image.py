"""Source-level checks for the Files section: the existing-images list,
the main image dropdown, and the rename control."""

from pathlib import Path

BASE = Path(__file__).parents[1] / "src" / "recipeserver"
ASSETS = BASE / "assets" / "recipe-editor"


def test_files_section_offers_main_image_dropdown_and_thumbnails():
    markup = (ASSETS / "files.html").read_text(encoding="utf-8")

    # The dropdown defaults to None and reports the first image link.
    assert 'id="recipe-editor-main-image"' in markup
    assert '<option value="">None</option>' in markup
    # The thumbnail shows the currently selected image.
    assert "recipe-editor__main-image-preview" in markup
    # The list renders one row per image in the folder, with thumbnails.
    assert "recipe-editor__image-list" in markup


def test_main_image_dropdown_is_wired_to_markdown_and_rename_api():
    script = (ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    # The dropdown reports/rewrites the first img link in the Markdown.
    assert "findFirstImageReference" in script
    assert "applyMainImageSelection" in script
    # "None" removes the first image link instead of leaving a dangling one.
    assert "removeImageSpan" in script
    # Renaming goes through the rename endpoint and fixes references.
    assert "/api/recipe-images/rename" in script
    assert "renameOccurrences" in script


def test_rename_endpoint_is_registered_and_images_are_listed():
    server = (BASE / "server.py").read_text(encoding="utf-8")

    assert '"/api/recipe-images/rename"' in server
    assert "_handle_recipe_images_rename_post" in server
    # The editor payload carries the images sitting next to the Markdown file.
    assert '"images": self._list_recipe_images(file_path)' in server


def test_main_image_styles_keep_fields_at_least_16px():
    css = (ASSETS / "recipe-editor.css").read_text(encoding="utf-8")

    for selector in (
        ".recipe-editor__main-image-select",
        ".recipe-editor__image-name",
        ".recipe-editor__image-rename",
    ):
        block = css.split(f"{selector} {{")[1].split("}")[0]
        assert "2.5rem" in block or "1rem" in block

    assert ".recipe-editor__existing-images[hidden]" in css
    assert "object-fit: cover" in css
