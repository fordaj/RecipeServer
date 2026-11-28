"""The startup entry points are one sequence, reachable in two ways."""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata

import pytest

import recipeserver


def test_console_script_entry_point_is_the_package_main(monkeypatch):
    scripts = [entry for entry in metadata.entry_points(group="console_scripts") if entry.name == "recipeserver"]
    assert scripts, "recipeserver console script is not installed"

    entry_point = scripts[0].load()
    assert entry_point is recipeserver.main

    monkeypatch.setattr(sys, "argv", ["recipeserver", "--help"])
    with pytest.raises(SystemExit) as exc:
        entry_point()
    assert exc.value.code == 0


def test_module_entry_point_uses_the_same_sequence():
    result = subprocess.run(
        [sys.executable, "-m", "recipeserver", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--log-level" in result.stdout


def test_importing_a_leaf_module_does_not_load_the_server_stack():
    program = "import sys; import recipeserver.shopping_list; " "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('recipeserver'))))"
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    loaded = set(result.stdout.splitlines())
    assert "recipeserver.shopping_list" in loaded
    for heavy in ("recipeserver.core", "recipeserver.server", "recipeserver.tray", "recipeserver.config", "tkinter", "pystray"):
        assert heavy not in loaded, f"importing a leaf module loaded {heavy}"
