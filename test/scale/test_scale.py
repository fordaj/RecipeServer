"""Scale/performance measurements for RecipeServer.

Opt-in only — skipped unless ``RECIPE_SERVER_SCALE=1`` is set:

    RECIPE_SERVER_SCALE=1 uv run pytest test/scale -s

Builds a mock recipe library at each configured size (default
``10,100,1000,10000``, override with ``RECIPE_SERVER_SCALE_SIZES=10,100``),
times the build and the HTTP endpoints, and writes ``.scale-artifacts/``
artifacts (``report.json`` machine-readable, ``report.md`` human-readable).

Assertions here check invariants only (page counts, card counts, 2xx
responses, a parseable index). There are deliberately no time budgets; see
the issue's "Out of scope".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from test.scale import harness, metrics, mock_library
from test.scale.conftest import parse_repetitions, parse_seed, parse_sizes

SIZES = parse_sizes()
SEED = parse_seed()
REPETITIONS = parse_repetitions()

FIRST_RECIPE_MARKDOWN = "mock-000001/recipe.md"
FIRST_RECIPE_HTML = "/mock-000001/recipe.html"


def _by_size(results: list[dict], size: int) -> dict:
    for entry in results:
        if entry["size"] == size:
            return entry
    raise KeyError(f"no results recorded for size {size}")


def _probe_endpoints(url: str, repetitions: int) -> dict[str, dict]:
    targets = {
        "/": f"{url}/",
        FIRST_RECIPE_HTML: f"{url}{FIRST_RECIPE_HTML}",
        "/health": f"{url}/health",
        "/api/metadata-options": f"{url}/api/metadata-options",
        "/api/recipe-folders": f"{url}/api/recipe-folders",
        "/api/shopping-list": f"{url}/api/shopping-list?path={FIRST_RECIPE_MARKDOWN}",
    }
    results = {}
    for name, target in targets.items():
        try:
            results[name] = metrics.time_request(target, repetitions)
        except Exception as exc:  # record failures so the invariant tests can report them
            results[name] = {
                "url": target,
                "status": getattr(exc, "code", None),
                "repetitions": repetitions,
                "transferBytes": 0,
                "p50": 0.0,
                "p95": 0.0,
                "max": 0.0,
                "error": repr(exc),
            }
    return results


def _measure_size(tmp_root: Path, size: int, seed: int, repetitions: int) -> dict:
    entry: dict = {"size": size, "seed": seed}
    source_dir = tmp_root / "source"
    site_dir = tmp_root / "site"

    try:
        library = mock_library.build_mock_library(source_dir, size, seed=seed)
    except Exception as exc:
        entry["error"] = f"mock library generation failed: {exc!r}"
        return entry
    entry["generatorSeconds"] = library.generator_seconds

    scale_server = None
    rss_before_build = metrics.rss_bytes()
    try:
        with harness.override_site_directory(site_dir):
            build = harness.build_site(library.root, site_dir)
            rss_after_build = metrics.rss_bytes()
            scale_server = harness.start_server(build)
            try:
                rss_after_serving = metrics.rss_bytes()
                entry["requests"] = _probe_endpoints(scale_server.url, repetitions)
            finally:
                harness.stop_server(scale_server)
    except Exception as exc:
        harness.stop_server(scale_server)
        entry["error"] = f"measure run failed: {exc!r}"
        return entry

    index_bytes = (site_dir / "index.html").read_bytes()
    entry["build"] = {
        "wallSeconds": build.wall_seconds,
        "workerCount": build.worker_count,
        "phases": dict(build.core.last_regen_timings),
    }
    entry["output"] = {
        "recipePages": len(list(site_dir.glob("mock-*/recipe.html"))),
        "indexHtmlBytes": len(index_bytes),
        "siteBytes": metrics.dir_size_bytes(site_dir),
        "indexCards": metrics.index_card_count(index_bytes),
    }
    entry["memory"] = {
        "rssBeforeBuild": rss_before_build,
        "rssAfterBuild": rss_after_build,
        "rssAfterServing": rss_after_serving,
    }
    entry["startupSeconds"] = scale_server.startup_seconds
    entry["siteDir"] = str(site_dir)
    return entry


def _print_console_table(results: list[dict]) -> None:
    print("\nRecipeServer scale results (RECIPE_SERVER_SCALE=1)")
    print(f"{'recipes':>8} {'build':>9} {'index.html':>12} {'site':>12} {'cards':>8} {'/':>9} {'metadata p50':>13}")
    for entry in results:
        if entry.get("error"):
            print(f"{entry['size']:>8} ERROR: {entry['error']}")
            continue
        page_size = metrics._format_bytes(entry["output"]["indexHtmlBytes"])
        site_size = metrics._format_bytes(entry["output"]["siteBytes"])
        root = entry["requests"].get("/", {})
        metadata_options = entry["requests"].get("/api/metadata-options", {})
        print(
            f"{entry['size']:>8} {entry['build']['wallSeconds']:>8.2f}s {page_size:>12} {site_size:>12} "
            f"{entry['output']['indexCards']:>8} {root.get('p50', 0.0):>8.3f}s {metadata_options.get('p50', 0.0):>12.3f}s"
        )


@pytest.fixture(scope="module")
def scale_run(tmp_path_factory, artifacts_dir):
    results = []
    for size in SIZES:
        results.append(_measure_size(tmp_path_factory.mktemp(f"scale-{size}"), size, SEED, REPETITIONS))

    worker_count = next((entry["build"]["workerCount"] for entry in results if not entry.get("error")), None)
    report = metrics.write_reports(artifacts_dir, seed=SEED, repetitions=REPETITIONS, worker_count=worker_count, results=results)

    _print_console_table(results)
    print(f"Artifacts written to {artifacts_dir}/report.json and report.md")
    baseline = report.get("baselineDeltaPercent", {})
    if baseline:
        print("Delta vs. previous report.json (percent):")
        for size_key, deltas in baseline.items():
            formatted = ", ".join(f"{key} {value:+.1f}%" for key, value in deltas.items())
            print(f"  {int(size_key):>8} recipes: {formatted}")
    return results


@pytest.mark.parametrize("size", SIZES)
def test_expected_recipe_pages_built(scale_run, size):
    entry = _by_size(scale_run, size)
    assert not entry.get("error"), f"scale run failed for {size} recipes: {entry.get('error')}"
    assert entry["output"]["recipePages"] == size


@pytest.mark.parametrize("size", SIZES)
def test_index_contains_all_cards(scale_run, size):
    entry = _by_size(scale_run, size)
    assert not entry.get("error"), f"scale run failed for {size} recipes: {entry.get('error')}"
    assert entry["output"]["indexCards"] == size


@pytest.mark.parametrize("size", SIZES)
def test_index_parses(scale_run, size):
    entry = _by_size(scale_run, size)
    assert not entry.get("error"), f"scale run failed for {size} recipes: {entry.get('error')}"

    index_html = Path(entry["siteDir"]) / "index.html"
    soup = BeautifulSoup(index_html.read_text(encoding="utf-8"), "html.parser")
    cards = soup.find_all(attrs={"data-testid": "recipe-item"})
    assert len(cards) == size
    assert soup.title is not None


@pytest.mark.parametrize("size", SIZES)
def test_probed_endpoints_return_2xx(scale_run, size):
    entry = _by_size(scale_run, size)
    assert not entry.get("error"), f"scale run failed for {size} recipes: {entry.get('error')}"
    failures = {name: stats for name, stats in entry["requests"].items() if not (stats.get("status") or 0) // 100 == 2}
    assert not failures, f"endpoints did not return 2xx at {size} recipes: {failures}"
