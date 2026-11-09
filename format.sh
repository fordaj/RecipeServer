#!/usr/bin/env bash
set -euo pipefail
uv run formattington python src test "$@"
