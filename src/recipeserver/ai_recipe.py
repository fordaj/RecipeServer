"""Optional local-model integration for creating recipes from text, URLs, or images."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import frontmatter
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from ._logger import logger

MODEL_TIMEOUT_SECONDS = 120
AVAILABILITY_TIMEOUT_SECONDS = 3
URL_TIMEOUT_SECONDS = 20
MAX_URL_BYTES = 2 * 1024 * 1024
MAX_MODEL_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PROMPT_INPUT_CHARS = 60_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# Thinking/reasoning models (e.g. qwen3) spend part of this budget on
# reasoning before producing the answer, so it needs headroom beyond the
# length of the recipe itself.
MAX_MODEL_TOKENS = 8192
USER_AGENT = "RecipeServer/0.1"

# Ollama exposes the chat stream, the loaded-model list, and the installed-model
# list under these paths. The endpoint configured by the user may still include
# an OpenAI-compatible suffix such as ``/v1``; ``normalize_ollama_base_url``
# removes it so every request reaches the Ollama server itself.
OLLAMA_CHAT_PATH = "/api/chat"
OLLAMA_PS_PATH = "/api/ps"
OLLAMA_TAGS_PATH = "/api/tags"

# Normalized generation states shared by the backend and the browser UI.
STATUS_CHECKING_MODEL = "checking_model"
STATUS_LOADING_MODEL = "loading_model"
STATUS_PREPARING = "preparing"
STATUS_THINKING = "thinking"
STATUS_GENERATING = "generating"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"

# Vision-capable image formats accepted for "From Images" generation.
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


@dataclass(frozen=True)
class AIConfigView:
    """Typed snapshot of AI-related configuration values."""

    endpoint: str
    all_purpose_model_name: str
    image_analysis_model: str
    new_recipe_prompt: str
    new_recipe_from_image_prompt: str

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.new_recipe_prompt)

    @property
    def is_image_configured(self) -> bool:
        return bool(self.endpoint and self.new_recipe_from_image_prompt)


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
    )


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
    }
    logger.debug(
        f"Checking local model status: configured={resolved.is_configured}, "
        f"image_configured={resolved.is_image_configured}, endpoint={resolved.endpoint or '(none)'}, "
        f"model={resolved.all_purpose_model_name or '(auto)'}, "
        f"image_model={resolved.image_analysis_model or '(auto)'}"
    )

    if not resolved.is_configured and not resolved.is_image_configured:
        logger.info("AI recipe creation is not configured")
        return status

    available = is_available(resolved.endpoint)
    logger.info(f"Local model status: configured={resolved.is_configured}, available={available}, endpoint={resolved.endpoint}")
    status["available"] = available
    status["image_available"] = bool(available and resolved.is_image_configured)
    return status


# Endpoint suffixes that point at a specific Ollama (or OpenAI-compatible)
# route. Stripping them leaves the base URL of the Ollama server.
_OLLAMA_ENDPOINT_SUFFIXES = (
    "/v1/chat/completions",
    "/chat/completions",
    "/api/chat",
    "/api/ps",
    "/api/tags",
    "/v1",
    "/api",
)


def normalize_ollama_base_url(endpoint: str) -> str:
    """Return the Ollama server base URL for a configured endpoint.

    RecipeServer targets Ollama exclusively. Accepting the ``/v1`` shape keeps
    existing configurations (and the documented ``.../v1`` example) working
    while every request is sent to Ollama's native API.
    """
    endpoint = (endpoint or "").strip()
    if not endpoint:
        raise ValueError("Model endpoint is not configured")

    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Model endpoint must be an http or https URL")

    base = endpoint.rstrip("/")
    path = parsed.path.rstrip("/")

    for suffix in _OLLAMA_ENDPOINT_SUFFIXES:
        if path.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break

    return base


def ollama_chat_url(endpoint: str) -> str:
    return f"{normalize_ollama_base_url(endpoint)}{OLLAMA_CHAT_PATH}"


def ollama_ps_url(endpoint: str) -> str:
    return f"{normalize_ollama_base_url(endpoint)}{OLLAMA_PS_PATH}"


def ollama_tags_url(endpoint: str) -> str:
    return f"{normalize_ollama_base_url(endpoint)}{OLLAMA_TAGS_PATH}"


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
    models_url = ollama_tags_url(endpoint)
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
            logger.debug(f"{endpoint} does not expose a model list (HTTP {exc.code}); " "assuming chat requests are supported")
            return True
        logger.warning(f"Model endpoint {endpoint} returned HTTP {exc.code}")
        return False
    except (URLError, OSError, ValueError, ModelRequestError, json.JSONDecodeError) as exc:
        logger.warning(f"Model endpoint {endpoint} is unavailable: {exc}")
        return False
    return True


def loaded_model_names(endpoint: str, timeout: float = AVAILABILITY_TIMEOUT_SECONDS) -> list[str]:
    """Return the names of the models Ollama currently has loaded in memory."""
    ps_url = ollama_ps_url(endpoint)
    logger.debug(f"Checking loaded models at {ps_url}")
    request = Request(
        ps_url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )

    with urlopen(request, timeout=timeout) as response:
        if not 200 <= response.status < 300:
            logger.debug(f"Loaded-model request to {ps_url} returned HTTP {response.status}")
            return []
        payload = json.loads(_read_response(response, MAX_MODEL_RESPONSE_BYTES))

    entries = payload.get("models") if isinstance(payload, dict) else None
    names: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("model")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())

    logger.debug(f"Models loaded at {ps_url}: {names}")
    return names


def _model_names_match(left: str, right: str) -> bool:
    """Compare Ollama model names, treating ``:latest`` as implicit."""
    left = left.strip().casefold()
    right = right.strip().casefold()
    if not left or not right:
        return False
    if left == right:
        return True
    return left.removesuffix(":latest") == right.removesuffix(":latest")


def is_model_loaded(endpoint: str, model_name: str, timeout: float = AVAILABILITY_TIMEOUT_SECONDS) -> bool | None:
    """Whether ``model_name`` is loaded, or ``None`` when the status is unknown."""
    try:
        names = loaded_model_names(endpoint, timeout=timeout)
    except (HTTPError, URLError, OSError, ValueError, ModelRequestError, json.JSONDecodeError) as exc:
        logger.debug(f"Could not read loaded models from {endpoint}: {exc}")
        return None
    return any(_model_names_match(name, model_name) for name in names)


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

    return _truncate_prompt_text(prompt_text), title


def image_base64(image_filename: str, image_bytes: bytes) -> str:
    """Validate an uploaded recipe image and return it base64-encoded.

    Ollama's native ``/api/chat`` takes images as raw base64 strings in the
    message's ``images`` list; the data-URI form belongs to the OpenAI-style
    ``image_url`` content parts, which the native route does not accept.
    """
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

    return base64.b64encode(image_bytes).decode("ascii")


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


THINKING_START_PATTERN = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
THINKING_END_PATTERN = re.compile(r"</think\s*>", re.IGNORECASE)


class _ThinkingStreamFilter:
    """Split streamed text into answer text and embedded thinking text.

    Ollama exposes reasoning in ``message.thinking``, but some models still
    embed ``<think>`` blocks in ``message.content``. This filter keeps the two
    channels separate even when a tag is split across stream chunks.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._in_thinking = False

    def feed(self, text: str) -> tuple[str, str]:
        if text:
            self._pending += text
        return self._drain(final=False)

    def finish(self) -> tuple[str, str]:
        return self._drain(final=True)

    @staticmethod
    def _pending_tag_start(text: str, markers: tuple[str, ...]) -> int | None:
        """Index of a trailing ``<`` that may still become one of ``markers``."""
        index = text.rfind("<")
        if index == -1:
            return None

        suffix = text[index:].lower()
        for marker in markers:
            if marker.startswith(suffix):
                return index
            if suffix.startswith(marker) and ">" not in suffix:
                return index
        return None

    def _drain(self, final: bool) -> tuple[str, str]:
        content: list[str] = []
        thinking: list[str] = []

        while self._pending:
            if self._in_thinking:
                match = THINKING_END_PATTERN.search(self._pending)
                if match:
                    thinking.append(self._pending[: match.start()])
                    self._pending = self._pending[match.end() :]
                    self._in_thinking = False
                    continue
                if final:
                    thinking.append(self._pending)
                    self._pending = ""
                    break
                hold = self._pending_tag_start(self._pending, ("</think",))
                if hold is None:
                    thinking.append(self._pending)
                    self._pending = ""
                else:
                    thinking.append(self._pending[:hold])
                    self._pending = self._pending[hold:]
                break

            start_match = THINKING_START_PATTERN.search(self._pending)
            end_match = THINKING_END_PATTERN.search(self._pending)
            if end_match and (start_match is None or end_match.start() < start_match.start()):
                # An unmatched closing tag: the preceding text was reasoning.
                thinking.append(self._pending[: end_match.start()])
                self._pending = self._pending[end_match.end() :]
                continue
            if start_match:
                content.append(self._pending[: start_match.start()])
                self._pending = self._pending[start_match.end() :]
                self._in_thinking = True
                continue
            if final:
                content.append(self._pending)
                self._pending = ""
                break
            hold = self._pending_tag_start(self._pending, ("<think", "</think"))
            if hold is None:
                content.append(self._pending)
                self._pending = ""
            else:
                content.append(self._pending[:hold])
                self._pending = self._pending[hold:]
            break

        return "".join(content), "".join(thinking)


