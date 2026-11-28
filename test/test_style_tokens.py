"""Focus rings and status-pill colors have one CSS definition."""

from pathlib import Path

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


def test_focus_ring_and_status_tokens_are_defined_once():
    definitions = (ASSETS / "definitions.css").read_text(encoding="utf-8")
    for token in (
        "--focus-ring:",
        "--status-recording-color:",
        "--status-recording-border:",
        "--status-progress-color:",
        "--status-progress-border:",
    ):
        assert definitions.count(token) == 1, f"{token} must be defined exactly once"


def test_component_stylesheets_use_the_shared_tokens():
    offenders = []
    for path in ASSETS.rglob("*.css"):
        if "katex" in path.parts or path.name == "definitions.css":
            continue
        source = path.read_text(encoding="utf-8")
        if "outline: 2px solid var(--food-color);" in source:
            offenders.append(str(path))
        if "color-mix(in srgb, var(--danger-color) 45%" in source:
            offenders.append(str(path))
    assert offenders == [], f"hard-coded focus/status styles in: {offenders}"


def test_status_pill_components_consume_the_tokens():
    for relative in ("ai-assistant/ai-assistant.css", "speech-button/speech-button.css"):
        source = (ASSETS / relative).read_text(encoding="utf-8")
        assert "--status-recording-color" in source
        assert "--status-progress-color" in source
        assert "--focus-ring" in source
