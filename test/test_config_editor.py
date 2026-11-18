"""Tests for the Configuration dialog's JS behavior: the select field added
for ``timeline_retention`` and the shared checkbox path."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CONFIG_EDITOR_JS_TEST = Path(__file__).parent / "js" / "config_editor_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_config_editor_renders_and_saves_the_timeline_retention_select():
    result = subprocess.run(
        [shutil.which("node"), str(CONFIG_EDITOR_JS_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "config editor checks passed" in result.stdout