def _split_embedded_thinking(text: str) -> tuple[str, str]:
    filter_ = _ThinkingStreamFilter()
    content, thinking = filter_.feed(text)
    final_content, final_thinking = filter_.finish()
    return content + final_content, thinking + final_thinking


@dataclass(frozen=True)
class ChatResult:
    """Normalized result of one Ollama chat request."""

    content: str
    thinking: str
    metrics: dict[str, Any]
    finish_reason: str | None


def _duration_seconds(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value / 1_000_000_000


def _metrics_from_ollama_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Ollama's nanosecond timings into display-friendly metrics."""
    load_seconds = _duration_seconds(payload, "load_duration")
    generation_seconds = _duration_seconds(payload, "eval_duration")
    total_seconds = _duration_seconds(payload, "total_duration")
    prompt_seconds = _duration_seconds(payload, "prompt_eval_duration")

    token_count = payload.get("eval_count")
    prompt_token_count = payload.get("prompt_eval_count")

    metrics: dict[str, Any] = {}
    if load_seconds is not None:
        metrics["model_load_seconds"] = round(load_seconds, 3)
    if generation_seconds is not None:
        metrics["generation_seconds"] = round(generation_seconds, 3)
    if total_seconds is not None:
        metrics["total_seconds"] = round(total_seconds, 3)
    if isinstance(token_count, int) and not isinstance(token_count, bool):
        metrics["token_count"] = token_count
    if isinstance(prompt_token_count, int) and not isinstance(prompt_token_count, bool):
        metrics["prompt_token_count"] = prompt_token_count
    if token_count and generation_seconds:
        metrics["tokens_per_second"] = round(token_count / generation_seconds, 2)
    if prompt_token_count and prompt_seconds:
        metrics["prompt_tokens_per_second"] = round(prompt_token_count / prompt_seconds, 2)
    return metrics


def _chat_payload(
    model_name: str,
    prompt: str,
    user_message: str,
    *,
    stream: bool,
    images: list[str] | None = None,
) -> dict[str, Any]:
    user: dict[str, Any] = {"role": "user", "content": user_message}
    if images:
        # Ollama's native chat route reads images from the message itself.
        user["images"] = list(images)

    return {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt},
            user,
        ],
        "stream": stream,
        "options": {
            "temperature": 0.2,
            "num_predict": MAX_MODEL_TOKENS,
        },
    }


