"""Shared helpers for HTTP API tests.

Canonical versions of the server/request scaffolding that was copy-pasted
across test modules. Keep file-specific fakes (fake model API handlers,
Configuration input patching, SSE parsing) local to the files that need them.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import frontmatter
from PIL import Image

from recipeserver.server import RecipeRequestHandler


def request_json(url: str, payload: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    if payload is None:
        request = Request(url, method=method or "GET")
    else:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method or "POST",
        )

    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        body = error.read()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body.decode("utf-8", errors="replace")}
        return error.code, parsed


@contextmanager
def running_recipe_server(
    source_directory: Path,
    *,
    directory: str | None = None,
    config=None,
    on_markdown_saved=None,
    on_recipes_deleted=None,
):
    saved_paths: list[Path] = []
    deleted_batches: list[list[Path]] = []

    handler = partial(
        RecipeRequestHandler,
        directory=directory if directory is not None else str(source_directory),
        source_directory=source_directory,
        config=config,
        on_markdown_saved=on_markdown_saved if on_markdown_saved is not None else saved_paths.append,
        on_recipes_deleted=on_recipes_deleted if on_recipes_deleted is not None else deleted_batches.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", saved_paths, deleted_batches
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def write_recipe(path: Path, metadata: dict, body: str = "# Recipe\n\nBody.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{metadata}---\n{body}", encoding="utf-8")


def read_metadata(path: Path) -> dict:
    return frontmatter.loads(path.read_text(encoding="utf-8")).metadata


def read_asset(name: str) -> str:
    return (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / name).read_text(encoding="utf-8")


def write_png(path: Path, color: tuple[int, int, int] = (200, 70, 30)) -> None:
    Image.new("RGB", (8, 8), color).save(path)


def png_bytes(size: int = 1, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()
