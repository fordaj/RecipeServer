"""Executable architectural constraints.

These tests run in CI (the workflow runs the whole pytest suite) and encode the
structural rules that keep the codebase navigable for parallel work: canonical
constants, canonical path rules, and one-way dependencies.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "recipeserver"

# Modules that own a concept must not reach up into the HTTP/orchestration
# layers. Dependencies point inward toward these leaf modules, never outward.
DOMAIN_MODULES = (
    "archive.py",
    "color_utils.py",
    "history.py",
    "image_handler.py",
    "recipe_paths.py",
    "recipe_utils.py",
    "session.py",
    "shopping_list.py",
    "sources.py",
    "markdown_to_html/icons.py",
    "markdown_to_html/quantities.py",
)
HIGHER_LAYER_MODULES = {"config", "core", "index_html_generator", "server", "authorization"}


def _tree(relative_path: str) -> ast.Module:
    return ast.parse((SOURCE / relative_path).read_text(encoding="utf-8"))


def _string_literals(tree: ast.Module) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
            names.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
    return names


def _delegates_to(relative_path: str, function_name: str, callee: str) -> bool:
    for node in ast.walk(_tree(relative_path)):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return any(isinstance(call.func, ast.Name) and call.func.id == callee for call in ast.walk(node) if isinstance(call, ast.Call))
    return False


@pytest.mark.parametrize("relative_path", ["server.py", "ai_assistant.py", "core.py", "metadata_options.py", "index_html_generator.py"])
def test_recipe_filename_has_one_definition(relative_path: str):
    assert "recipe.md" not in _string_literals(_tree(relative_path))


@pytest.mark.parametrize("relative_path", ["server.py", "ai_assistant.py", "index_html_generator.py"])
def test_markdown_suffix_has_one_definition(relative_path: str):
    assert ".md" not in _string_literals(_tree(relative_path))


@pytest.mark.parametrize("relative_path", ["server.py"])
def test_both_streaming_endpoints_share_the_sse_framing(relative_path: str):
    tree = _tree(relative_path)
    for handler in ("_stream_ai_recipe", "_stream_ai_assistant"):
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == handler)
        calls = {call.func.id for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        assert "run_stream" in calls
    server_source = (SOURCE / relative_path).read_text(encoding="utf-8")
    assert "def _send_sse_event" not in server_source
    assert "def _begin_event_stream" not in server_source


@pytest.mark.parametrize(
    ("relative_path", "names"),
    [
        ("config.py", ("DEFAULT_SERVER_PORT", "DEFAULT_KEEP_ALIVE_MINUTES", "DEFAULT_DICTATION_ENABLED", "DEFAULT_FOOD_COLOR")),
        ("ai_recipe.py", ("DEFAULT_KEEP_ALIVE_MINUTES",)),
        ("server.py", ("DEFAULT_SERVER_BIND_ADDRESS", "DEFAULT_SERVER_PORT")),
        ("config_endpoints.py", ("DEFAULT_DICTATION_ENABLED", "DEFAULT_KEEP_ALIVE_MINUTES", "DEFAULT_TRANSCRIPTION_MODEL")),
        ("index_html_generator.py", ("DEFAULT_DICTATION_ENABLED", "DEFAULT_FOOD_COLOR")),
        ("tray.py", ("DEFAULT_SERVER_PORT",)),
        ("markdown_to_html/converter.py", ("DEFAULT_FOOD_COLOR",)),
    ],
)
def test_configuration_defaults_have_one_leaf_definition(relative_path: str, names: tuple[str, ...]):
    tree = _tree(relative_path)
    assert set(names) <= _imported_names(tree)
    if relative_path == "ai_recipe.py":
        assert "0" not in _string_literals(tree), "duplicated keep-alive default in ai_recipe.py"


def test_config_defaults_is_a_leaf_module():
    assert not (_imported_names(_tree("config_defaults.py")) & {"config", "server", "core", "retention"})


BROWSER_API_BUNDLES = (
    "recipe-editor/recipe-editor.js",
    "recipe-history/timeline.js",
    "dialogs.js",
    "recipe-feedback.js",
    "shopping-list/shopping-list.js",
    "ai-assistant/ai-assistant.js",
    "config-editor.js",
    "dictation.js",
)


def test_css_design_tokens_have_one_owner():
    definitions = (SOURCE / "assets" / "definitions.css").read_text(encoding="utf-8")
    assert "--focus-ring:" in definitions
    assert "--status-recording-border:" in definitions
    for path in (SOURCE / "assets").rglob("*.css"):
        if "katex" in path.parts or path.name == "definitions.css":
            continue
        source = path.read_text(encoding="utf-8")
        assert "outline: 2px solid var(--food-color);" not in source


def test_browser_dictation_transport_has_one_owner():
    for relative in ("speech-button/speech-button.js", "ai-assistant/ai-assistant.js"):
        source = (SOURCE / "assets" / relative).read_text(encoding="utf-8")
        assert "RecipeDictation" in source
        assert "new MediaRecorder" not in source


def test_metadata_value_collection_has_one_owner():
    for relative in ("index_html_generator.py", "metadata_options.py"):
        source = (SOURCE / relative).read_text(encoding="utf-8")
        assert "collect_metadata_values" in source
        assert "def _field_values" not in source
    index_source = (SOURCE / "index_html_generator.py").read_text(encoding="utf-8")
    assert "def collect_metadata_values" not in index_source


def test_browser_katex_loading_has_one_owner():
    for relative in ("ai-assistant/ai-assistant.js", "shopping-list/shopping-list.js"):
        source = (SOURCE / "assets" / relative).read_text(encoding="utf-8")
        assert "RecipeKatexLoader" in source
        assert "katex.min.js" not in source


def test_browser_date_labels_have_one_owner():
    for relative in ("time.js", "recipe-history/timeline.js"):
        source = (SOURCE / "assets" / relative).read_text(encoding="utf-8")
        assert "RecipeDates" in source
        assert "getFullYear()" not in source, f"{relative} still decides the year itself"


def test_model_list_uses_the_catalog_reader():
    source = (SOURCE / "ai_recipe.py").read_text(encoding="utf-8")
    start = source.index("def list_models(")
    end = source.index("def _model_catalog(", start)
    body = source[start:end]
    assert "_model_catalog(" in body
    assert "_fetch_model_names(" not in body


def test_browser_page_path_has_one_owner():
    for relative in ("recipe-feedback.js", "recipe-history/timeline.js", "ai-assistant/ai-assistant.js"):
        source = (SOURCE / "assets" / relative).read_text(encoding="utf-8")
        if relative == "recipe-feedback.js":
            assert "RecipePagePath.markdownPathFromLocation" in source
        else:
            assert "RecipePagePath." in source
        assert "decodeURIComponent(window.location.pathname" not in source


def test_browser_json_requests_share_one_wrapper():
    for relative in BROWSER_API_BUNDLES:
        source = (SOURCE / "assets" / relative).read_text(encoding="utf-8")
        assert "window.RecipeApi.requestJson" in source, f"{relative} does not use the shared wrapper"
        assert "response.json().catch(() => ({}))" not in source, f"{relative} still unwraps responses itself"


def test_auth_flow_decisions_are_not_in_the_handler():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    assert "def _queue_cookie" not in server_source
    assert "self.auth.begin_login(" not in server_source
    assert "self.auth.finish_login(" not in server_source
    assert "from .auth_endpoints import" in server_source


def test_config_and_auth_status_shapes_have_one_owner():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    for name in ("_probe_configured_models", "_transcription_settings", "_dictation_enabled"):
        assert f"def {name}" not in server_source
    assert '"csrfToken": None' not in server_source
    assert "from .config_endpoints import" in server_source


def test_history_api_operations_are_not_implemented_in_the_handler():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    for name in ("_history_query", "_snapshot_payload", "_history_snapshot_for", "_render_history_preview", "_sanitize_preview_html"):
        assert f"def {name}" not in server_source
    assert "from .recipe_history_api import" in server_source


def test_request_parsing_is_not_implemented_in_the_handler():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    for name in ("_read_body", "_read_json_payload", "_parse_multipart_message", "_validate_uploaded_images", "_write_uploaded_images"):
        assert f"def {name}" not in server_source
    assert "from .request_payload import" in server_source


def test_configuration_and_retention_share_a_leaf_policy_module():
    config_imports = _imported_names(_tree("config.py"))
    retention_imports = _imported_names(_tree("retention.py"))
    policy_imports = _imported_names(_tree("retention_policy.py"))

    assert "retention" not in config_imports
    assert "config" not in retention_imports
    assert "retention_policy" in config_imports
    assert "retention_policy" in retention_imports
    assert not (policy_imports & (HIGHER_LAYER_MODULES | {"history", "server", "core"})), f"policy leaf imports higher layers: {policy_imports}"


def test_rating_rules_are_not_redefined_in_the_http_layer():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    for name in ("_validate_ratings", "_apply_rating_override", "_validate_bulk_rating", "_now_utc_iso"):
        assert f"def {name}" not in server_source
    for name in ("validate_ratings", "apply_rating_override", "validate_bulk_rating"):
        assert name in server_source


def test_assistant_imports_only_the_public_ai_transport():
    for node in ast.walk(_tree("ai_assistant.py")):
        if isinstance(node, ast.ImportFrom) and node.module == "ai_recipe":
            assert all(not alias.name.startswith("_") for alias in node.names)


def test_ai_drafting_uses_the_canonical_multi_value_fields():
    tree = _tree("ai_recipe.py")
    assert "STRING_LIST_FIELDS" in _imported_names(tree)
    assert "LIST_FIELDS" not in _imported_names(tree)


def test_editor_metadata_schema_and_validation_have_one_owner():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    assert "def validate_editor_metadata" not in server_source
    assert "def _validate_editor_metadata" not in server_source
    assert "def validate_assistant_metadata" not in server_source
    for name in ("EDITOR_METADATA_FIELDS", "validate_editor_metadata", "validate_assistant_metadata"):
        assert name in server_source
    # Folder naming is HTTP-layer policy and must stay in the handler.
    assert "def _recipe_folder_name" in server_source


def test_image_reference_rules_do_not_live_in_the_http_layer():
    server_source = (SOURCE / "server.py").read_text(encoding="utf-8")
    for name in ("fallback_main_image", "first_image_reference", "validate_image_content", "validate_svg_content", "validate_image_name"):
        assert f"def {name}" not in server_source
    assert "from .recipe_images import" in server_source


@pytest.mark.parametrize("relative_path", ["core.py", "metadata_options.py", "ai_assistant.py"])
def test_recipe_discovery_has_one_implementation(relative_path: str):
    assert "iter_recipe_files" in _imported_names(_tree(relative_path))


def test_http_and_assistant_path_checks_share_one_implementation():
    assert _delegates_to("server.py", "_resolve_markdown_path", "resolve_recipe_file")
    assert _delegates_to("ai_assistant.py", "_resolve_recipe_path", "resolve_recipe_file")
    assert _delegates_to("server.py", "_resolve_recipe_directory", "resolve_recipe_folder")


def test_tray_uses_the_canonical_server_defaults():
    tree = _tree("tray.py")
    imported = _imported_names(tree)
    assert {"DEFAULT_SERVER_PORT", "LOCALHOST", "WILDCARD_BIND_ADDRESSES"} <= imported
    assert "8000" not in _string_literals(tree)


@pytest.mark.parametrize("relative_path", ["markdown_to_html/converter.py", "ai_assistant.py"])
def test_title_extraction_has_one_owner(relative_path: str):
    assert "first_heading" in _imported_names(_tree(relative_path))


def test_transcriber_uses_the_canonical_ollama_chat_url():
    tree = _tree("transcriber.py")
    assert '"/api/chat"' not in _string_literals(tree)
    assert "ollama_chat_url" in _imported_names(tree)


@pytest.mark.parametrize("relative_path", DOMAIN_MODULES)
def test_domain_modules_do_not_import_higher_layers(relative_path: str):
    assert not (_imported_names(_tree(relative_path)) & HIGHER_LAYER_MODULES)


SOURCE_FILE_SUFFIXES = {".py", ".js", ".css", ".html"}


def test_no_inline_svg_outside_vendored_katex():
    for path in SOURCE.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_FILE_SUFFIXES or "katex" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "<svg" not in text, f"inline SVG in {path}; use an assets/*.svg file"
        assert "data:image/svg+xml" not in text, f"encoded SVG in {path}; use an assets/*.svg file"


def test_every_python_module_has_a_sibling_documentation_page():
    for path in SOURCE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        assert path.with_name(f"{path.name}.md").is_file(), f"missing documentation page for {path}"


PROMPT_FILES = {"NewRecipePrompt.md", "NewRecipeFromImagePrompt.md", "FindOneForMePrompt.md", "AssistantPrompt.md"}


def test_documentation_pages_open_with_a_mermaid_diagram():
    for path in SOURCE.rglob("*.md"):
        if path.name in PROMPT_FILES or "assets" in path.parts:
            continue
        head = path.read_text(encoding="utf-8")[:2000]
        assert "```mermaid" in head, f"no Mermaid diagram at the top of {path}"
