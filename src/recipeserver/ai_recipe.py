"""Optional local-model integration for creating recipes from text, URLs, or images.

Also provides "Find One for Me": server-side web search for candidate
images plus all-purpose-model selection of a single suitable image.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urlsplit
from urllib.request import Request, urlopen

import frontmatter
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from ._logger import logger

MODEL_TIMEOUT_SECONDS = 120
AVAILABILITY_TIMEOUT_SECONDS = 3
URL_TIMEOUT_SECONDS = 20
SEARCH_TIMEOUT_SECONDS = 20
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_URL_BYTES = 2 * 1024 * 1024
MAX_MODEL_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PROMPT_INPUT_CHARS = 60_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_IMAGE_BYTES = 10 * 1024 * 1024
# Direct-download formats that map cleanly to a file extension.
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}
DOWNLOADABLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".avif"}
# Thinking/reasoning models (e.g. qwen3) spend part of this budget on
# reasoning before producing the answer, so it needs headroom beyond the
# length of the recipe itself.
MAX_MODEL_TOKENS = 8192
USER_AGENT = "RecipeServer/0.1"

# Vision-capable image formats accepted for "From Image" generation.
# SVG is excluded: it is not a raster image a vision model can transcribe.
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

LIST_FIELDS = ("tags", "cuisine", "categories", "meals")
SOURCE_FIELDS = ("author", "title", "format", "url")

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)


class ModelUnavailable(RuntimeError):
    """The configured model endpoint cannot be reached or is not configured."""


class ModelRequestError(RuntimeError):
    """The model endpoint returned an error or unusable response."""


class SourceFetchError(RuntimeError):
    """Recipe source content could not be fetched."""


class ImageSearchError(RuntimeError):
    """Web image search or model selection produced no usable image."""


class ImageDownloadError(RuntimeError):
    """A selected image could not be downloaded or validated."""


FIND_ONE_FOR_ME_PROMPT_PATH = Path(__file__).resolve().parent / "FindOneForMePrompt.md"


def load_find_one_for_me_prompt() -> str:
    """Load the Find One for Me prompt fresh from its external file."""
    try:
        return FIND_ONE_FOR_ME_PROMPT_PATH.read_text(encoding="UTF-8").strip()
    except OSError:
        logger.exception(f"Failed to read Find One for Me prompt: {FIND_ONE_FOR_ME_PROMPT_PATH}")
        return ""


@dataclass(frozen=True)
class AIConfigView:
    """Typed snapshot of AI-related configuration values."""

    endpoint: str
    all_purpose_model_name: str
    image_analysis_model: str
    new_recipe_prompt: str
    new_recipe_from_image_prompt: str
    find_one_for_me_prompt: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.new_recipe_prompt)

    @property
    def is_image_configured(self) -> bool:
        return bool(self.endpoint and self.new_recipe_from_image_prompt)

    @property
    def is_find_image_configured(self) -> bool:
        return bool(self.endpoint and (self.find_one_for_me_prompt or load_find_one_for_me_prompt()))


def _read_config_text(config: object | None, name: str) -> str:
    return str(getattr(config, name, "") or "").strip()


def _resolve_all_purpose_model_name(config: object | None) -> str:
    configured_name = _read_config_text(config, "all_purpose_model_name")
    if configured_name:
        return configured_name
    # Fall back to the legacy attribute name for older configurations.
    return _read_config_text(config, "model_name")


def resolve_ai_config(config: object | None) -> AIConfigView:
    return AIConfigView(
        endpoint=_read_config_text(config, "model_endpoint"),
        all_purpose_model_name=_resolve_all_purpose_model_name(config),
        image_analysis_model=_read_config_text(config, "image_analysis_model"),
        new_recipe_prompt=_read_config_text(config, "new_recipe_prompt"),
        new_recipe_from_image_prompt=_read_config_text(config, "new_recipe_from_image_prompt"),
        # Configured prompt if present; otherwise fall back to the external
        # FindOneForMePrompt.md file so callers that only carry the endpoint
        # and model still work (and never embed the prompt here).
        find_one_for_me_prompt=_read_config_text(config, "find_one_for_me_prompt")
        or load_find_one_for_me_prompt(),
    )


# Compatibility aliases: retained because these helpers were previously module-level.
def _all_purpose_model_name(config: object | None) -> str:
    return _resolve_all_purpose_model_name(config)


def _image_analysis_model_name(config: object | None) -> str:
    return _read_config_text(config, "image_analysis_model")


def is_configured(config: object | None) -> bool:
    return resolve_ai_config(config).is_configured


def is_image_configured(config: object | None) -> bool:
    return resolve_ai_config(config).is_image_configured


def is_find_image_configured(config: object | None) -> bool:
    return resolve_ai_config(config).is_find_image_configured


def ai_status(config: object | None) -> dict[str, Any]:
    resolved = resolve_ai_config(config)
    status: dict[str, Any] = {
        "configured": resolved.is_configured,
        "available": False,
        "model": resolved.all_purpose_model_name,
        "all_purpose_model": resolved.all_purpose_model_name,
        "image_model": resolved.image_analysis_model,
        "image_configured": resolved.is_image_configured,
        "image_available": False,
        "find_image_configured": resolved.is_find_image_configured,
        "find_image_available": False,
    }
    logger.debug(
        f"Checking local model status: configured={resolved.is_configured}, "
        f"image_configured={resolved.is_image_configured}, "
        f"find_image_configured={resolved.is_find_image_configured}, "
        f"endpoint={resolved.endpoint or '(none)'}, "
        f"model={resolved.all_purpose_model_name or '(auto)'}, "
        f"image_model={resolved.image_analysis_model or '(auto)'}"
    )

    if not resolved.is_configured and not resolved.is_image_configured and not resolved.is_find_image_configured:
        logger.info("AI recipe creation is not configured")
        return status

    available = is_available(resolved.endpoint)
    logger.info(
        f"Local model status: configured={resolved.is_configured}, available={available}, endpoint={resolved.endpoint}"
    )
    status["available"] = available
    status["image_available"] = bool(available and resolved.is_image_configured)
    status["find_image_available"] = bool(available and resolved.is_find_image_configured)
    return status


def normalize_chat_completions_url(endpoint: str) -> str:
    endpoint = (endpoint or "").strip()
    if not endpoint:
        raise ValueError("Model endpoint is not configured")

    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Model endpoint must be an http or https URL")

    endpoint = endpoint.rstrip("/")
    path = parsed.path.rstrip("/")

    if path.endswith("/chat/completions") or path.endswith("/api/chat"):
        return endpoint
    if not path:
        return f"{endpoint}/v1/chat/completions"
    return f"{endpoint}/chat/completions"


def normalize_models_url(endpoint: str) -> str:
    chat_url = normalize_chat_completions_url(endpoint)
    path = urlsplit(chat_url).path.rstrip("/")

    if path.endswith("/api/chat"):
        return chat_url.removesuffix("/api/chat") + "/api/tags"

    return chat_url.removesuffix("/chat/completions") + "/models"


def _read_response(response, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > limit:
            raise ModelRequestError("Model response is too large")

    body = response.read(limit + 1)
    if len(body) > limit:
        raise ModelRequestError("Model response is too large")
    return body


def _model_names_from_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []

    entries = payload.get("data")
    if not isinstance(entries, list):
        entries = payload.get("models")

    names: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("id") or entry.get("name") or entry.get("model")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())

    return names


def list_models(endpoint: str, timeout: float = AVAILABILITY_TIMEOUT_SECONDS) -> list[str]:
    models_url = normalize_models_url(endpoint)
    logger.debug(f"Listing models from {models_url}")
    request = Request(
        models_url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )

    with urlopen(request, timeout=timeout) as response:
        if not 200 <= response.status < 300:
            logger.warning(f"Model list request to {models_url} returned HTTP {response.status}")
            return []
        payload = json.loads(_read_response(response, MAX_MODEL_RESPONSE_BYTES))

    names = _model_names_from_payload(payload)
    logger.debug(f"Models reported by {models_url}: {names}")
    return names


def resolve_model_name(endpoint: str, configured_name: str = "") -> str:
    configured_name = configured_name.strip()
    if configured_name:
        logger.debug(f"Using configured model name: {configured_name}")
        return configured_name

    try:
        models = list_models(endpoint)
    except (HTTPError, URLError, OSError, ValueError, ModelRequestError, json.JSONDecodeError) as exc:
        logger.warning(f"Could not auto-detect a model name from {endpoint}: {exc}")
        return ""

    if not models:
        logger.warning(f"The model endpoint {endpoint} did not report any models")
        return ""

    logger.info(f"Auto-selected local model: {models[0]}")
    return models[0]


def is_available(endpoint: str, timeout: float = AVAILABILITY_TIMEOUT_SECONDS) -> bool:
    try:
        list_models(endpoint, timeout=timeout)
    except HTTPError as exc:
        # Some compatible servers do not expose /models but still accept chat requests.
        if exc.code in {404, 405}:
            logger.debug(
                f"{endpoint} does not expose a model list (HTTP {exc.code}); " "assuming chat requests are supported"
            )
            return True
        logger.warning(f"Model endpoint {endpoint} returned HTTP {exc.code}")
        return False
    except (URLError, OSError, ValueError, ModelRequestError, json.JSONDecodeError) as exc:
        logger.warning(f"Model endpoint {endpoint} is unavailable: {exc}")
        return False
    return True


def _html_looks_like_markup(text: str) -> bool:
    beginning = text.lstrip()[:1000].lower()
    return beginning.startswith("<!doctype html") or "<html" in beginning or "<body" in beginning


def _extract_url_text(body: bytes, content_type: str, charset: str, url: str) -> tuple[str, str]:
    try:
        text = body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")

    fallback_title = urlsplit(url).netloc

    if "html" not in content_type.lower() and not _html_looks_like_markup(text):
        return fallback_title, text.strip()

    soup = BeautifulSoup(text, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        element.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return title or fallback_title, main.get_text("\n", strip=True)


def fetch_url_content(url: str) -> tuple[str, str]:
    """Return a title and readable text for a recipe URL."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must start with http:// or https://")

    request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    logger.info(f"Fetching recipe source from {url}")

    try:
        with urlopen(request, timeout=URL_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_URL_BYTES + 1)
    except (HTTPError, URLError, OSError) as exc:
        logger.warning(f"Unable to fetch recipe URL {url}: {exc}")
        raise SourceFetchError(f"Unable to fetch URL: {exc}") from exc

    if len(body) > MAX_URL_BYTES:
        logger.warning(f"Recipe URL content from {url} exceeds {MAX_URL_BYTES} bytes")
        raise SourceFetchError("The URL content is too large to send to the model")

    title, text = _extract_url_text(body, content_type, charset, url)
    logger.debug(f"Extracted {len(text)} characters of text from {url} (title={title!r})")
    return title, text


