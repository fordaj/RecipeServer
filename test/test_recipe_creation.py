from functools import partial
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import frontmatter
import pytest
from PIL import Image

from recipeserver.server import RecipeRequestHandler


def multipart_body(fields, files):
    boundary = "recipe-server-test"
    parts = []
    for name, value in fields.items():
        parts.append((f"--{boundary}\r\n" f'Content-Disposition: form-data; name="{name}"\r\n\r\n' f"{value}\r\n").encode("utf-8"))
    for name, filename, content in files:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n".encode("ascii") + content + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return boundary, b"".join(parts)


def png_image():
    output = BytesIO()
    Image.new("RGB", (1, 1), color="red").save(output, format="PNG")
    return output.getvalue()


def test_recipe_creation_lists_folders_creates_recipes_and_rejects_conflicts(tmp_path):
    source = tmp_path / "source"
    (source / "Breakfast").mkdir(parents=True)
    (source / "Taken").mkdir()
    (source / "Taken" / "recipe.md").write_text("# Taken\n", encoding="utf-8")
    saved_paths = []
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=source,
        on_markdown_saved=saved_paths.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    def post_recipe(folder, create_folder, content="# New Recipe\n\nInstructions."):
        request = Request(
            f"{base_url}/api/recipe",
            data=json.dumps(
                {
                    "folder": folder,
                    "createFolder": create_folder,
                    "content": content,
                    "metadata": {},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(request)

    def post_recipe_with_image(folder, create_folder, image_name="cover.png", image=None):
        boundary, body = multipart_body(
            {
                "folder": folder,
                "createFolder": str(create_folder).lower(),
                "content": "# New Recipe\n\nInstructions.",
                "metadata": "{}",
            },
            [("images", image_name, image or png_image())],
        )
        request = Request(
            f"{base_url}/api/recipe",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return urlopen(request)

    def post_editor_with_image(path, image_name="detail.png"):
        boundary, body = multipart_body(
            {
                "path": path,
                "content": "# Updated Recipe\n\nInstructions.",
                "metadata": "{}",
            },
            [("images", image_name, png_image())],
        )
        request = Request(
            f"{base_url}/api/recipe-editor",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return urlopen(request)

    try:
        with urlopen(f"{base_url}/api/recipe-folders") as response:
            folders = json.loads(response.read())["folders"]
        assert folders == ["", "Breakfast"]

        with post_recipe("Breakfast", False) as response:
            created = json.loads(response.read())
        breakfast_recipe = source / "Breakfast" / "recipe.md"
        assert created == {"success": True, "path": "Breakfast/recipe.md"}
        assert frontmatter.loads(breakfast_recipe.read_text(encoding="utf-8")).content.startswith("# New Recipe")

        with post_recipe("", True) as response:
            created = json.loads(response.read())
        assert created == {"success": True, "path": "New Recipe/recipe.md"}

        with post_recipe("", True) as response:
            created = json.loads(response.read())
        assert created == {"success": True, "path": "New Recipe (1)/recipe.md"}

        with post_recipe("", True, "# Chicken / Tomato Soup?\n\nInstructions.") as response:
            created = json.loads(response.read())
        assert created == {"success": True, "path": "Chicken Tomato Soup/recipe.md"}

        with post_recipe_with_image("Desserts/Cakes", True) as response:
            created = json.loads(response.read())
        cake_recipe = source / "Desserts" / "Cakes" / "recipe.md"
        assert created == {"success": True, "path": "Desserts/Cakes/recipe.md"}
        assert cake_recipe.is_file()
        assert (cake_recipe.parent / "cover.png").read_bytes() == png_image()

        with post_editor_with_image("Breakfast/recipe.md") as response:
            assert json.loads(response.read()) == {"success": True}
        assert (breakfast_recipe.parent / "detail.png").read_bytes() == png_image()
        assert saved_paths == [
            breakfast_recipe,
            source / "New Recipe" / "recipe.md",
            source / "New Recipe (1)" / "recipe.md",
            source / "Chicken Tomato Soup" / "recipe.md",
            cake_recipe,
            breakfast_recipe,
        ]

        with pytest.raises(HTTPError) as error:
            post_recipe("Taken", False)
        assert error.value.code == 409

        with pytest.raises(HTTPError) as error:
            post_recipe("../outside", True)
        assert error.value.code == 400
        assert not (tmp_path / "outside").exists()

        with pytest.raises(HTTPError) as error:
            post_recipe_with_image("Invalid", True, image_name="not-image.txt")
        assert error.value.code == 400
        assert not (source / "Invalid").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
