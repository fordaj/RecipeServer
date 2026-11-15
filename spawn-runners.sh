#!/usr/bin/env bash
# spawn-runners.sh — create the repository-scoped self-hosted runners.
#
# Usage:
#   ./spawn-runners.sh                # create the runners in .runner-spawner.json
#   ./spawn-runners.sh --dry-run      # print what would happen, change nothing
#   ./spawn-runners.sh <flags...>     # any additional runner-spawner create flags
#
# Sources scripts/env.sh to resolve RUNNER_SPAWNER_BIN (bundled via
# tools/runner-spawner/update.sh) and the logamuffin-backed log()
# helper, then runs `runner-spawner create --config .runner-spawner.json`
# from the repository root. Extra arguments are forwarded to the binary
# (runner-spawner reads RUNNER_SPAWNER_REPO as the *target* repository,
# which is why the env cascade exports RUNNER_SPAWNER_UPSTREAM_REPO for
# the release updater instead — do not set RUNNER_SPAWNER_REPO).
# The runners are repository-scoped to the origin remote (github.com/
# fordaj/RecipeServer); .runners/ is gitignored.
#
# Note: runner-spawner is macOS/Windows only, and requesting the
# registration token requires gh to be authenticated (or --token).

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
if [[ ! -f "$SCRIPT_DIR/scripts/env.sh" ]]; then
  printf 'spawn-runners.sh: error: env cascade not found: %s/scripts/env.sh\n' "$SCRIPT_DIR" >&2
  exit 1
fi
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/env.sh"

# Target-repo selectors for the runner-spawner binary are read from
# RUNNER_SPAWNER_REPO / RUNNER_SPAWNER_OWNER. Older env cascades exported
# RUNNER_SPAWNER_REPO for the release updater (fordaj/runner-spawner), and a
# stale value in the caller's shell overrides .runner-spawner.json and the
# git remote (that is what produced fordaj/fordaj/runner-spawner, HTTP 404).
# This script is scoped to this repo's config, so disarm them; an explicit
# --owner/--repo flag (forwarded via "$@") still wins.
unset RUNNER_SPAWNER_REPO RUNNER_SPAWNER_OWNER

cd "$SCRIPT_DIR"

if [[ -z "${RUNNER_SPAWNER_BIN:-}" ]]; then
  log ERROR "no runner-spawner binary found (run tools/runner-spawner/update.sh, or set RUNNER_SPAWNER_BIN)"
  exit 1
fi
[[ -x "$RUNNER_SPAWNER_BIN" ]] || {
  log ERROR "RUNNER_SPAWNER_BIN=$RUNNER_SPAWNER_BIN is not executable"
  exit 1
}
CONFIG="$SCRIPT_DIR/.runner-spawner.json"
[[ -f "$CONFIG" ]] || {
  log ERROR "runner config not found: $CONFIG"
  exit 1
}

log INFO "using runner-spawner: $RUNNER_SPAWNER_BIN"
log INFO "creating runners from $CONFIG (repo resolved by runner-spawner from .runner-spawner.json / git remote)"
"$RUNNER_SPAWNER_BIN" create --config "$CONFIG" "$@"