def _raise_model_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if error:
        raise ModelRequestError(f"The model returned an error: {error}")


def _parse_chat_payload(payload: object) -> ChatResult:
    if not isinstance(payload, dict):
        raise ModelRequestError("The model returned an invalid response")
    _raise_model_error(payload)

    message = payload.get("message")
    if not isinstance(message, dict):
        raise ModelRequestError("The model returned a response without a message")

    content = _content_text(message.get("content"))
    thinking = _content_text(message.get("thinking"))
    content, embedded_thinking = _split_embedded_thinking(content)
    thinking = f"{thinking}{embedded_thinking}"

    return ChatResult(
        content=content,
        thinking=thinking,
        metrics=_metrics_from_ollama_payload(payload),
        finish_reason=payload.get("done_reason"),
    )


def _read_chat_stream(
    response,
    *,
    on_thinking: Callable[[str], None] | None,
    on_content: Callable[[str], None] | None,
) -> ChatResult:
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    filter_ = _ThinkingStreamFilter()
    metrics: dict[str, Any] = {}
    finish_reason: str | None = None
    total_bytes = 0

    for raw_line in response:
        total_bytes += len(raw_line)
        if total_bytes > MAX_MODEL_RESPONSE_BYTES:
            raise ModelRequestError("Model response is too large")

        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelRequestError("The model returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise ModelRequestError("The model returned an invalid response")
        _raise_model_error(payload)

        message = payload.get("message")
        thinking_delta = _content_text(message.get("thinking")) if isinstance(message, dict) else ""
        content_delta = _content_text(message.get("content")) if isinstance(message, dict) else ""

        if thinking_delta:
            thinking_parts.append(thinking_delta)
            if on_thinking is not None:
                on_thinking(thinking_delta)

        filtered_content, embedded_thinking = filter_.feed(content_delta)
        if embedded_thinking:
            thinking_parts.append(embedded_thinking)
            if on_thinking is not None:
                on_thinking(embedded_thinking)
        if filtered_content:
            content_parts.append(filtered_content)
            if on_content is not None:
                on_content(filtered_content)

        if payload.get("done"):
            finish_reason = payload.get("done_reason")
            metrics = _metrics_from_ollama_payload(payload)
            break

    final_content, final_thinking = filter_.finish()
    if final_thinking:
        thinking_parts.append(final_thinking)
        if on_thinking is not None:
            on_thinking(final_thinking)
    if final_content:
        content_parts.append(final_content)
        if on_content is not None:
            on_content(final_content)

    return ChatResult(
        content="".join(content_parts),
        thinking="".join(thinking_parts),
        metrics=metrics,
        finish_reason=finish_reason,
    )


def _ollama_chat(
    endpoint: str,
    model_name: str,
    prompt: str,
    user_message: str,
    *,
    stage: str = "recipe generation",
    stream: bool = False,
    images: list[str] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
) -> ChatResult:
    chat_url = ollama_chat_url(endpoint)
    payload = _chat_payload(model_name, prompt, user_message, stream=stream, images=images)
    logger.info(
        f"Sending {stage} request to {chat_url} (model={model_name}, "
        f"stream={stream}, system_prompt_chars={len(prompt)}, user_chars={len(user_message)})"
    )
    request = Request(
        chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/x-ndjson" if stream else "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        response = urlopen(request, timeout=MODEL_TIMEOUT_SECONDS)
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
        with response:
            logger.debug(f"Model request to {chat_url} returned HTTP {response.status}")
            if stream:
                result = _read_chat_stream(response, on_thinking=on_thinking, on_content=on_content)
            else:
                body = _read_response(response, MAX_MODEL_RESPONSE_BYTES)
                logger.debug(f"Received {len(body)} bytes from the model")
                try:
                    response_payload = json.loads(body)
                except json.JSONDecodeError as exc:
                    raise ModelRequestError("The model returned invalid JSON") from exc
                result = _parse_chat_payload(response_payload)
    except BrokenPipeError, ConnectionResetError:
        raise
    except (OSError, TimeoutError) as exc:
        logger.error(f"Model response from {chat_url} was interrupted: {exc}")
        raise ModelRequestError(f"The model response was interrupted: {exc}") from exc

    logger.info(
        f"{stage} response from {model_name}: "
        f"finish_reason={result.finish_reason!r}, "
        f"content_chars={len(result.content)}, "
        f"thinking_chars={len(result.thinking)}, "
        f"metrics={result.metrics}"
    )
    logger.debug(f"{stage} content preview: {result.content[:2000]!r}")
    if result.thinking:
        logger.debug(f"{stage} thinking preview: {result.thinking[:2000]!r}")

    if not result.content.strip():
        if result.finish_reason == "length":
            raise ModelRequestError(
                f"The {stage} model ({model_name}) stopped before producing "
                "an answer because it reached the token limit; it returned "
                "only reasoning/thinking text. Try again, or use a "
                "non-thinking model for the all-purpose model."
            )
        if result.thinking.strip():
            raise ModelRequestError(
                f"The {stage} model ({model_name}) returned only "
                "reasoning/thinking text and no answer "
                f"(finish_reason={result.finish_reason!r}). "
                "Try again, or use a non-thinking model."
            )
        raise ModelRequestError(
            f"The {stage} model ({model_name}) returned an empty response " f"(finish_reason={result.finish_reason!r}, metrics={result.metrics!r})"
        )

    return result


def _chat(
    endpoint: str,
    model_name: str,
    prompt: str,
    user_message: str,
    stage: str = "recipe generation",
    images: list[str] | None = None,
) -> str:
    return _ollama_chat(endpoint, model_name, prompt, user_message, stage=stage, stream=False, images=images).content


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
        normalized["source"] = {field: (source.get(field).strip() or None if isinstance(source.get(field), str) else None) for field in SOURCE_FIELDS}

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


EventCallback = Callable[[dict[str, Any]], None]


def _emit(event_callback: EventCallback | None, event_type: str, **fields: Any) -> None:
    if event_callback is not None:
        event_callback({"type": event_type, **fields})


def _emit_status(event_callback: EventCallback | None, state: str, message: str) -> None:
    _emit(event_callback, "status", state=state, message=message)


def _report_model_loading(event_callback: EventCallback | None, endpoint: str, model_name: str) -> bool | None:
    """Report a loading state when Ollama says the model is not in memory."""
    loaded = is_model_loaded(endpoint, model_name)
    if loaded is False:
        _emit_status(event_callback, STATUS_LOADING_MODEL, f"Loading {model_name} into memory...")
    return loaded


def _prepare_image_draft_input(
    resolved: AIConfigView,
    all_purpose_model_name: str,
    image_model_name: str,
    images: list[tuple[str, bytes]],
    event_callback: EventCallback | None,
) -> tuple[str, str]:
    # Stage 1 (vision): transcribe every image in the order it was uploaded.
    # Stage 2 (all-purpose): draft the recipe from the combined text.
    image_count = len(images)
    _report_model_loading(event_callback, resolved.endpoint, image_model_name)

    transcriptions: list[str] = []
    for index, (image_filename, image_bytes) in enumerate(images, start=1):
        position = f"image {index} of {image_count}" if image_count > 1 else "the image"
        _emit_status(
            event_callback,
            STATUS_PREPARING,
            f"Sending {position} ({image_filename}) to {image_model_name} for transcription...",
        )
        encoded = image_base64(image_filename, image_bytes)
        logger.info(f"Transcribing recipe image with local model '{image_model_name}' ({len(image_bytes)} bytes, {image_filename})")
        transcription = _chat(
            resolved.endpoint,
            image_model_name,
            resolved.new_recipe_from_image_prompt,
            "Recipe image:",
            stage="image transcription",
            images=[encoded],
        )
        logger.info(f"Image transcription from '{image_model_name}' ({len(transcription)} characters): {transcription[:2000]!r}")
        transcriptions.append(f"--- {position.capitalize()}: {image_filename} ---\n{transcription}")

        if index < image_count:
            _emit_status(
                event_callback,
                STATUS_PREPARING,
                f"Transcribed {position}. Sending the next image...",
            )

    transcribed_label = f"{image_count} images" if image_count > 1 else "image"
    _emit_status(
        event_callback,
        STATUS_PREPARING,
        f"Transcribed {transcribed_label}. Preparing the extracted text for {all_purpose_model_name}...",
    )
    combined = "\n\n".join(transcriptions)
    return _truncate_prompt_text(f"Recipe text (transcribed from {transcribed_label}):\n{combined}"), ""


def _prepare_text_or_url_draft_input(
    input_type: str,
    input_value: str,
    event_callback: EventCallback | None,
) -> tuple[str, str]:
    user_message, title = _build_user_message(input_type, input_value)
    if input_type == "url":
        _emit_status(event_callback, STATUS_PREPARING, "Page fetched. Preparing the extracted text...")
    else:
        _emit_status(event_callback, STATUS_PREPARING, "Preparing the recipe text...")
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
    event_callback: EventCallback | None = None,
    images: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    images = list(images or [])
    resolved = resolve_ai_config(config)
    if not resolved.is_configured:
        raise ModelUnavailable("The local model is not configured")
    if input_type == "image" and not resolved.is_image_configured:
        raise ModelUnavailable("The image analysis model is not configured")
    if input_type == "image" and not images:
        raise ValueError("Expected at least one recipe image")

    _emit_status(event_callback, STATUS_CHECKING_MODEL, "Checking model status...")
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
        _emit_status(event_callback, STATUS_PREPARING, f"Fetching recipe page: {input_value}")
    elif input_type == "image":
        if len(images) == 1:
            _emit_status(event_callback, STATUS_PREPARING, "Preparing the recipe image...")
        else:
            _emit_status(event_callback, STATUS_PREPARING, f"Preparing {len(images)} recipe images...")
    else:
        _emit_status(event_callback, STATUS_PREPARING, "Preparing the recipe text...")

    if input_type == "image":
        user_message, title = _prepare_image_draft_input(
            resolved,
            all_purpose_model_name,
            image_model_name,
            images,
            event_callback,
        )
    else:
        user_message, title = _prepare_text_or_url_draft_input(
            input_type,
            input_value,
            event_callback,
        )

    logger.info(
        f"Generating recipe from {input_type} input with local model '{all_purpose_model_name}' "
        f"({len(user_message)} characters of source content)"
    )

    all_purpose_loaded = _report_model_loading(event_callback, resolved.endpoint, all_purpose_model_name)
    last_status = None

    def emit_progress(state: str, message: str) -> None:
        nonlocal last_status
        if last_status != state:
            last_status = state
            _emit_status(event_callback, state, message)

    if all_purpose_loaded is not False:
        emit_progress(STATUS_GENERATING, f"Generating recipe with {all_purpose_model_name}...")

    def on_thinking(_text: str) -> None:
        emit_progress(STATUS_THINKING, "Thinking...")

    def on_content(_text: str) -> None:
        emit_progress(STATUS_GENERATING, f"Generating recipe with {all_purpose_model_name}...")

    result = _ollama_chat(
        resolved.endpoint,
        all_purpose_model_name,
        resolved.new_recipe_prompt,
        user_message,
        stage="recipe drafting" if input_type == "image" else "recipe generation",
        stream=event_callback is not None,
        on_thinking=on_thinking,
        on_content=on_content,
    )

    if result.metrics:
        _emit(event_callback, "metrics", metrics=result.metrics)

    content, metadata = parse_model_output(result.content)
    logger.info(
        f"Model returned {len(result.content)} characters; parsed {len(content)} characters of Markdown " f"and metadata fields {sorted(metadata)}"
    )
    _apply_default_source(metadata, input_type, all_purpose_model_name, input_value, title)
    _emit_status(event_callback, STATUS_COMPLETE, "Generation complete.")
    return {"content": content, "metadata": metadata, "metrics": result.metrics}
