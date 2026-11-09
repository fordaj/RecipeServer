#!/usr/bin/env bash
# release.bash — compute the next version with versioner (dogfooding),
# tag HEAD, push the tag, and create a GitHub release for version tracking.
#
# Unlike the Versioner and Logamuffin tools, RecipeServer ships no bundled
# binaries or archives for GitHub Releases: releases are for version
# tracking only (no .exe uploads, no zip archives). A release is created by
# tagging HEAD with the computed version and publishing a GitHub release
# with generated notes (`gh release create ... --generate-notes`).
#
# Usage:
#   ./release.bash           # compute version, tag, push, gh release create
#   ./release.bash --dry-run # compute + verify only, touch nothing remote
#
# Prerequisites: git, gh authenticated via `gh auth login` (real release),
# and bundled versioner/logamuffin binaries (refresh with
# tools/versioner/update.bash and tools/logamuffin/update.bash; select with
# scripts/env.sh). Logging uses log <level> <message> from scripts/env.sh
# (logamuffin, with printf fallback until tools/logamuffin is populated).
# Working tree must be clean; HEAD should be pushed.

set -euo pipefail

# Logging via logamuffin (log <level> <message> from scripts/env.sh,
# with printf fallback until tools/logamuffin is populated). Source the
# env cascade first so every later message goes through log().
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
if [[ ! -f "$SCRIPT_DIR/scripts/env.sh" ]]; then
	printf 'release.bash: error: env cascade not found: %s/scripts/env.sh\n' "$SCRIPT_DIR" >&2
	exit 1
fi
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/env.sh"

DRY_RUN=0

usage() {
	cat <<'EOF'
Usage: ./release.bash [--dry-run]

Compute the next VERSION/TAG with versioner itself (dogfooding, bundled
binary selected via scripts/env.sh), create an annotated tag, push it,
and create a GitHub release with generated notes (version tracking only,
no assets).

Flags:
  --dry-run, -n   Compute + verify version, but do not tag/push/release.
  --help, -h      Show this help.

Env:
  VERSIONER_BIN   Path to versioner (default: via scripts/env.sh, then PATH).
  LOGAMUFFIN_BIN  Path to logamuffin for log() (default: via scripts/env.sh, then PATH).
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--dry-run | -n)
		DRY_RUN=1
		shift
		;;
	--help | -h)
		usage
		exit 0
		;;
	*)
		log ERROR "unknown argument: $1"
		usage >&2
		exit 2
		;;
	esac
done

die() {
	log ERROR "$*" || true
	exit 1
}
need_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

need_cmd git

if [[ "$DRY_RUN" -ne 1 ]]; then
	need_cmd gh
	if ! gh auth status >/dev/null 2>&1; then
		die "gh is not authenticated (run: gh auth login)"
	fi
fi

if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
	die "not inside a git repository"
fi
cd "$REPO_ROOT"
log INFO "repo: $REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
HEAD_SHORT="$(git rev-parse --short HEAD)"
log INFO "branch: $BRANCH  HEAD: $HEAD_SHORT"
if [[ "$DRY_RUN" -eq 1 ]]; then
	log INFO "DRY RUN: no tag/push/release will happen"
fi

# --- Precondition: clean working tree ---------------------------------
if [[ -n "$(git status --porcelain)" ]]; then
	if [[ "$DRY_RUN" -eq 1 ]]; then
		log WARNING "working tree is not clean (allowed in --dry-run)"
		git status --short | sed 's/^/release.bash:   /' >&2
	else
		die "working tree is not clean (commit or stash first):"$'\n'"$(git status --short)"
	fi
fi

# Best-effort fetch so remote tag-existence checks are current.
if ! git fetch origin --tags 2>/dev/null; then
	if [[ "$DRY_RUN" -eq 1 ]]; then
		log WARNING "git fetch origin --tags failed; remote tag check may be stale"
	else
		die "git fetch origin --tags failed"
	fi
fi

# --- Dogfooding: versioner/logamuffin via scripts/env.sh (sourced above)
# shellcheck disable=SC2154
if [[ -z "${VERSIONER_BIN:-}" ]]; then
	die "no versioner binary found (run tools/versioner/update.bash, or set VERSIONER_BIN)"
fi
[[ -x "$VERSIONER_BIN" ]] || die "VERSIONER_BIN=$VERSIONER_BIN is not executable"
log INFO "using versioner: $VERSIONER_BIN"
if [[ -n "${LOGAMUFFIN_BIN:-}" && -x "$LOGAMUFFIN_BIN" ]]; then
	log INFO "using logamuffin: $LOGAMUFFIN_BIN"
else
	log WARNING "logamuffin not found; falling back to printf logging (run tools/logamuffin/update.bash)"
fi
"$VERSIONER_BIN" --version | sed 's/^/release.bash:   /'

# --- Compute VERSION/TAG with versioner (dogfooding) ------------------
log INFO "computing version with versioner (dogfooding)..."
VERSION_OUT="$("$VERSIONER_BIN" --repo-dir "$REPO_ROOT" --quiet)"
log INFO "versioner output:"
printf '%s\n' "$VERSION_OUT" | sed 's/^/release.bash:   /'

VERSION="$(printf '%s\n' "$VERSION_OUT" | sed -n 's/^VERSION=//p' | tail -1)"
TAG="$(printf '%s\n' "$VERSION_OUT" | sed -n 's/^TAG=//p' | tail -1)"
[[ -n "$VERSION" ]] || die "could not parse VERSION from versioner output"
[[ -n "$TAG" ]] || die "could not parse TAG from versioner output"
if ! [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	die "computed tag looks invalid: '$TAG' (expected vX.Y.Z.W.V)"
fi
log INFO "VERSION=$VERSION  TAG=$TAG"

# --- Tag must not already exist ---------------------------------------
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
	die "tag $TAG already exists locally (make a new feat:/fix: commit to bump the version, then re-run)"
fi
if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
	die "tag $TAG already exists on origin (make a new feat:/fix: commit to bump the version, then re-run)"
fi

# --- Tag + GitHub release (version tracking only, no assets) -----------
if [[ "$DRY_RUN" -eq 1 ]]; then
	log INFO "DRY RUN: would run:"
	log INFO "  git tag -a $TAG -m \"recipeserver $TAG\""
	log INFO "  git push origin $TAG"
	log INFO "  gh release create $TAG --title \"recipeserver $TAG\" --generate-notes"
	log INFO "dry run complete: VERSION=$VERSION TAG=$TAG"
	exit 0
fi

log INFO "creating annotated tag $TAG..."
git tag -a "$TAG" -m "recipeserver $TAG"

log INFO "pushing tag $TAG..."
git push origin "$TAG"

if gh release view "$TAG" >/dev/null 2>&1; then
	die "GitHub release $TAG already exists (tag was pushed; add it manually with: gh release create $TAG --title \"recipeserver $TAG\" --generate-notes)"
fi

log INFO "creating GitHub release $TAG (version tracking only, no assets)..."
gh release create "$TAG" \
	--title "recipeserver $TAG" \
	--generate-notes

if REPO_SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" && [[ -n "$REPO_SLUG" ]]; then
	log INFO "release: https://github.com/$REPO_SLUG/releases/tag/$TAG"
else
	log INFO "release $TAG created (see GitHub Releases)"
fi
