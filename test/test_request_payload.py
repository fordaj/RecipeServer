"""Body parsing and upload staging live outside the HTTP handler."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from recipeserver.request_payload import (
    RequestTooLarge,
    read_ai_recipe_payload,
    read_json_payload,
    read_recipe_payload,
    remove_uploaded_images,
    validate_uploaded_images,
    write_uploaded_images,
)


def _json_request(payload: bytes, *, max_size: int = 1000) -> dict:
    headers = {"Content-Length": str(len(payload))}
    return read_json_payload(BytesIO(payload), headers, max_size)


def _multipart(fields: dict[str, str], files: list[tuple[str, str, bytes]]) -> tuple[bytes, dict[str, str]]:
    boundary = "----recipetest"
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, filename, content in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))}


def _png() -> bytes:
    from io import BytesIO as Bytes
    from PIL import Image

    buffer = Bytes()
    Image.new("RGB", (4, 4)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_read_json_payload_parses_objects_and_rejects_bad_bodies():
    assert _json_request(b'{"a": 1}') == {"a": 1}
    with pytest.raises(ValueError, match="Invalid JSON"):
        _json_request(b"{")
    with pytest.raises(ValueError, match="JSON object"):
        _json_request(b"[1]")
    with pytest.raises(ValueError, match="Content-Length"):
        read_json_payload(BytesIO(b"{}"), {}, 100)
    with pytest.raises(RequestTooLarge, match="too large"):
        _json_request(b"{}", max_size=1)


def test_multipart_recipe_payload_normalizes_booleans_and_metadata():
    body, headers = _multipart({"createFolder": "true", "metadata": '{"categories": ["Dinner"]}'}, [])
    payload, images = read_recipe_payload(BytesIO(body), headers, 1000, 1000)

    assert payload["createFolder"] is True
    assert payload["metadata"] == {"categories": ["Dinner"]}
    assert images == []

    body, headers = _multipart({"createFolder": "maybe"}, [])
    with pytest.raises(ValueError, match="createFolder"):
        read_recipe_payload(BytesIO(body), headers, 1000, 1000)


def test_multipart_ai_payload_accepts_images_and_stream_flag():
    body, headers = _multipart({"stream": "false"}, [("images", "photo.png", _png())])
    payload, images = read_ai_recipe_payload(BytesIO(body), headers, 1000, 1000)

    assert payload["stream"] is False
    assert images and images[0][0] == "photo.png"


def test_validate_uploaded_images_enforces_limits_and_rejects_duplicates():
    image = _png()
    assert validate_uploaded_images([("a.png", image)], max_count=2, max_size=len(image)) == [("a.png", image)]
    with pytest.raises(ValueError, match="no more than"):
        validate_uploaded_images([("a.png", image), ("b.png", image)], max_count=1, max_size=1000)
    with pytest.raises(ValueError, match="Duplicate"):
        validate_uploaded_images([("a.png", image), ("A.PNG", image)], max_count=5, max_size=1000)
    with pytest.raises(RequestTooLarge):
        validate_uploaded_images([("a.png", image)], max_count=5, max_size=1)


def test_staging_rolls_back_on_collision(tmp_path: Path):
    (tmp_path / "taken.png").write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        write_uploaded_images(tmp_path, [("a.png", _png()), ("taken.png", _png())])
    assert not (tmp_path / "a.png").exists(), "the first staged image must be rolled back"

    written = write_uploaded_images(tmp_path, [("ok.png", _png())])
    assert written == [tmp_path / "ok.png"]
    remove_uploaded_images(written)
    assert not written[0].exists()
