#!/usr/bin/env bash
set -euo pipefail

# Formattington's `all` runs every registered formatter concurrently
# (ThreadPoolExecutor) with per-formatter file discovery. This repo has
# no C/C++ or PowerShell files, and `all` still invokes clang-format and
# powershell (requiring clang-format, pwsh, and PSScriptAnalyzer on
# every machine), so we reuse the same parallel engine for the
# formatters that match this repo's files: black (.py), shfmt (bash),
# prettier (css, js, html, .md, .yml), and taplo (.toml). SVG files are
# not covered by Prettier discovery, so they are formatted explicitly.
exec uv run python - "$@" <<'PY'
import argparse
import glob
import sys

from formattington.cli import _run_parallel
from formattington.prettier import prettier

parser = argparse.ArgumentParser(prog="format.sh")
parser.add_argument("--check", action="store_true")
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--verbose", action="store_true")
parser.add_argument("--version", action="store_true")
args, unknown = parser.parse_known_args(sys.argv[1:])

if args.version and not (args.check or args.dry_run or args.verbose or unknown):
    print("format.sh (formattington)")
    raise SystemExit(0)

if unknown:
    parser.error(f"unrecognized arguments: {' '.join(unknown)}")

names = ["shfmt", "black", "prettier", "taplo"]
exit_code = _run_parallel(
    names,
    check=args.check,
    dry_run=args.dry_run,
    args=[],
    verbose=args.verbose,
)

svg_files = sorted(glob.glob("src/recipeserver/assets/*.svg"))
if svg_files:
    svg_result = prettier(
        check=args.check,
        dry_run=args.dry_run,
        args=["--parser", "html", *svg_files],
        verbose=args.verbose,
    )
    if exit_code == 0:
        exit_code = svg_result

raise SystemExit(exit_code)
PY
