"""Library-relative path rules for recipe Markdown files.

Every feature that accepts a path from a URL, a model tool call, or a
configuration value uses the same rules: the path is library-relative, points
at a Markdown file (or a folder inside the library), and cannot escape the
source directory. Keeping the rules here means a change to path safety has
one place to land rather than four subtly different copies.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

# A recipe is a directory holding a file with exactly this name.
RECIPE_FILENAME = "recipe.md"
# Paths accepted by the editing and assistant APIs must point at Markdown.
MARKDOWN_FILE_SUFFIX = ".md"


def iter_recipe_files(source_directory: Path) -> list[Path]:
    """Return every recipe in the library, sorted and excluding symlinks.

    Sorting makes the duplicate-``recipe_id`` rule deterministic, and skipping
    symlinks keeps a link outside the library from being treated as a recipe.
    """
    root = Path(source_directory)
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob(RECIPE_FILENAME) if not path.is_symlink() and path.is_file())


def resolve_recipe_file(source_directory: Path, requested_path: object, *, action: str = "edited") -> Path:
    """Return the resolved path of a library-relative Markdown file.

    ``action`` completes the error for a non-Markdown path ("edited" for
    browser writes, "read" for the assistant's read-only tools), so each caller
    keeps its established error wording.
    """
    if isinstance(requested_path, str):
        requested_path = requested_path.strip()
    if not isinstance(requested_path, str) or not requested_path:
        raise ValueError("Expected a recipe path")
    if "\\" in requested_path or "\x00" in requested_path:
        raise ValueError("Invalid file path")

    relative_path = Path(requested_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Path must stay inside the source directory")
    if relative_path.suffix.lower() != MARKDOWN_FILE_SUFFIX:
        raise ValueError(f"Only Markdown ({MARKDOWN_FILE_SUFFIX}) files can be {action}")

    root = Path(source_directory).resolve()
    file_path = (root / relative_path).resolve()
    if not file_path.is_relative_to(root):
        raise ValueError("Path must stay inside the source directory")
    return file_path


def resolve_recipe_folder(source_directory: Path, requested_path: object) -> Path:
    """Return the resolved path of a library-relative recipe folder.

    An empty path denotes the library root itself.
    """
    if requested_path is None:
        requested_path = ""
    if not isinstance(requested_path, str):
        raise ValueError("Expected a folder path")
    if "\\" in requested_path or "\x00" in requested_path:
        raise ValueError("Invalid folder path")
    if requested_path and (requested_path.startswith("/") or any(part in {"", ".", ".."} for part in requested_path.split("/"))):
        raise ValueError("Folder path must stay inside the source directory")

    relative_path = Path(requested_path) if requested_path else Path()
    if PureWindowsPath(requested_path).drive:
        raise ValueError("Folder path must stay inside the source directory")

    root = Path(source_directory).resolve()
    folder_path = (root / relative_path).resolve()
    if not folder_path.is_relative_to(root):
        raise ValueError("Folder path must stay inside the source directory")
    return folder_path


def display_path(source_directory: Path, file_path: Path) -> str:
    """Return the library-relative POSIX path used in prompts and replies."""
    return Path(file_path).resolve().relative_to(Path(source_directory).resolve()).as_posix()
