"""Gate and shared fixtures for the scale tests.

The scale tests build and serve a mock recipe library at up to 10,000
recipes, so they are far too heavy for the default suite. They run only
when explicitly requested:

    RECIPE_SERVER_SCALE=1 uv run pytest test/scale -s

``RECIPE_SERVER_SCALE_SIZES`` trims the measured sizes (default
``10,100,1000,10000``), ``RECIPE_SERVER_SCALE_ARTIFACTS`` redirects where
``report.json``/``report.md`` are written (default ``.scale-artifacts/``),
and ``RECIPE_SERVER_SCALE_REPETITIONS`` sets how many timed repetitions
each probed endpoint gets (default ``5``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCALE_DIR = Path(__file__).resolve().parent
DEFAULT_SIZES = "10,100,1000,10000"
DEFAULT_SEED = "207"
DEFAULT_REPETITIONS = "5"


def scale_enabled() -> bool:
    return os.environ.get("RECIPE_SERVER_SCALE", "").strip().lower() in {"1", "true", "yes"}


def parse_sizes() -> list[int]:
    raw = os.environ.get("RECIPE_SERVER_SCALE_SIZES", DEFAULT_SIZES)
    sizes: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value < 1:
            raise ValueError(f"RECIPE_SERVER_SCALE_SIZES entries must be positive integers, got {value}")
        if value not in sizes:
            sizes.append(value)
    if not sizes:
        raise ValueError(f"RECIPE_SERVER_SCALE_SIZES={raw!r} did not yield any sizes")
    return sizes


def parse_seed() -> int:
    return int(os.environ.get("RECIPE_SERVER_SCALE_SEED", DEFAULT_SEED).strip())


def parse_repetitions() -> int:
    repetitions = int(os.environ.get("RECIPE_SERVER_SCALE_REPETITIONS", DEFAULT_REPETITIONS).strip())
    if repetitions < 1:
        raise ValueError(f"RECIPE_SERVER_SCALE_REPETITIONS must be at least 1, got {repetitions}")
    return repetitions


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if scale_enabled():
        return
    skip_marker = pytest.mark.skip(reason="scale tests are opt-in and slow; set RECIPE_SERVER_SCALE=1 to run them (see README, 'Scale testing')")
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(SCALE_DIR):
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    """Where report.json/report.md are written (git-ignored)."""
    path = Path(os.environ.get("RECIPE_SERVER_SCALE_ARTIFACTS", REPO_ROOT / ".scale-artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path