def _build_user_message(input_type: str, input_value: str) -> tuple[str, str]:
    title = ""

    if input_type == "url":
        title, text = fetch_url_content(input_value)
        prompt_text = f"Recipe URL: {input_value}\n" f"Page title: {title}\n\n" f"Recipe content:\n{text}"
    elif input_type == "text":
        prompt_text = f"Recipe text:\n{input_value}"
    else:
        raise ValueError("inputType must be 'url', 'text', or 'image'")

    if len(prompt_text) > MAX_PROMPT_INPUT_CHARS:
        prompt_text = prompt_text[:MAX_PROMPT_INPUT_CHARS] + "\n\n[The source was truncated because it was very long.]"

    return prompt_text, title


def image_data_uri(image_filename: str, image_bytes: bytes) -> str:
    """Validate an uploaded recipe image and return it as a data URI."""
    if not image_bytes:
        raise ValueError("Expected a recipe image")

    suffix = "." + image_filename.rsplit(".", 1)[-1].lower() if "." in image_filename else ""
    mime_type = IMAGE_MIME_TYPES.get(suffix) or mimetypes.guess_type(image_filename)[0]
    if suffix not in IMAGE_MIME_TYPES or mime_type not in IMAGE_MIME_TYPES.values():
        raise ValueError("Unsupported image type for AI generation. " "Use a JPG, PNG, GIF, WebP, BMP, or TIFF image.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("The recipe image is too large to send to the model")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Invalid image file") from exc

    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _content_text(content: object) -> str:
    """Flatten a chat message content value (string or list of parts)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text") or part.get("content")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _extract_reasoning_text(message: dict[str, Any]) -> str:
    return _content_text(message.get("reasoning_content") or message.get("reasoning"))


def _extract_choice_content(choice: object) -> tuple[str, str, Any]:
    if not isinstance(choice, dict):
        return "", "", None

    message = choice.get("message")
    content = ""
    reasoning = ""
    if isinstance(message, dict):
        content = _content_text(message.get("content"))
        reasoning = _extract_reasoning_text(message)

    if not content:
        content = _content_text(choice.get("text"))
    if not reasoning:
        reasoning = _content_text(choice.get("reasoning_content") or choice.get("reasoning"))

    return content, reasoning, choice.get("finish_reason")


def _extract_payload_fallback_content(payload: dict[str, Any]) -> tuple[str, str]:
    message = payload.get("message")
    if not isinstance(message, dict):
        return "", ""
    return _content_text(message.get("content")), _extract_reasoning_text(message)


THINKING_BLOCK_PATTERN = re.compile(
    r"<think\b[^>]*>.*?</think\s*>",
    re.IGNORECASE | re.DOTALL,
)

THINKING_START_PATTERN = re.compile(
    r"<think\b[^>]*>.*$",
    re.IGNORECASE | re.DOTALL,
)

THINKING_END_PATTERN = re.compile(
    r"</think\s*>",
    re.IGNORECASE,
)


def _strip_thinking_content(content: str) -> str:
    """Remove embedded model reasoning from response content."""
    content = THINKING_BLOCK_PATTERN.sub("", content)

    # Handle an unmatched closing tag by discarding preceding reasoning.
    closing_match = THINKING_END_PATTERN.search(content)
    if closing_match:
        content = content[closing_match.end() :]

    # Discard an incomplete trailing thinking block.
    content = THINKING_START_PATTERN.sub("", content)

    return content.strip()


def _extract_chat_content(payload: object) -> tuple[str, dict[str, Any]]:
    """Extract answer text plus diagnostics from a chat completion payload.

    Thinking models may return reasoning in separate ``reasoning_content``/
    ``reasoning`` fields or embed it directly in ``content``. Reasoning is
    diagnostics only and is never used as the answer.
    """
    diagnostics: dict[str, Any] = {
        "finish_reason": None,
        "usage": None,
        "content_chars": 0,
        "reasoning_chars": 0,
        "response_keys": sorted(payload) if isinstance(payload, dict) else [],
    }
    content = ""
    reasoning = ""

    if isinstance(payload, dict):
        diagnostics["usage"] = payload.get("usage")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            content, reasoning, diagnostics["finish_reason"] = _extract_choice_content(choices[0])

        if not content:
            fallback_content, fallback_reasoning = _extract_payload_fallback_content(payload)
            content = fallback_content or content
            reasoning = reasoning or fallback_reasoning

    original_content = content
    content = _strip_thinking_content(content)

    if content != original_content:
        diagnostics["embedded_reasoning_stripped"] = True
        logger.debug("Stripped embedded thinking content from model response")

    diagnostics["content_chars"] = len(content)
    diagnostics["reasoning_chars"] = len(reasoning)
    diagnostics["reasoning_preview"] = reasoning[:2000]
    diagnostics["content_preview"] = content[:2000]
    return content, diagnostics


def _chat(
    endpoint: str,
    model_name: str,
    prompt: str,
    user_message: str | list[dict[str, Any]],
    stage: str = "recipe generation",
) -> str:
    chat_url = normalize_chat_completions_url(endpoint)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": MAX_MODEL_TOKENS,
        "reasoning_effort": "none",  # TODO: Expose this in configuration. It is also an ollama specific setting so that will need handled if other providers are used
        "stream": False,
    }
    user_chars = len(user_message) if isinstance(user_message, str) else len(json.dumps(user_message))
    logger.info(
        f"Sending {stage} request to {chat_url} (model={model_name}, "
        f"system_prompt_chars={len(prompt)}, user_chars={user_chars})"
    )
    request = Request(
        chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=MODEL_TIMEOUT_SECONDS) as response:
            logger.debug(f"Model request to {chat_url} returned HTTP {response.status}")
            body = _read_response(response, MAX_MODEL_RESPONSE_BYTES)
            logger.debug(f"Received {len(body)} bytes from the model")
    except HTTPError as exc:
        details = exc.read(2000).decode("utf-8", errors="replace").strip()
        message = f"Model request failed (HTTP {exc.code})"
        if details:
            message = f"{message}: {details}"
        logger.error(f"{message} ({chat_url})")
        raise ModelRequestError(message) from exc
    except (URLError, OSError) as exc:
        logger.error(f"Could not reach the model endpoint {chat_url}: {exc}")
        raise ModelUnavailable(f"Could not reach the model endpoint: {exc}") from exc

    try:
        response_payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ModelRequestError("The model returned invalid JSON") from exc

    content, diagnostics = _extract_chat_content(response_payload)
    logger.info(
        f"{stage} response from {model_name}: {len(body)} bytes, "
        f"finish_reason={diagnostics['finish_reason']!r}, "
        f"usage={diagnostics['usage']!r}, "
        f"content_chars={diagnostics['content_chars']}, "
        f"reasoning_chars={diagnostics['reasoning_chars']}, "
        f"response_keys={diagnostics['response_keys']}"
    )
    logger.debug(f"{stage} content preview: {diagnostics['content_preview']!r}")
    if diagnostics["reasoning_chars"]:
        logger.debug(f"{stage} reasoning preview: {diagnostics['reasoning_preview']!r}")

    if not content.strip():
        if diagnostics["finish_reason"] == "length":
            raise ModelRequestError(
                f"The {stage} model ({model_name}) stopped before producing "
                "an answer because it reached the token limit; it returned "
                "only reasoning/thinking text. Try again, or use a "
                "non-thinking model for the all-purpose model."
            )
        if diagnostics["reasoning_chars"]:
            raise ModelRequestError(
                f"The {stage} model ({model_name}) returned only "
                "reasoning/thinking text and no answer "
                f"(finish_reason={diagnostics['finish_reason']!r}). "
                "Try again, or use a non-thinking model."
            )
        raise ModelRequestError(
            f"The {stage} model ({model_name}) returned an empty response "
            f"(finish_reason={diagnostics['finish_reason']!r}, "
            f"usage={diagnostics['usage']!r})"
        )

    return content


def _normalize_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}

    normalized = dict(metadata)

    legacy_category = normalized.pop("category", None)
    if normalized.get("categories") is None and legacy_category is not None:
        normalized["categories"] = legacy_category

    for field in LIST_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = [item.strip() for item in value.split(",") if item.strip()]

    # Status is a single string value; collapse any list to its first item.
    status = normalized.get("status")
    if isinstance(status, list):
        normalized["status"] = next((item.strip() for item in status if isinstance(item, str) and item.strip()), None)
    elif status is not None and not isinstance(status, str):
        normalized["status"] = None
    elif isinstance(status, str):
        normalized["status"] = status.strip() or None

    source = normalized.get("source")
    if isinstance(source, list):
        source = next((item for item in source if isinstance(item, dict)), None)
    if not isinstance(source, dict):
        source = None
    if source is not None:
        normalized["source"] = {
            field: (source.get(field).strip() or None if isinstance(source.get(field), str) else None)
            for field in SOURCE_FIELDS
        }

        source_format = normalized["source"].get("format")
        if isinstance(source_format, str):
            normalized["source"]["format"] = {
                "website": "Website",
                "ai": "AI",
                "book": "Book",
                "other": "Other",
            }.get(source_format.casefold(), source_format)

    return normalized


def _source_for_input(
    input_type: str,
    model_name: str,
    url: str = "",
    title: str = "",
) -> dict[str, str | None]:
    if input_type == "url":
        return {
            "author": None,
            "title": title or urlsplit(url).netloc,
            "format": "Website",
            "url": url,
        }

    return {
        "author": None,
        "title": model_name or "Local model",
        "format": "AI",
        "url": None,
    }


def parse_model_output(output: str) -> tuple[str, dict[str, Any]]:
    text = output.strip()
    fence = _CODE_FENCE_RE.match(text)
    if fence:
        text = fence.group("body").strip()

    try:
        post = frontmatter.loads(text)
        metadata = _normalize_metadata(post.metadata)
        content = post.content.strip()
    except Exception:
        logger.exception("Failed to parse model front matter; using the raw output")
        metadata = {}
        content = text

    return content, metadata


def _truncate_prompt_text(prompt_text: str) -> str:
    if len(prompt_text) <= MAX_PROMPT_INPUT_CHARS:
        return prompt_text
    return prompt_text[:MAX_PROMPT_INPUT_CHARS] + "\n\n[The source was truncated because it was very long.]"


def _require_model_name(endpoint: str, configured_name: str, missing_message: str) -> str:
    model_name = resolve_model_name(endpoint, configured_name)
    if not model_name:
        raise ModelUnavailable(missing_message)
    return model_name


def _report_progress(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _prepare_image_draft_input(
    resolved: AIConfigView,
    all_purpose_model_name: str,
    image_model_name: str,
    image_bytes: bytes | None,
    image_filename: str,
    progress_callback: Callable[[str], None] | None,
) -> tuple[str, str]:
    # Stage 1 (vision): transcribe the image. Stage 2 (all-purpose): draft recipe.
    _report_progress(progress_callback, f"Sending the image to {image_model_name} for transcription...")
    data_uri = image_data_uri(image_filename, image_bytes or b"")
    image_user_content: list[dict[str, Any]] = [
        {"type": "text", "text": "Recipe image:"},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    logger.info(
        f"Transcribing recipe image with local model '{image_model_name}' "
        f"({len(image_bytes or b'')} bytes, {image_filename})"
    )
    transcription = _chat(
        resolved.endpoint,
        image_model_name,
        resolved.new_recipe_from_image_prompt,
        image_user_content,
        stage="image transcription",
    )
    logger.info(
        f"Image transcription from '{image_model_name}' ({len(transcription)} characters): {transcription[:2000]!r}"
    )
    _report_progress(
        progress_callback,
        f"Image transcribed. Sending the extracted text to {all_purpose_model_name}...",
    )
    return _truncate_prompt_text(f"Recipe text (transcribed from image):\n{transcription}"), ""


def _prepare_text_or_url_draft_input(
    input_type: str,
    input_value: str,
    all_purpose_model_name: str,
    progress_callback: Callable[[str], None] | None,
) -> tuple[str, str]:
    user_message, title = _build_user_message(input_type, input_value)
    if input_type == "url":
        _report_progress(
            progress_callback,
            f"Page fetched. Sending the source URL and extracted text to {all_purpose_model_name}...",
        )
    else:
        _report_progress(progress_callback, f"Sending the recipe text to {all_purpose_model_name}...")
    return user_message, title


def _apply_default_source(
    metadata: dict[str, Any],
    input_type: str,
    model_name: str,
    input_value: str,
    title: str,
) -> None:
    default_source = _source_for_input(
        input_type,
        model_name,
        url=input_value if input_type == "url" else "",
        title=title,
    )
    source = metadata.get("source")
    if not isinstance(source, dict):
        metadata["source"] = default_source
        return
    for field, value in default_source.items():
        if not source.get(field):
            source[field] = value


def generate_recipe(
    config: object,
    input_type: str,
    input_value: str,
    progress_callback: Callable[[str], None] | None = None,
    image_bytes: bytes | None = None,
    image_filename: str = "",
) -> dict[str, Any]:
    resolved = resolve_ai_config(config)
    if not resolved.is_configured:
        raise ModelUnavailable("The local model is not configured")
    if input_type == "image" and not resolved.is_image_configured:
        raise ModelUnavailable("The image analysis model is not configured")

    _report_progress(progress_callback, "Checking the configured AI model...")
    all_purpose_model_name = _require_model_name(
        resolved.endpoint,
        resolved.all_purpose_model_name,
        "Could not determine a model name. Configure all_purpose_model_name in recipe-server-cfg.toml.",
    )

    image_model_name = ""
    if input_type == "image":
        image_model_name = _require_model_name(
            resolved.endpoint,
            resolved.image_analysis_model,
            "Could not determine an image analysis model name. Configure image_analysis_model in recipe-server-cfg.toml.",
        )

    # Report the input-specific preparation step before doing any expensive work.
    if input_type == "url":
        _report_progress(progress_callback, f"Fetching recipe page: {input_value}")
    elif input_type == "image":
        _report_progress(progress_callback, "Preparing the recipe image...")
    else:
        _report_progress(progress_callback, "Preparing the recipe text...")

    if input_type == "image":
        user_message, title = _prepare_image_draft_input(
            resolved,
            all_purpose_model_name,
            image_model_name,
            image_bytes,
            image_filename,
            progress_callback,
        )
    else:
        user_message, title = _prepare_text_or_url_draft_input(
            input_type,
            input_value,
            all_purpose_model_name,
            progress_callback,
        )

    logger.info(
        f"Generating recipe from {input_type} input with local model '{all_purpose_model_name}' "
        f"({len(user_message)} characters of source content)"
    )
    _report_progress(progress_callback, f"Generating recipe with {all_purpose_model_name}...")
    output = _chat(
        resolved.endpoint,
        all_purpose_model_name,
        resolved.new_recipe_prompt,
        user_message,
        stage="recipe drafting" if input_type == "image" else "recipe generation",
    )
    _report_progress(progress_callback, "AI response received. Preparing the recipe draft...")

    content, metadata = parse_model_output(output)
    logger.info(
        f"Model returned {len(output)} characters; parsed {len(content)} characters of Markdown "
        f"and metadata fields {sorted(metadata)}"
    )
    _apply_default_source(metadata, input_type, all_purpose_model_name, input_value, title)
    return {"content": content, "metadata": metadata}


# ---------------------------------------------------------------------------
# "Find One for Me" - web image search + all-purpose model selection
# ---------------------------------------------------------------------------
# The local model cannot browse the internet on its own, so the server does
# the actual web search and hands the model real candidate results. The model
# may only return one of those URLs, which prevents fabricated image URLs.


def substitute_search_query(prompt: str, search_query: str) -> str:
    """Replace the prompt's search-query placeholder with the user's query.

    Both the current ``{{search_query}}`` placeholder and the earlier
    ``{{recipe_title}}`` spelling (older prompt files) are substituted.
    """
    query = (search_query or "").strip()
    result = prompt.replace("{{search_query}}", query).replace("{search_query}", query)
    return result.replace("{{recipe_title}}", query).replace("{recipe_title}", query)


# Compatibility alias for callers that still spell it in terms of the title.
def substitute_recipe_title(prompt: str, recipe_title: str) -> str:
    return substitute_search_query(prompt, recipe_title)


def _is_valid_image_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    parsed = urlsplit(url.strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _clean_url(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _valid_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only candidates with a real image URL; drop fabricated/malformed rows."""
    valid: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        image_url = _clean_url(candidate.get("image_url"))
        if not _is_valid_image_url(image_url):
            continue
        valid.append(
            {
                "image_url": image_url,
                "source_url": _clean_url(candidate.get("source_url")) or None,
                "description": _clean_url(candidate.get("description")) or None,
                "attribution": _clean_url(candidate.get("attribution")) or None,
            }
        )
    return valid


