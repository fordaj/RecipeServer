"""Metrics collection and report writers for the scale tests.

Collects wall-clock timings, process RSS, on-disk output sizes, and
per-endpoint latency percentiles, then renders two artifacts into the
artifacts directory (``.scale-artifacts/`` by default):

- ``report.json`` — machine-readable; includes platform, interpreter,
  worker count, git SHA, sizes, and seed so two runs on the same machine
  can be compared.
- ``report.md`` — human-readable tables, including the per-doubling growth
  factors between consecutive sizes (the 100 → 10,000 slope is the
  interesting output) and, when a previous ``report.json`` exists in the
  artifacts directory, a delta section against that baseline.

No time budgets or thresholds are enforced anywhere here; this is an
analysis harness, not a correctness gate.
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import psutil

CARD_PATTERN = re.compile(rb'data-testid="recipe-item"')
INDEX_HTML_NAME = "index.html"
REPORT_JSON_NAME = "report.json"
REPORT_MD_NAME = "report.md"


def rss_bytes() -> int:
    return psutil.Process().memory_info().rss


def dir_size_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def index_card_count(index_bytes: bytes) -> int:
    return len(CARD_PATTERN.findall(index_bytes))


def _nearest_rank(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(percentile / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def percentile_stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "p50": _nearest_rank(ordered, 50),
        "p95": _nearest_rank(ordered, 95),
        "max": ordered[-1] if ordered else 0.0,
    }


def time_request(url: str, repetitions: int) -> dict:
    """Time ``GET url`` sequentially and return percentiles plus transfer size."""
    samples: list[float] = []
    body_bytes = 0
    status = None
    for _ in range(repetitions):
        start = time.perf_counter()
        with urlopen(url, timeout=30.0) as response:
            body = response.read()
            status = response.status
        samples.append(time.perf_counter() - start)
        body_bytes = len(body)

    stats = percentile_stats(samples)
    return {
        "url": url,
        "status": status,
        "repetitions": repetitions,
        "transferBytes": body_bytes,
        **stats,
    }


def git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def machine_metadata() -> dict:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpuCount": os.process_cpu_count(),
        "pythonVersion": sys.version.split()[0],
        "pythonImplementation": platform.python_implementation(),
        "gitSha": git_sha(),
    }


def load_previous_report(artifacts_dir: Path) -> dict | None:
    path = artifacts_dir / REPORT_JSON_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError:
        return None


def _baseline_deltas(previous: dict | None, results: list[dict]) -> dict[str, dict[str, float]]:
    """Percent change vs. the previous report, keyed by size, for headline metrics."""
    if not previous:
        return {}
    previous_by_size = {entry.get("size"): entry for entry in previous.get("results", [])}

    def _percent_change(old: float | None, new: float | None) -> float | None:
        if old is None or new is None or old == 0:
            return None
        return (new - old) / old * 100

    deltas: dict[str, dict[str, float]] = {}
    for entry in results:
        prior = previous_by_size.get(entry.get("size"))
        if prior is None or entry.get("error") or prior.get("error"):
            continue
        size_key = str(entry["size"])
        entry_deltas: dict[str, float | None] = {
            "buildWallSeconds": _percent_change(prior.get("build", {}).get("wallSeconds"), entry.get("build", {}).get("wallSeconds")),
            "indexHtmlBytes": _percent_change(prior.get("output", {}).get("indexHtmlBytes"), entry.get("output", {}).get("indexHtmlBytes")),
            "siteBytes": _percent_change(prior.get("output", {}).get("siteBytes"), entry.get("output", {}).get("siteBytes")),
            "metadataOptionsP50": _percent_change(
                (prior.get("requests", {}).get("/api/metadata-options") or {}).get("p50"),
                (entry.get("requests", {}).get("/api/metadata-options") or {}).get("p50"),
            ),
        }
        filtered = {key: value for key, value in entry_deltas.items() if value is not None}
        if filtered:
            deltas[size_key] = filtered
    return deltas


def _growth_factors(results: list[dict]) -> list[dict]:
    """Per-doubling growth between consecutive measured sizes."""

    def _per_doubling(old: float, new: float, old_size: int, new_size: int) -> float | None:
        if not old or old <= 0 or new <= 0:
            return None
        doublings = math.log2(new_size / old_size)
        return (new / old) ** (1 / doublings) if doublings else None

    growth = []
    ordered = [entry for entry in sorted(results, key=lambda item: item.get("size", 0)) if not entry.get("error")]
    for before, after in zip(ordered, ordered[1:]):
        before_size, after_size = before["size"], after["size"]
        growth.append(
            {
                "from": before_size,
                "to": after_size,
                "doublings": math.log2(after_size / before_size),
                "buildWallSeconds": _per_doubling(before["build"]["wallSeconds"], after["build"]["wallSeconds"], before_size, after_size),
                "recipeConversionSeconds": _per_doubling(
                    before["build"].get("phases", {}).get("recipe_conversion", 0),
                    after["build"].get("phases", {}).get("recipe_conversion", 0),
                    before_size,
                    after_size,
                ),
                "indexBuildSeconds": _per_doubling(
                    before["build"].get("phases", {}).get("index_build", 0),
                    after["build"].get("phases", {}).get("index_build", 0),
                    before_size,
                    after_size,
                ),
                "indexHtmlBytes": _per_doubling(before["output"]["indexHtmlBytes"], after["output"]["indexHtmlBytes"], before_size, after_size),
                "siteBytes": _per_doubling(before["output"]["siteBytes"], after["output"]["siteBytes"], before_size, after_size),
                "metadataOptionsP50": _per_doubling(
                    (before.get("requests", {}).get("/api/metadata-options") or {}).get("p50", 0),
                    (after.get("requests", {}).get("/api/metadata-options") or {}).get("p50", 0),
                    before_size,
                    after_size,
                ),
            }
        )
    return growth


def _format_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _format_seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}s"


def _format_percent(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def render_markdown_report(report: dict) -> str:
    lines: list[str] = [
        "# RecipeServer scale report",
        "",
        f"- Generated: {report['generatedAt']}",
        f"- Git SHA: `{report.get('gitSha') or 'unknown'}`",
        f"- Platform: {report['platform']} ({report.get('machine')}, {report.get('cpuCount')} CPUs)",
        f"- Python: {report['pythonVersion']} ({report.get('pythonImplementation')})",
        f"- Seed: {report['seed']} · Worker count: {report.get('workerCount')} · Repetitions per request: {report.get('repetitions')}",
        "",
        "> Performance analysis only — no time budgets are enforced. Reproduce with:",
        ">",
        "> ```bash",
        "> RECIPE_SERVER_SCALE=1 uv run pytest test/scale -s",
        "> ```",
        "",
    ]

    for entry in report["results"]:
        size = entry["size"]
        lines.append(f"## {size:,} recipes")
        lines.append("")
        if entry.get("error"):
            lines.append(f"**Build failed:** `{entry['error']}`")
            lines.append("")
            continue

        build = entry["build"]
        output = entry["output"]
        memory = entry["memory"]
        lines.append(f"- Generator wall time (not measured): {_format_seconds(entry.get('generatorSeconds'))}")
        lines.append(f"- Build wall time: {_format_seconds(build['wallSeconds'])} (workers: {build.get('workerCount')})")
        phases = build.get("phases", {})
        lines.append(
            f"  - assets_copy: {_format_seconds(phases.get('assets_copy'))} · recipe_conversion: {_format_seconds(phases.get('recipe_conversion'))} · index_build: {_format_seconds(phases.get('index_build'))}"
        )
        lines.append(
            f"- Output: {output['recipePages']:,} pages · index.html {_format_bytes(output['indexHtmlBytes'])} · site total {_format_bytes(output['siteBytes'])} · index cards {output['indexCards']:,}"
        )
        lines.append(
            f"- RSS: before build {_format_bytes(memory['rssBeforeBuild'])} → after build {_format_bytes(memory['rssAfterBuild'])} → after serving {_format_bytes(memory['rssAfterServing'])}"
        )
        lines.append(f"- Server start → first /health: {_format_seconds(entry.get('startupSeconds'))}")
        lines.append("")
        lines.append("| Endpoint | Status | p50 | p95 | max | Transfer |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for endpoint, stats in entry.get("requests", {}).items():
            lines.append(
                f"| `{endpoint}` | {stats.get('status')} | {_format_seconds(stats.get('p50'))} | {_format_seconds(stats.get('p95'))} | {_format_seconds(stats.get('max'))} | {_format_bytes(stats.get('transferBytes'))} |"
            )
        lines.append("")

    growth = report.get("growth", [])
    if growth:
        lines.append("## Growth per doubling")
        lines.append("")
        lines.append("Values above 1.0 mean superlinear growth; ~2.0 means linear scaling per doubling for totals.")
        lines.append("")
        lines.append("| From → To | Build wall | Conversion | Index build | index.html | Site size | metadata-options p50 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for row in growth:

            def _fmt_factor(value):
                return "—" if value is None else f"{value:.2f}×"

            lines.append(
                f"| {row['from']:,} → {row['to']:,} | {_fmt_factor(row['buildWallSeconds'])} | {_fmt_factor(row['recipeConversionSeconds'])} | {_fmt_factor(row['indexBuildSeconds'])} | {_fmt_factor(row['indexHtmlBytes'])} | {_fmt_factor(row['siteBytes'])} | {_fmt_factor(row['metadataOptionsP50'])} |"
            )
        lines.append("")

    deltas = report.get("baselineDeltaPercent", {})
    if deltas:
        lines.append("## Delta vs. previous report")
        lines.append("")
        lines.append("| Size | Build wall | index.html | Site size | metadata-options p50 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for size_key, entry_deltas in deltas.items():
            lines.append(
                f"| {int(size_key):,} | {_format_percent(entry_deltas.get('buildWallSeconds'))} | {_format_percent(entry_deltas.get('indexHtmlBytes'))} | {_format_percent(entry_deltas.get('siteBytes'))} | {_format_percent(entry_deltas.get('metadataOptionsP50'))} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_reports(artifacts_dir: Path, *, seed: int, repetitions: int, worker_count: int | None, results: list[dict]) -> dict:
    previous = load_previous_report(artifacts_dir)

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "repetitions": repetitions,
        "workerCount": worker_count,
        **machine_metadata(),
        "sizes": [entry["size"] for entry in results],
        "results": results,
    }
    report["growth"] = _growth_factors(results)
    report["baselineDeltaPercent"] = _baseline_deltas(previous, results)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / REPORT_JSON_NAME).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (artifacts_dir / REPORT_MD_NAME).write_text(render_markdown_report(report), encoding="utf-8")
    return report
