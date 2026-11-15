#!/usr/bin/env bash
# scripts/format.sh — run formattington with logging via logamuffin.
#
# Usage:
#   ./scripts/format.sh [--check] [...]
#
# Forwards all arguments to `uv run formattington <args> all
# --config .formattington.json` after sourcing scripts/entry.sh for the
# logamuffin-backed log() helper. Runs from the repository root so the
# config path resolves regardless of the caller's directory.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
if [[ ! -f "$SCRIPT_DIR/scripts/entry.sh" ]]; then
  printf 'scripts/format.sh: error: env cascade not found: %s/scripts/entry.sh\n' "$SCRIPT_DIR" >&2
  exit 1
fi
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/entry.sh"

cd "$SCRIPT_DIR"
log INFO "running formattington $* all --config .formattington.json"
uv run formattington "$@" all --config .formattington.json
log INFO "format complete"
