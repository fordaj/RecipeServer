import shutil
import subprocess
from pathlib import Path

import pytest

FILTER_MENUS_TEST = Path(__file__).parent / "js" / "index_filter_menus_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_advanced_filter_menus_filter_and_count_recipes():
    result = subprocess.run(
        [shutil.which("node"), str(FILTER_MENUS_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
