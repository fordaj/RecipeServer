"""The microphone/transcription transport has one browser implementation."""

from pathlib import Path
import shutil
import subprocess

import pytest

TEST_JS = Path(__file__).parent / "js" / "dictation_test.js"
ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_shared_dictation_transport():
    result = subprocess.run([shutil.which("node"), str(TEST_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dictation checks passed" in result.stdout


def test_consumers_delegate_to_the_shared_controller():
    for relative in ("speech-button/speech-button.js", "ai-assistant/ai-assistant.js"):
        source = (ASSETS / relative).read_text(encoding="utf-8")
        assert "RecipeDictation" in source
        assert "new MediaRecorder" not in source
        assert "getUserMedia" not in source
        assert '"/api/transcribe"' not in source


def test_generated_pages_load_the_controller_before_consumers():
    from types import SimpleNamespace

    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
    from recipeserver.markdown_to_html.page import build_recipe_html

    page = Path(__file__).parent / "tmp-dictation" / "recipe.html"
    page.parent.mkdir(exist_ok=True)
    page.write_text("<h1>R</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=page.parent.parent))
    generator.add(Recipe({"categories": ["R"]}, page))
    generator.convert()
    index_html = (page.parent.parent / "index.html").read_text(encoding="utf-8")
    assert index_html.index("/assets/dictation.js") < index_html.index("/assets/speech-button/speech-button.js")
    assert index_html.index("/assets/dictation.js") < index_html.index("/assets/ai-assistant/ai-assistant.js")

    recipe_html = build_recipe_html(
        source_title="R",
        heading_color="#8d5542",
        metadata_json="{}",
        recipe_scaler_html="",
        body="<h1>R</h1>",
        ratings_html="",
        comments_html="",
    )
    assert recipe_html.index("/assets/dictation.js") < recipe_html.index("/assets/ai-assistant/ai-assistant.js")
