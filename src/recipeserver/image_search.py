"""Web image search for the "Find One For Me" feature.

Searches the Wikimedia Commons file repository through its official, key-less
JSON API (https://commons.wikimedia.org/w/api.php). Commons hosts a large
catalog of freely licensed photographs (including Food photography) and, like
the rest of the project, needs no API key. Every candidate carries a real,
verifiable URL plus source and attribution information, which is what allows
the model to evaluate actual search results instead of inventing URLs.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ._logger import logger

# Wikimedia's etiquette asks clients to send a descriptive User-Agent with a
# contact link; anonymous generic agents are throttled (HTTP 429).
USER_AGENT = "RecipeServer/0.1 (https://github.com/fordaj/RecipeServer)"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
SEARCH_TIMEOUT_SECONDS = 10
# How many candidates to hand to the model. Fewer results make the model's
# choice more reliable; more results make a random pick more meaningful.
SEARCH_RESULT_LIMIT = 12
# Reject thumbnails and icons; a recipe hero image should be at least this
# large on its shorter side when the dimensions are reported.
MIN_IMAGE_SIDE_PIXELS = 400
# The Commons API answers full result sets quickly; cap the response anyway.
MAX_SEARCH_RESPONSE_BYTES = 4 * 1024 * 1024
# Width of the thumbnail renditions we prefer over the original uploads,
# which are routinely tens of megapixels.
THUMBNAIL_WIDTH_PIXELS = 1024
# File extensions we are willing to hand to a recipe page. SVG is excluded:
# it is an icon/vector format, not a photograph.
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_TAG_RE = re.compile(r"<[^>]+>")
# Words that commonly appear in recipe titles/blogs but carry no image-search
# signal; left in, they pull cookbook PDFs and recipe blogs above photos.
_QUERY_NOISE_WORDS = {
    "best",
    "the",
    "a",
    "an",
    "of",
    "and",
    "from",
    "with",
    "recipe",
    "recipes",
    "homemade",
    "easy",
    "quick",
    "simple",
    "authentic",
    "delicious",
    "perfect",
    "classic",
    "how",
    "to",
    "make",
    "cook",
}


def _optimize_query(query: str) -> str:
    """Reduce a recipe title to its search-relevant terms.

    "BEST Teriyaki Sauce Recipe" matches cookbook PDFs under full-text
    search; "teriyaki sauce" finds the dish. Falls back to the raw query
    when filtering would leave nothing behind.
    """
    words = re.findall(r"[a-z0-9']+", query.lower())
    significant = [word for word in words if word not in _QUERY_NOISE_WORDS]
    return " ".join(significant) or query.strip()


class ImageSearchError(RuntimeError):
    """The image web search failed or returned no usable candidates."""


@dataclass(frozen=True)
class ImageCandidate:
    """One image the search turned up, with the source details to preserve."""

    url: str
    source_url: str
    title: str
    attribution: str
    license: str
    width: int | None
    height: int | None


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _html_to_summary(value: object) -> str:
    text = _TAG_RE.sub("", _clean_text(value))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip(" .,;-")


def _strip_tracking_params(url: str) -> str:
    """Drop utm_* share parameters from a URL; they carry no information."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def _clean_dimension(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _min_dimension(thumb: object, original: object) -> int | None:
    thumb_value = _clean_dimension(thumb)
    original_value = _clean_dimension(original)
    if thumb_value is not None and original_value is not None:
        return min(thumb_value, original_value)
    return thumb_value if thumb_value is not None else original_value


