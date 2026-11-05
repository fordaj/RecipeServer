"""Optional local-model integration for creating recipes from text or URLs."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import frontmatter
from bs4 import BeautifulSoup

from ._logger import logger


MODEL_TIMEOUT_SECONDS = 120
AVAILABILITY_TIMEOUT_SECONDS = 3
URL_TIMEOUT_SECONDS = 20
MAX_URL_BYTES = 2 * 1024 * 1024
MAX_MODEL_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PROMPT_INPUT_CHARS = 60_000
USER_AGENT = "RecipeServer/0.1"

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


def is_configured(config: object | None) -> bool:
    if config is None:
        return False

    endpoint = str(getattr(config, "model_endpoint", "") or "").strip()
    prompt = str(getattr(config, "new_recipe_prompt", "") or "").strip()
    return bool(endpoint and prompt)


def ai_status(config: object | None) -> dict[str, Any]:
    endpoint = str(getattr(config, "model_endpoint", "") or "").strip()
    model_name = str(getattr(config, "model_name", "") or "").strip()
    configured = is_configured(config)
    logger.debug(
        f"Checking local model status: configured={configured}, "
        f"endpoint={endpoint or '(none)'}, model={model_name or '(auto)'}"
    )

    if not configured:
        logger.info("AI recipe creation is not configured")
        return {"configured": False, "available": False, "model": model_name}

    available = is_available(endpoint)
    logger.info(
        f"Local model status: configured=True, available={available}, "
        f"endpoint={endpoint}"
    )
    return {
        "configured": True,
        "available": available,
        "model": model_name,
    }


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
            logger.warning(
                f"Model list request to {models_url} returned HTTP {response.status}"
            )
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
                f"{endpoint} does not expose a model list (HTTP {exc.code}); "
                "assuming chat requests are supported"
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
    logger.debug(
        f"Extracted {len(text)} characters of text from {url} (title={title!r})"
    )
    return title, text


def _build_user_message(input_type: str, input_value: str) -> tuple[str, str]:
    title = ""

    if input_type == "url":
        title, text = fetch_url_content(input_value)
        prompt_text = (
            f"Recipe URL: {input_value}\n"
            f"Page title: {title}\n\n"
            f"Recipe content:\n{text}"
        )
    elif input_type == "text":
        prompt_text = f"Recipe text:\n{input_value}"
    else:
        raise ValueError("inputType must be 'url' or 'text'")

    if len(prompt_text) > MAX_PROMPT_INPUT_CHARS:
        prompt_text = (
            prompt_text[:MAX_PROMPT_INPUT_CHARS]
            + "\n\n[The source was truncated because it was very long.]"
        )

    return prompt_text, title


def _chat(endpoint: str, model_name: str, prompt: str, user_message: str) -> str:
    chat_url = normalize_chat_completions_url(endpoint)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "stream": False,
    }
    logger.info(
        f"Sending recipe request to {chat_url} (model={model_name}, "
        f"system_prompt_chars={len(prompt)}, user_chars={len(user_message)})"
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
            logger.debug(
                f"Model request to {chat_url} returned HTTP {response.status}"
            )
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

    content: object = None
    if isinstance(response_payload, dict):
        choices = response_payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                if content is None:
                    content = choice.get("text")

        if content is None:
            message = response_payload.get("message")
            if isinstance(message, dict):
                content = message.get("content")

    if not isinstance(content, str) or not content.strip():
        raise ModelRequestError("The model returned an empty response")

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


def generate_recipe(config: object, input_type: str, input_value: str) -> dict[str, Any]:
    if not is_configured(config):
        raise ModelUnavailable("The local model is not configured")

    endpoint = str(getattr(config, "model_endpoint", "") or "").strip()
    prompt = str(getattr(config, "new_recipe_prompt", "") or "").strip()
    configured_name = str(getattr(config, "model_name", "") or "").strip()

    model_name = resolve_model_name(endpoint, configured_name)
    if not model_name:
        raise ModelUnavailable(
            "Could not determine a model name. Configure model_name in config.txt."
        )

    user_message, title = _build_user_message(input_type, input_value)
    logger.info(
        f"Generating recipe from {input_type} input with local model '{model_name}' "
        f"({len(user_message)} characters of source content)"
    )
    output = _chat(endpoint, model_name, prompt, user_message)
    content, metadata = parse_model_output(output)
    logger.info(
        f"Model returned {len(output)} characters; parsed "
        f"{len(content)} characters of Markdown and metadata fields "
        f"{sorted(metadata)}"
    )

    default_source = _source_for_input(
        input_type,
        model_name,
        url=input_value if input_type == "url" else "",
        title=title,
    )
    source = metadata.get("source")
    if not isinstance(source, dict):
        metadata["source"] = default_source
    else:
        for field, value in default_source.items():
            if not source.get(field):
                source[field] = value

    return {"content": content, "metadata": metadata}
