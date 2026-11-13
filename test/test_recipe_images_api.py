"""Tests for the recipe images API: listing the images that sit next to a
recipe Markdown file, and renaming, uploading, and deleting them."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

from test.helpers import png_bytes, request_json, running_recipe_server


def _multipart_body(fields: dict, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "----recipeserver-test-boundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for filename, content in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode() + content + b"\r\n",
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _post_multipart(url: str, fields: dict, files: list[tuple[str, bytes]]) -> tuple[int, dict]:
    body, boundary = _multipart_body(fields, files)
    request = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        body_bytes = error.read()
        try:
            parsed = json.loads(body_bytes) if body_bytes else {}
        except json.JSONDecodeError:
            parsed = {"error": body_bytes.decode("utf-8", errors="replace")}
        return error.code, parsed


def _make_recipe(source: Path, name: str = "recipe.md", body: str = "# Soup\n\nBody.\n") -> Path:
    source.mkdir(parents=True, exist_ok=True)
    recipe = source / name
    recipe.write_text(f"---\nmeals:\n  - Dinner\n---\n{body}", encoding="utf-8", newline="\n")
    return recipe


def _write_png(path: Path) -> None:
    Image.new("RGB", (4, 4), (200, 70, 30)).save(path)


def test_recipe_editor_get_lists_images_next_to_markdown(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = _make_recipe(source, body="# Soup\n\n![Soup](IMG_1.png)\n")
    _write_png(source / "IMG_1.png")
    _write_png(source / "another.jpg")
    (source / "notes.txt").write_text("not an image", encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/recipe-editor?{urlencode({'path': 'recipe.md'})}")

    assert status == 200
    assert [image["name"] for image in body["images"]] == ["IMG_1.png", "another.jpg"]
    assert [image["url"] for image in body["images"]] == ["/IMG_1.png", "/another.jpg"]


def test_recipe_editor_get_image_url_is_root_absolute_and_encoded(tmp_path: Path):
    source = tmp_path / "recipes"
    nested = source / "Dinner" / "Soup Time"
    recipe = _make_recipe(nested, body="# Soup\n")
    _write_png(nested / "my image.png")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/recipe-editor?{urlencode({'path': 'Dinner/Soup Time/recipe.md'})}")

    assert status == 200
    assert body["images"] == [{"name": "my image.png", "url": "/Dinner/Soup%20Time/my%20image.png"}]


def test_rename_updates_file_and_markdown_references(tmp_path: Path):
    source = tmp_path / "recipes"
    body = "# Soup\n\n![Hero](IMG_123.jpg)\n\n![Decoy](chocolate-IMG_123.jpg)\n"
    recipe = _make_recipe(source, body=body)
    _write_png(source / "IMG_123.jpg")
    _write_png(source / "chocolate-IMG_123.jpg")

    with running_recipe_server(source) as (base_url, saved_paths, _):
        status, body_response = request_json(
            f"{base_url}/api/recipe-images/rename",
            {"path": "recipe.md", "from": "IMG_123.jpg", "to": "hero.jpg"},
        )

    assert status == 200
    assert body_response["success"] is True
    assert [image["name"] for image in body_response["images"]] == ["chocolate-IMG_123.jpg", "hero.jpg"]
    assert (source / "hero.jpg").is_file()
    assert not (source / "IMG_123.jpg").exists()

    updated = recipe.read_text(encoding="utf-8")
    assert "![Hero](hero.jpg)" in updated
    # The decoy name merely contains the old filename; it must survive.
    assert "![Decoy](chocolate-IMG_123.jpg)" in updated
    assert saved_paths == [recipe.resolve()]


def test_rename_updates_angle_bracketed_and_url_encoded_references(tmp_path: Path):
    source = tmp_path / "recipes"
    body = "# Soup\n\n![Hero](<my image.png>)\n\n![Other](my%20image.png)\n"
    recipe = _make_recipe(source, body=body)
    _write_png(source / "my image.png")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(
            f"{base_url}/api/recipe-images/rename",
            {"path": "recipe.md", "from": "my image.png", "to": "soup.png"},
        )

    assert status == 200
    updated = recipe.read_text(encoding="utf-8")
    assert "![Hero](<soup.png>)" in updated
    assert "![Other](soup.png)" in updated


def test_rename_removes_stale_site_copy_and_regenerates(tmp_path: Path):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    nested = source / "Dinner"
    recipe = _make_recipe(nested)
    _write_png(nested / "IMG_1.png")
    site_directory = site / "Dinner"
    site_directory.mkdir(parents=True)
    stale = site_directory / "IMG_1.png"
    stale.write_bytes(png_bytes())

    with running_recipe_server(source, directory=str(site)) as (base_url, saved_paths, _):
        status, _ = request_json(
            f"{base_url}/api/recipe-images/rename",
            {"path": "Dinner/recipe.md", "from": "IMG_1.png", "to": "hero.png"},
        )

    assert status == 200
    assert not stale.exists()
    assert saved_paths == [recipe.resolve()]


def test_rename_rejects_invalid_input(tmp_path: Path):
    source = tmp_path / "recipes"
    _make_recipe(source)
    _write_png(source / "IMG_1.png")
    (source / "notes.txt").write_text("x", encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "missing.png", "to": "hero.png"})
        assert status == 404

        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "notes.txt", "to": "hero.png"})
        assert status == 400

        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "IMG_1.png", "to": "hero.txt"})
        assert status == 400

        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "IMG_1.png", "to": "IMG_1.png"})
        assert status == 400

        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "IMG_1.png", "to": "../hero.png"})
        assert status == 400

        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "../recipe.md", "from": "IMG_1.png", "to": "hero.png"})
        assert status == 400

    _write_png(source / "existing.png")
    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/recipe-images/rename", {"path": "recipe.md", "from": "IMG_1.png", "to": "existing.png"})
        assert status == 409
        assert "already exists" in body["error"]


def test_upload_saves_image_to_folder_and_returns_listing(tmp_path: Path):
    source = tmp_path / "recipes"
    nested = source / "Dinner"
    recipe = _make_recipe(nested)

    with running_recipe_server(source) as (base_url, saved_paths, _):
        status, body = _post_multipart(
            f"{base_url}/api/recipe-images/upload",
            {"path": "Dinner/recipe.md"},
            [("pasted.png", png_bytes())],
        )

    assert status == 200
    assert body["success"] is True
    assert [image["name"] for image in body["images"]] == ["pasted.png"]
    assert (nested / "pasted.png").is_file()
    assert saved_paths == [recipe.resolve()]


def test_upload_rejects_duplicate_and_validates_input(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = _make_recipe(source)
    _write_png(source / "existing.png")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_multipart(
            f"{base_url}/api/recipe-images/upload",
            {"path": "recipe.md"},
            [("existing.png", png_bytes())],
        )
        assert status == 409
        assert "already exists" in body["error"]

        status, body = _post_multipart(
            f"{base_url}/api/recipe-images/upload",
            {"path": "recipe.md"},
            [],
        )
        assert status == 400

        status, body = _post_multipart(
            f"{base_url}/api/recipe-images/upload",
            {"path": "missing.md"},
            [("new.png", png_bytes())],
        )
        assert status == 404

        status, body = _post_multipart(
            f"{base_url}/api/recipe-images/upload",
            {"path": "recipe.md"},
            [("notes.txt", b"not an image")],
        )
        assert status == 400

    assert recipe.is_file()


def test_delete_removes_file_and_reports_markdown_reference(tmp_path: Path):
    source = tmp_path / "recipes"
    body = "# Soup\n\n![Hero](IMG_1.png)\n\n![Body](keep.png)\n"
    recipe = _make_recipe(source, body=body)
    _write_png(source / "IMG_1.png")
    _write_png(source / "keep.png")

    with running_recipe_server(source) as (base_url, saved_paths, _):
        status, body_response = request_json(
            f"{base_url}/api/recipe-images/delete",
            {"path": "recipe.md", "name": "IMG_1.png"},
        )

    assert status == 200
    assert body_response["success"] is True
    assert body_response["referenced"] is True
    assert [image["name"] for image in body_response["images"]] == ["keep.png"]
    assert not (source / "IMG_1.png").exists()
    # The Markdown is left untouched; only the reference flag is reported.
    assert "![Hero](IMG_1.png)" in recipe.read_text(encoding="utf-8")
    assert saved_paths == [recipe.resolve()]


def test_delete_unreferenced_image_reports_false(tmp_path: Path):
    source = tmp_path / "recipes"
    _make_recipe(source, body="# Soup\n\n![Hero](keep.png)\n")
    _write_png(source / "unused.png")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe-images/delete",
            {"path": "recipe.md", "name": "unused.png"},
        )

    assert status == 200
    assert body["referenced"] is False


def test_delete_drops_stale_site_copy_and_validates_input(tmp_path: Path):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    nested = source / "Dinner"
    _make_recipe(nested)
    _write_png(nested / "IMG_1.png")
    site_directory = site / "Dinner"
    site_directory.mkdir(parents=True)
    stale = site_directory / "IMG_1.png"
    stale.write_bytes(png_bytes())

    with running_recipe_server(source, directory=str(site)) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe-images/delete",
            {"path": "Dinner/recipe.md", "name": "IMG_1.png"},
        )
        assert status == 200
        assert not stale.exists()

        status, body = request_json(
            f"{base_url}/api/recipe-images/delete",
            {"path": "Dinner/recipe.md", "name": "missing.png"},
        )
        assert status == 404

        status, body = request_json(
            f"{base_url}/api/recipe-images/delete",
            {"path": "Dinner/recipe.md", "name": "../escape.png"},
        )
        assert status == 400


def test_rename_reports_regeneration_failure_after_success(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = _make_recipe(source, body="# Soup\n\n![Hero](IMG_1.png)\n")
    _write_png(source / "IMG_1.png")

    def fail_regen(_path):
        raise RuntimeError("regen failed")

    with running_recipe_server(source, on_markdown_saved=fail_regen) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe-images/rename",
            {"path": "recipe.md", "from": "IMG_1.png", "to": "hero.png"},
        )

    assert status == 500
    assert "regeneration failed" in body["error"]
    assert [image["name"] for image in body["images"]] == ["hero.png"]
    assert "hero.png" in recipe.read_text(encoding="utf-8")
