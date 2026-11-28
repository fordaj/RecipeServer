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


def test_http_and_assistant_path_checks_share_one_implementation():
    assert _delegates_to("server.py", "_resolve_markdown_path", "resolve_recipe_file")
    assert _delegates_to("ai_assistant.py", "_resolve_recipe_path", "resolve_recipe_file")
    assert _delegates_to("server.py", "_resolve_recipe_directory", "resolve_recipe_folder")


@pytest.mark.parametrize("relative_path", DOMAIN_MODULES)
def test_domain_modules_do_not_import_higher_layers(relative_path: str):
    assert not (_imported_names(_tree(relative_path)) & HIGHER_LAYER_MODULES)
