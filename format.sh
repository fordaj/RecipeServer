#!/usr/bin/env bash
set -euo pipefail
uv run formattington "$@" all --config .formattington.json
