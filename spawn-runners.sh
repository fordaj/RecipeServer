#!/usr/bin/env bash
# spawn-runners.sh — spawn the GitHub Actions runners for this repo.
#
# Usage:
#   ./spawn-runners.sh
#
# For now this only reports the bundled runner-spawner binary's
# version; the actual spawn logic will be added later. Sources
# scripts/env.sh for the runner-spawner binary (RUNNER_SPAWNER_BIN,
# resolved from tools/runner-spawner/v*/<platform>/) and the
# logamuffin-backed log() helper. Runs from the repository root so
# paths resolve regardless of the caller's directory.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
if [[ ! -f "$SCRIPT_DIR/scripts/env.sh" ]]; then
  printf 'spawn-runners.sh: error: env cascade not found: %s/scripts/env.sh\n' "$SCRIPT_DIR" >&2
  exit 1
fi
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/env.sh"

cd "$SCRIPT_DIR"

if [[ -z "${RUNNER_SPAWNER_BIN:-}" ]]; then
  log ERROR "no runner-spawner binary found (run tools/runner-spawner/update.sh, or set RUNNER_SPAWNER_BIN)"
  exit 1
fi
[[ -x "$RUNNER_SPAWNER_BIN" ]] || {
  log ERROR "RUNNER_SPAWNER_BIN=$RUNNER_SPAWNER_BIN is not executable"
  exit 1
}
log INFO "using runner-spawner: $RUNNER_SPAWNER_BIN"
"$RUNNER_SPAWNER_BIN" --version
log INFO "spawn-runners complete (nothing spawned yet)"
