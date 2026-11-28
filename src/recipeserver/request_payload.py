"""Parse request bodies and stage image uploads.

The HTTP handler supplies the binary stream and headers; this module owns the
wire-format rules: Content-Length validation, JSON decoding, multipart parsing,
the two payload dialects used by the editing APIs, and staging uploaded images
on disk. Nothing here needs to know about routes or responses.
"""

from __future__ import annotations

import json
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

from .image_handler import IMAGE_EXTENSIONS
from .recipe_images import validate_image_content, validate_image_filename


class RequestTooLarge(ValueError):
    """The declared body or its images exceed the configured limit."""


def read_body(rfile, headers, max_size: int, too_large_message: str) -> bytes:
    content_length = headers.get("Content-Length")
    if content_length is None:
        raise ValueError("Missing Content-Length")

    try:
        length = int(content_length)
    except ValueError:
        raise ValueError("Invalid Content-Length") from None

    if length < 0:
        raise ValueError("Invalid Content-Length")
    if length > max_size:
        raise RequestTooLarge(too_large_message)

    return rfile.read(length)


def read_json_payload(rfile, headers, max_size: int) -> dict:
    body = read_body(rfile, headers, max_size, "Request body too large")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


def parse_multipart_message(body: bytes, content_type: str) -> Message:
    message = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if not message.is_multipart():
        raise ValueError("Invalid multipart request")
    return message


def is_multipart_request(headers) -> bool:
    return headers.get("Content-Type", "").lower().startswith("multipart/form-data")


def read_multipart_payload(rfile, headers, max_size: int) -> tuple[dict, list[tuple[str, bytes]]]:
    """Read a multipart/form-data body into its text fields and file uploads."""
    content_type = headers.get("Content-Type", "")
    body = read_body(rfile, headers, max_size, "Image upload request too large")
    message = parse_multipart_message(body, content_type)

    payload: dict = {}
    images: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if not isinstance(field_name, str):
            raise ValueError("Invalid multipart field")

        filename = part.get_filename()
        content = part.get_payload(decode=True) or b""
        if filename is not None:
            if field_name != "images":
                raise ValueError("Unexpected uploaded file field")
            images.append((filename, content))
            continue

        try:
            payload[field_name] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Invalid text field: {field_name}") from exc

    return payload, images


def read_ai_recipe_payload(rfile, headers, max_size: int, upload_max_size: int) -> tuple[dict, list[tuple[str, bytes]]]:
    """Read an AI recipe request, which may carry multipart image uploads."""
    if not is_multipart_request(headers):
        return read_json_payload(rfile, headers, max_size), []

    payload, images = read_multipart_payload(rfile, headers, upload_max_size)
    if "stream" in payload:
        if payload["stream"] not in {"true", "false"}:
            raise ValueError("Invalid stream value")
        payload["stream"] = payload["stream"] == "true"
    return payload, images


def read_recipe_payload(rfile, headers, max_size: int, upload_max_size: int) -> tuple[dict, list[tuple[str, bytes]]]:
    if not is_multipart_request(headers):
        return read_json_payload(rfile, headers, max_size), []

    payload, images = read_multipart_payload(rfile, headers, upload_max_size)
    if "metadata" in payload:
        try:
            payload["metadata"] = json.loads(payload["metadata"])
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid metadata JSON") from exc
    if "createFolder" in payload:
        if payload["createFolder"] not in {"true", "false"}:
            raise ValueError("Invalid createFolder value")
        payload["createFolder"] = payload["createFolder"] == "true"

    return payload, images


def validate_uploaded_images(images: list[tuple[str, bytes]], *, max_count: int, max_size: int) -> list[tuple[str, bytes]]:
    if len(images) > max_count:
        raise ValueError(f"Upload no more than {max_count} images at a time")

    validated = []
    names = set()
    total_size = 0
    for filename, content in images:
        validate_image_filename(filename)
        if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {filename}")
        if not content:
            raise ValueError(f"Image is empty: {filename}")
        validate_image_content(filename, content)

        normalized_name = filename.casefold()
        if normalized_name in names:
            raise ValueError(f"Duplicate image filename: {filename}")
        names.add(normalized_name)
        total_size += len(content)
        if total_size > max_size:
            raise RequestTooLarge("Image upload request too large")
        validated.append((filename, content))

    return validated


def write_uploaded_images(directory: Path, images: list[tuple[str, bytes]]) -> list[Path]:
    existing_names = {entry.name.casefold() for entry in directory.iterdir()}
    for filename, _ in images:
        if filename.casefold() in existing_names:
            raise FileExistsError(f"An item named {filename} already exists in the recipe folder")

    written = []
    try:
        for filename, content in images:
            image_path = directory / filename
            with image_path.open("xb") as image_file:
                written.append(image_path)
                image_file.write(content)
    except Exception:
        remove_uploaded_images(written)
        raise
    return written


def remove_uploaded_images(images: list[Path]) -> None:
    for image in images:
        image.unlink(missing_ok=True)
