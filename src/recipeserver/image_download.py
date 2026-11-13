"""Download a candidate image found by the web search.

The image URL reaches this module either from a search provider's results or
from the model after it picked one of those results. Either way the URL is
treated as untrusted input: only public HTTP(S) addresses may be requested,
redirects are re-validated, and the payload is size-capped and verified as a
raster image before it is handed to the browser.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, UnidentifiedImageError

from ._logger import logger

# Wikimedia's etiquette asks clients to send a descriptive User-Agent with a
# contact link; anonymous generic agents are throttled (HTTP 429).
USER_AGENT = "RecipeServer/0.1 (https://github.com/fordaj/RecipeServer)"
DOWNLOAD_TIMEOUT_SECONDS = 20
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024

# Content types we can store and the file extension each maps to. SVG is
# deliberately excluded: it is an icon/vector format, not a photo.
IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}
# Extensions accepted when the server does not report a usable content type.
_ALLOWED_URL_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
_PIL_FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}


class ImageDownloadError(RuntimeError):
    """The selected image could not be downloaded or verified."""


@dataclass(frozen=True)
class DownloadedImage:
    """Verified image bytes plus the mime type and extension to store them under."""

    content: bytes
    extension: str
    mime_type: str


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _resolve_addresses(hostname: str) -> list[str]:
    """Resolve a hostname to IP address strings; raises ImageDownloadError on failure."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError) as exc:
        raise ImageDownloadError(f"Unable to resolve the image host: {hostname}") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise ImageDownloadError(f"Unable to resolve the image host: {hostname}")
    return addresses


def validate_external_url(url: str) -> str:
    """Validate that ``url`` is a public HTTP(S) URL, or raise ImageDownloadError.

    Applies the same rules to the initial URL and to every redirect target.
    """
    parsed = urlsplit((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageDownloadError("The image URL must be an http:// or https:// URL")
    hostname = parsed.hostname
    if not hostname:
        raise ImageDownloadError("The image URL must include a host")
    addresses = _resolve_addresses(hostname)
    for address in addresses:
        if not _is_public_address(address):
            raise ImageDownloadError("The image URL points at a non-public address")
    return url


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Re-validate every redirect target before it is requested."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - stdlib hook
        validate_external_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_capped(response, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise ImageDownloadError("The image is too large to download")
        except ValueError:
            pass
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ImageDownloadError("The image is too large to download")
    return body


def _extension_for(content_type: str, url: str, content: bytes) -> str:
    if content_type in IMAGE_CONTENT_TYPES:
        return IMAGE_CONTENT_TYPES[content_type]

    suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
    if suffix in _ALLOWED_URL_SUFFIXES:
        # .jpeg/.tif collapse onto the canonical storage extensions.
        return {".jpeg": ".jpg", ".tif": ".tiff"}.get(suffix, suffix)

    try:
        with Image.open(BytesIO(content)) as image:
            detected = _PIL_FORMAT_EXTENSIONS.get(image.format or "")
    except OSError, UnidentifiedImageError:
        detected = None
    if detected:
        return detected

    raise ImageDownloadError(f"Unsupported image type: {content_type or 'unknown'}")


def download_image(url: str, *, timeout: float = DOWNLOAD_TIMEOUT_SECONDS, max_bytes: int = MAX_DOWNLOAD_BYTES) -> DownloadedImage:
    """Download and verify the image at ``url``.

    Raises :class:`ImageDownloadError` for inaccessible, unsupported,
    oversized, or invalid images. The caller is expected to leave any
    previously selected image untouched when this raises.
    """
    validate_external_url(url)
    opener = build_opener(_SafeRedirectHandler())
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"}, method="GET")
    logger.info(f"Downloading image from {url}")

    try:
        with opener.open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise ImageDownloadError(f"The image host returned HTTP {response.status}")
            # Defense in depth: the final URL after redirects is validated at
            # every hop by _SafeRedirectHandler; this catches anything the
            # handler did not see.
            final_url = response.geturl()
            if final_url and final_url != url:
                validate_external_url(final_url)
            content_type = (response.headers.get_content_type() or "").lower()
            body = _read_capped(response, max_bytes)
    except ImageDownloadError:
        raise
    except HTTPError as exc:
        logger.warning(f"Image download from {url} returned HTTP {exc.code}")
        raise ImageDownloadError(f"The image host returned HTTP {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        logger.warning(f"Image download from {url} failed: {exc}")
        raise ImageDownloadError(f"Unable to download the image: {exc}") from exc

    if content_type == "image/svg+xml":
        raise ImageDownloadError("SVG images are not supported for recipe photos")
    if not body:
        raise ImageDownloadError("The image host returned an empty response")

    try:
        with Image.open(BytesIO(body)) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageDownloadError("The downloaded file is not a valid image") from exc

    extension = _extension_for(content_type, url, body)
    mime_type = next((mime for mime, ext in IMAGE_CONTENT_TYPES.items() if ext == extension), "image/jpeg")
    logger.info(f"Downloaded {len(body)} bytes from {url} (content_type={content_type or 'unknown'})")
    return DownloadedImage(content=body, extension=extension, mime_type=mime_type)