def _fetch_json_url(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET")
    logger.info(f"Searching for candidate images: {url}")
    try:
        with urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
            body = _read_response(response, MAX_MODEL_RESPONSE_BYTES)
    except (HTTPError, URLError, OSError) as exc:
        raise ImageSearchError(f"Image search failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ImageSearchError("Image search returned invalid JSON") from exc


def _openverse_candidates(query: str, limit: int) -> list[dict[str, Any]]:
    # Openverse needs no API key for low-volume use and returns direct
    # image URLs together with the landing page (source) and creator.
    search_url = (
        f"https://api.openverse.org/v1/images/?q={quote_plus(query)}"
        f"&page_size={limit}&license_type=all"
    )
    payload = _fetch_json_url(search_url)
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    candidates = []
    for result in results:
        if not isinstance(result, dict):
            continue
        candidates.append(
            {
                "image_url": _clean_url(result.get("url")),
                "source_url": _clean_url(result.get("foreign_landing_url")),
                "description": _clean_url(result.get("title")),
                "attribution": _clean_url(result.get("creator")),
            }
        )
    return candidates


def _wikimedia_candidates(query: str, limit: int) -> list[dict[str, Any]]:
    search_url = (
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        f"&generator=search&gsrsearch=filetype:bitmap%20{quote_plus(query)}"
        f"&gsrnamespace=6&gsrlimit={limit}&prop=imageinfo&iiprop=url|extmetadata"
    )
    payload = _fetch_json_url(search_url)
    if not isinstance(payload, dict):
        return []
    pages = (payload.get("query") or {}).get("pages")
    if not isinstance(pages, dict):
        return []
    candidates = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        info_list = page.get("imageinfo")
        if not isinstance(info_list, list) or not info_list:
            continue
        info = info_list[0] if isinstance(info_list[0], dict) else {}
        metadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}

        def meta_value(key: str) -> str:
            entry = metadata.get(key) if isinstance(metadata.get(key), dict) else {}
            value = entry.get("value")
            return value.strip() if isinstance(value, str) else ""

        candidates.append(
            {
                "image_url": _clean_url(info.get("thumburl") or info.get("url")),
                "source_url": _clean_url(info.get("descriptionurl")),
                "description": meta_value("ImageDescription") or _clean_url(page.get("title")),
                "attribution": meta_value("Artist") or meta_value("Credit"),
            }
        )
    return candidates


def search_image_candidates(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Search the web for candidate images for ``query``.

    Tries Openverse first, then Wikimedia Commons. Only entries backed by a
    real ``http(s)`` image URL are returned; the model never invents them.
    Mock this function in tests rather than hitting the network.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        raise ImageSearchError("Type a search query before searching for an image")
    query_limit = max(1, min(int(limit), 20))
    errors: list[str] = []
    for search in (_openverse_candidates, _wikimedia_candidates):
        try:
            candidates = _valid_candidates(search(cleaned_query, query_limit))
        except ImageSearchError as exc:
            errors.append(str(exc))
            logger.warning(f"Image search provider failed: {exc}")
            continue
        if candidates:
            logger.info(f"Found {len(candidates)} candidate images for {cleaned_query!r}")
            return candidates
    if errors:
        raise ImageSearchError(f"No suitable image found for {cleaned_query!r}: {'; '.join(errors)}")
    raise ImageSearchError(f"No suitable image found for {cleaned_query!r}")


def parse_find_one_for_me_output(output: str) -> dict[str, Any] | None:
    """Parse the model's answer; ``None`` when it reports no suitable image."""
    text = (output or "").strip()
    generic_fence = re.match(r"^\s*```[a-zA-Z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", text, re.DOTALL)
    fence = _CODE_FENCE_RE.match(text)
    if fence:
        text = fence.group("body").strip()
    elif generic_fence:
        text = generic_fence.group("body").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImageSearchError("The model did not return a valid image selection") from exc
    if not isinstance(parsed, dict):
        raise ImageSearchError("The model did not return a valid image selection")
    image_url = _clean_url(parsed.get("image_url"))
    if not image_url:
        return None
    if not _is_valid_image_url(image_url):
        raise ImageSearchError("The model returned an invalid image URL")
    return {
        "image_url": image_url,
        "source_url": _clean_url(parsed.get("source_url")) or None,
        "description": _clean_url(parsed.get("description")) or None,
        "attribution": _clean_url(parsed.get("attribution")) or None,
    }


def _filename_for_download(image_url: str, content_type: str) -> tuple[str, str]:
    parsed = urlsplit(image_url)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    mime_type = (content_type or "").split(";")[0].strip().lower()
    if suffix not in DOWNLOADABLE_EXTENSIONS:
        suffix = CONTENT_TYPE_EXTENSIONS.get(mime_type, ".jpg")
    guessed = mimetypes.guess_type(f"image{suffix}")[0] or mime_type or "image/jpeg"
    base = Path(unquote(parsed.path)).stem
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-._") or "found-image"
    return f"{base}{suffix}", guessed


def download_image(image_url: str) -> dict[str, Any]:
    """Download and validate a selected image, returning a data-URI payload."""
    if not _is_valid_image_url(image_url):
        raise ImageDownloadError("The selected image URL is not valid")
    request = Request(image_url.strip(), headers={"User-Agent": USER_AGENT, "Accept": "image/*"}, method="GET")
    logger.info(f"Downloading selected image: {image_url}")
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            content_type = ""
            try:
                content_type = response.headers.get_content_type()
            except AttributeError:
                content_type = response.headers.get("Content-Type", "") or ""
            body = response.read(MAX_DOWNLOAD_IMAGE_BYTES + 1)
    except (HTTPError, URLError, OSError) as exc:
        raise ImageDownloadError(f"Failed to download the selected image: {exc}") from exc

    if not body:
        raise ImageDownloadError("The selected image is empty")
    if len(body) > MAX_DOWNLOAD_IMAGE_BYTES:
        raise ImageDownloadError("The selected image is too large to download")

    filename, mime_type = _filename_for_download(image_url.strip(), content_type)
    try:
        with Image.open(BytesIO(body)) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        if not filename.lower().endswith(".svg"):
            raise ImageDownloadError("The selected image could not be validated") from exc
        if b"<svg" not in body[:2000].lower():
            raise ImageDownloadError("The selected image could not be validated") from exc

    data_uri = f"data:{mime_type};base64,{base64.b64encode(body).decode('ascii')}"
    return {
        "filename": filename,
        "content_type": mime_type,
        "data_uri": data_uri,
        "byte_count": len(body),
    }


def find_image_for_recipe(
    config: object,
    search_query: str,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Find one suitable image for a user-typed search query.

    Searches the web for real candidates for the query, lets the configured
    all-purpose model randomly choose among them, then downloads the winner
    so the UI stores it locally instead of hotlinking. Every call performs a
    fresh search, so repeated calls can return different images.
    """
    query = (search_query or "").strip()
    if not query:
        raise ImageSearchError("Type a search query before searching for an image")

    resolved = resolve_ai_config(config)
    if not resolved.endpoint:
        raise ModelUnavailable("The local model is not configured")
    prompt_template = resolved.find_one_for_me_prompt
    if not prompt_template:
        raise ModelUnavailable("The Find One for Me prompt is not configured")

    model_name = _require_model_name(
        resolved.endpoint,
        resolved.all_purpose_model_name,
        "Could not determine a model name. Configure all_purpose_model_name in recipe-server-cfg.toml.",
    )

    _report_progress(progress_callback, "Searching the web for candidate images...")
    candidates = search_image_candidates(query)
    if not candidates:
        raise ImageSearchError(f"No suitable image found for {query!r}")

    # Shuffle so the model does not always favour the first candidate, and
    # so each click performs a fresh, randomised selection.
    shuffled = list(candidates)
    random.shuffle(shuffled)

    prompt = substitute_search_query(prompt_template, query)
    candidate_lines = json.dumps(shuffled, indent=2, ensure_ascii=False)
    user_message = (
        f"Search query: {query}\n\n"
        "Search results (real candidate images returned by a web search; "
        "choose exactly one of these image_url values, randomly among the "
        f"suitable ones):\n{candidate_lines}\n\n"
        "Return the JSON object described in your instructions for your chosen candidate. "
        "Do not return any URL that is not listed above."
    )

    logger.info(f"Selecting a candidate image for {query!r} with '{model_name}' ({len(shuffled)} candidates)")
    _report_progress(progress_callback, f"Asking {model_name} to choose an image...")
    output = _chat(resolved.endpoint, model_name, prompt, user_message, stage="image selection")
    selection = parse_find_one_for_me_output(output)
    if selection is None:
        raise ImageSearchError(f"No suitable image found for {query!r}")

    # Only accept URLs that actually came from the web search.
    chosen = next((c for c in shuffled if c["image_url"] == selection["image_url"]), None)
    if chosen is None:
        raise ImageSearchError("The model returned an image that was not in the search results")

    _report_progress(progress_callback, "Downloading the selected image...")
    downloaded = download_image(chosen["image_url"])
    if not downloaded.get("data_uri"):
        raise ImageDownloadError("The selected image could not be downloaded")

    return {
        "image_url": chosen["image_url"],
        "source_url": chosen.get("source_url") or selection.get("source_url"),
        "description": chosen.get("description") or selection.get("description"),
        "attribution": chosen.get("attribution") or selection.get("attribution"),
        "filename": downloaded["filename"],
        "content_type": downloaded["content_type"],
        "data_uri": downloaded["data_uri"],
        "byte_count": downloaded["byte_count"],
    }
