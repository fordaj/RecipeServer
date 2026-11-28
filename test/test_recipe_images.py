"""Text rules for rewriting image references in recipe Markdown."""

from io import BytesIO

from PIL import Image
import pytest

from recipeserver.recipe_images import (
    basename_of_src,
    fallback_main_image,
    first_image_reference,
    is_external_src,
    replace_image_reference,
    validate_image_content,
    validate_image_filename,
    validate_image_name,
    validate_svg_content,
)


def test_replace_image_reference_does_not_touch_longer_names():
    content = "![a](cake.png) and ![b](chocolate-cake.png)\n"
    assert replace_image_reference(content, "cake.png", "new.png") == "![a](new.png) and ![b](chocolate-cake.png)\n"


def test_replace_image_reference_handles_url_escaped_names():
    content = "![a](my%20cake.png)\n"
    assert replace_image_reference(content, "my cake.png", "new cake.png") == "![a](new%20cake.png)\n"


def test_first_image_reference_prefers_the_earliest_syntax():
    content = 'before <img src="html.png"> then ![md](md.png)\n'
    first = first_image_reference(content)
    assert first["kind"] == "html"
    assert first["src"] == "html.png"


def test_source_helpers_ignore_query_fragment_and_entities():
    assert basename_of_src("dir/a%20b.png?x=1#top") == "a b.png"
    assert basename_of_src("dir/a&amp;b.png") == "a&b.png"
    assert is_external_src("https://example.com/a.png")
    assert not is_external_src("images/a.png")


@pytest.mark.parametrize("name", ["", "..", "../a.png", "C:\\a.png", "CON.png", "a b.png "])
def test_validate_image_filename_rejects_unsafe_names(name: str):
    with pytest.raises(ValueError):
        validate_image_filename(name)


def test_validate_image_name_requires_a_supported_extension():
    assert validate_image_name("photo.PNG", field="name") == "photo.PNG"
    with pytest.raises(ValueError, match="supported image extension"):
        validate_image_name("notes.txt", field="name")


def test_validate_image_content_accepts_real_images_and_rejects_garbage():
    buffer = BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    validate_image_content("photo.png", buffer.getvalue())
    with pytest.raises(ValueError, match="Invalid image file"):
        validate_image_content("photo.png", b"not an image")


def test_validate_svg_content_rejects_active_content():
    validate_svg_content("icon.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>')
    for body in (
        b"<!doctype svg><svg/>",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="https://example.com"/></svg>',
    ):
        with pytest.raises(ValueError):
            validate_svg_content("icon.svg", body)


def test_fallback_main_image_uses_remaining_name_or_removes_link():
    original = "![hero](old.png)\n\nBody\n"
    updated, name = fallback_main_image(original, "old.png", ["z.png", "a.png"])
    assert name == "z.png"
    assert "![hero](z.png)" in updated

    updated, name = fallback_main_image(original, "old.png", [])
    assert name is None
    assert "old.png" not in updated
    assert "Body" in updated
