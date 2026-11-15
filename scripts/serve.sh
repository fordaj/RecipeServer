#!/usr/bin/env bash
# scripts/serve.sh — start the local recipe server.
#
# Usage:
#   ./scripts/serve.sh
#
# Sources scripts/entry.sh for the logamuffin-backed log() helper, then
# starts the server from the repository root with:
#   uv run python -m recipeserver

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
if [[ ! -f "$SCRIPT_DIR/scripts/entry.sh" ]]; then
  printf 'scripts/serve.sh: error: env cascade not found: %s/scripts/entry.sh\n' "$SCRIPT_DIR" >&2
  exit 1
fi
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/entry.sh"

cd "$SCRIPT_DIR"
log INFO "starting recipeserver..."
exec uv run python -m recipeserver
