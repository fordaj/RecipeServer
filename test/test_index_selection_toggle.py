import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
SELECTION_TOGGLE_TEST = Path(__file__).parent / "js" / "index_selection_toggle_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_select_button_toggles_selection_mode():
    result = subprocess.run(
        [shutil.which("node"), str(SELECTION_TOGGLE_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_selection_mode_is_a_button_in_the_bulk_controls():
    script = (ASSETS / "index.js").read_text(encoding="utf-8")

    # The Selection Mode checkbox is replaced by a Select/Cancel button.
    assert "#bulk-selection-mode" not in script
    assert 'document.querySelector("#bulk-selection-toggle")' in script
    assert 'selectionToggle.addEventListener("click", () =>' in script
    assert "setSelectionMode(ctx, !ctx.selectionModeEnabled)" in script
    assert 'selectionToggleLabel.textContent = enabled ? "Cancel" : "Select"' in script