def _candidate_from_page(page: object) -> ImageCandidate | None:
    """Normalize one Commons search result, or return None when it is unusable."""
    if not isinstance(page, dict):
        return None

    infos = page.get("imageinfo")
    if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
        return None
    info = infos[0]

    # Prefer the ~1024px thumbnail rendition (small, fast, plenty for a hero
    # image) and fall back to the original upload when there is no thumb.
    original_url = _clean_text(info.get("url"))
    thumbnail_url = _clean_text(info.get("thumburl"))
    url = _strip_tracking_params(thumbnail_url or original_url)
    path = urlsplit(url).path.lower()
    extension = path[path.rfind(".") :] if "." in path else ""
    if extension not in _ALLOWED_EXTENSIONS:
        return None

    # The candidate URL is what will be downloaded; its dimensions are:
    # - the thumbnail rendition when one exists. For files smaller than the
    #   requested thumbnail, Commons serves the original as the thumbnail
    #   while still reporting the requested size, so the smaller of the two
    #   reported sizes is used to keep small files filtered out.
    # - otherwise the original upload's own dimensions.
    if thumbnail_url:
        width = _min_dimension(info.get("thumbwidth"), info.get("width"))
        height = _min_dimension(info.get("thumbheight"), info.get("height"))
    else:
        width = _clean_dimension(info.get("width"))
        height = _clean_dimension(info.get("height"))
    if width is not None and height is not None and min(width, height) < MIN_IMAGE_SIDE_PIXELS:
        return None

    extmetadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}

    def _meta(key: str) -> str:
        entry = extmetadata.get(key)
        return _html_to_summary(entry.get("value")) if isinstance(entry, dict) else ""

    license_name = _meta("LicenseShortName")
    artist = _meta("Artist")
    attribution = f"{artist} ({license_name})" if artist and license_name else artist or license_name

    title = _clean_text(page.get("title"))
    if title.lower().startswith("file:"):
        title = title[len("file:") :]
    # The thumbnail of a PDF is a .pdf.jpg, so also reject candidates whose
    # source file is not a raster image (PDF, SVG, audio, video, ...).
    title_path = title.lower().split("?", 1)[0]
    title_extension = title_path[title_path.rfind(".") :] if "." in title_path else ""
    if title_extension and title_extension not in _ALLOWED_EXTENSIONS:
        return None

    return ImageCandidate(
        url=url,
        source_url=_strip_tracking_params(_clean_text(info.get("descriptionurl"))),
        title=title,
        attribution=attribution,
        license=license_name,
        width=width,
        height=height,
    )


def _read_capped(response, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ImageSearchError("The image search response was too large")
    return body


def search_images(query: str, *, limit: int = SEARCH_RESULT_LIMIT, timeout: float = SEARCH_TIMEOUT_SECONDS) -> list[ImageCandidate]:
    """Search Wikimedia Commons for candidate images for ``query``.

    Returns a non-empty list of candidates or raises :class:`ImageSearchError`.
    """
    query = (query or "").strip()
    if not query:
        raise ImageSearchError("Expected a non-empty search query")

    search_query = _optimize_query(query)

    params = urlencode(
        {
            "action": "query",
            # generator=search does a full-text search; namespace 6 is File:.
            "generator": "search",
            "gsrsearch": search_query,
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": str(THUMBNAIL_WIDTH_PIXELS),
            "format": "json",
        }
    )
    url = f"{COMMONS_API_URL}?{params}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET")
    logger.info(f"Searching for recipe images: {url}")

    try:
        with urlopen(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise ImageSearchError(f"The image search returned HTTP {response.status}")
            body = _read_capped(response, MAX_SEARCH_RESPONSE_BYTES)
    except ImageSearchError:
        raise
    except HTTPError as exc:
        logger.warning(f"Image search returned HTTP {exc.code} for {url}")
        raise ImageSearchError(f"The image search request failed (HTTP {exc.code})") from exc
    except (URLError, OSError, TimeoutError) as exc:
        logger.warning(f"Image search failed for {url}: {exc}")
        raise ImageSearchError(f"Unable to reach the image search service: {exc}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ImageSearchError("The image search returned an invalid response") from exc

    pages = payload.get("query", {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        raise ImageSearchError("The image search returned an invalid response")

    # The API returns an object keyed by pageid; `index` is the search rank.
    ordered = sorted((page for page in pages.values() if isinstance(page, dict)), key=lambda page: page.get("index", 1_000_000))
    candidates = [candidate for page in ordered if (candidate := _candidate_from_page(page)) is not None]
    if not candidates:
        logger.info(f"Image search for {query!r} returned no usable candidates")
        raise ImageSearchError(f"No suitable images were found for {query!r}")

    logger.info(f"Image search for {query!r} returned {len(candidates)} usable candidates")
    return candidates
