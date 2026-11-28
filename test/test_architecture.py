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
        calls = {call.func.attr for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)}
        assert "_begin_event_stream" in calls
        assert "_send_sse_event" in calls


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
    assert "def fallback_main_image" not in server_source
    assert "def first_image_reference" not in server_source
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
