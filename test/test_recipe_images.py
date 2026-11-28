"""Text rules for rewriting image references in recipe Markdown."""

from recipeserver.recipe_images import (
    basename_of_src,
    fallback_main_image,
    first_image_reference,
    is_external_src,
    replace_image_reference,
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


def test_fallback_main_image_uses_remaining_name_or_removes_link():
    original = "![hero](old.png)\n\nBody\n"
    updated, name = fallback_main_image(original, "old.png", ["z.png", "a.png"])
    assert name == "z.png"
    assert "![hero](z.png)" in updated

    updated, name = fallback_main_image(original, "old.png", [])
    assert name is None
    assert "old.png" not in updated
    assert "Body" in updated
