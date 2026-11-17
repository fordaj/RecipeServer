#!/usr/bin/env bash
# update.sh — refresh bundled mkcert binaries from FiloSottile/mkcert releases.
#
# mkcert publishes raw executables (no archives, no checksums file), so this
# downloads each platform binary directly into
# tools/mkcert/<tag>/<platform>/ (platform is the bundled <os>-<arch> layout:
# macos/linux/windows + x86_64/arm64, so darwin-amd64 -> macos-x86_64, etc.)
# and deletes old version folders. Old v*/ folders are deleted only after the
# new version is fully staged, so a failed download leaves the previous
# bundle intact.
#
# The upstream LICENSE is fetched from the release tag and kept next to each
# binary; mkcert ships no checksums, so binaries are verified by size and by
# running `mkcert -version` on the host platform.
#
# Usage:
#   tools/mkcert/update.sh              # download latest, replace old versions
#   tools/mkcert/update.sh --dry-run    # resolve tag + list assets, change nothing
#   tools/mkcert/update.sh --help       # usage
#
# Prerequisites: gh (https://cli.github.com/) and curl. The script resolves
# its own directory, so it can be run from anywhere. Logging uses
# log <level> <message> from scripts/entry.sh (logamuffin, with printf fallback).
#
# Layout after a successful run (current pin v1.4.4):
#   tools/mkcert/
#     update.sh
#     v1.4.4/
#       macos-arm64/mkcert
#       macos-x86_64/mkcert
#       linux-arm64/mkcert
#       linux-x86_64/mkcert
#       windows-arm64/mkcert.exe
#       windows-x86_64/mkcert.exe
#
# Env:
#   MKCERT_REPO  Repository slug (default: FiloSottile/mkcert)
#   MKCERT_TAG   Pinned tag (default: latest release)

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT_FOR_ENV=$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)
if [[ ! -f "$REPO_ROOT_FOR_ENV/scripts/entry.sh" ]]; then
    printf 'update.sh: error: entry point not found: %s/scripts/entry.sh\n' "$REPO_ROOT_FOR_ENV" >&2
    exit 1
fi
# shellcheck disable=SC1091
. "$REPO_ROOT_FOR_ENV/scripts/entry.sh"

DRY_RUN=0
TAG="${MKCERT_TAG:-}"
REPO="${MKCERT_REPO:-FiloSottile/mkcert}"

# Assets to install, mapped to their bundled platform directory.
PLATFORMS=(
    "darwin-amd64:macos-x86_64"
    "darwin-arm64:macos-arm64"
    "linux-amd64:linux-x86_64"
    "linux-arm64:linux-arm64"
    "windows-amd64:windows-x86_64"
    "windows-arm64:windows-arm64"
)

usage() {
    cat <<'EOF'
Usage: tools/mkcert/update.sh [--dry-run] [--tag TAG] [--repo REPO]

Download the latest mkcert release from GitHub via gh and install each
platform binary into tools/mkcert/<tag>/<platform>/ (platform is the
bundled <os>-<arch> layout, e.g. darwin-amd64 -> macos-x86_64), and delete
old version folders. Only the mkcert binary and the upstream LICENSE are
kept.

Flags:
  --dry-run, -n   Resolve tag + list planned downloads, change nothing.
  --tag TAG       Pin a specific release tag (default: latest release).
  --repo REPO     Repository slug (default: FiloSottile/mkcert).
  --help, -h      Show this help.

Env:
  MKCERT_REPO  Repository slug (overridden by --repo).
  MKCERT_TAG   Pinned tag (overridden by --tag).
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
    --tag)
        [[ $# -ge 2 ]] || {
            log ERROR "--tag requires a value"
            usage >&2
            exit 2
        }
        TAG="$2"
        shift 2
        ;;
    --tag=*)
        TAG="${1#--tag=}"
        shift
        ;;
    --repo)
        [[ $# -ge 2 ]] || {
            log ERROR "--repo requires a value"
            usage >&2
            exit 2
        }
        REPO="$2"
        shift 2
        ;;
    --repo=*)
        REPO="${1#--repo=}"
        shift
        ;;
    *)
        log ERROR "unknown argument: $1"
        usage >&2
        exit 2
        ;;
    esac
done

[[ -n "$REPO" ]] || {
    log ERROR "repository must not be empty"
    exit 2
}

die() {
    log ERROR "$*" || true
    exit 1
}
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

need_cmd gh
need_cmd curl

TOOL_ROOT="$SCRIPT_DIR"
[[ -d "$TOOL_ROOT" ]] || die "mkcert bundle directory not found: $TOOL_ROOT"
log INFO "mkcert bundle directory: $TOOL_ROOT"
log INFO "repository: $REPO"

if [[ -z "$TAG" ]]; then
    TAG="$(gh release view --repo "$REPO" --json tagName -q .tagName)" ||
        die "could not determine latest release from $REPO (is gh authenticated and the repo visible?)"
fi
[[ -n "$TAG" ]] || die "could not determine release tag from $REPO"
if ! [[ "$TAG" =~ ^v[0-9]+(\.[0-9]+)+$ ]]; then
    die "invalid tag '$TAG' (expected vX.Y.Z...)"
fi
log INFO "release tag: $TAG"

asset_name() {
    # <tag without leading v>-<platform-asset>[.exe]
    local asset_platform="$1"
    local version="${TAG#v}"
    case "$asset_platform" in
    windows-*) printf 'mkcert-v%s-%s.exe' "$version" "$asset_platform" ;;
    *) printf 'mkcert-v%s-%s' "$version" "$asset_platform" ;;
    esac
}

if [[ "$DRY_RUN" -eq 1 ]]; then
    log INFO "DRY RUN: no download or deletion will happen"
    log INFO "release $TAG assets:"
    assets_list=$(gh release view "$TAG" --repo "$REPO" --json assets -q '.assets[].name' ||
        die "could not list assets for $TAG in $REPO")
    [[ -n "$assets_list" ]] || die "no assets found for $TAG in $REPO"
    for pair in "${PLATFORMS[@]}"; do
        asset_platform="${pair%%:*}"
        target="${pair##*:}"
        asset="$(asset_name "$asset_platform")"
        if grep -Fxq "$asset" <<<"$assets_list"; then
            log INFO "  $asset -> $TAG/$target"
        else
            log INFO "  missing: $asset (would fail)"
        fi
    done
    shopt -s nullglob
    old_found=0
    for dir in "$TOOL_ROOT"/v*/; do
        [[ -d "$dir" ]] || continue
        dir_name="$(basename "$dir")"
        if [[ "$dir_name" != "$TAG" ]]; then
            log INFO "would remove old $dir_name"
            old_found=1
        fi
    done
    if [[ "$old_found" -eq 0 ]]; then
        log INFO "no old version folders to remove"
    fi
    log INFO "dry run complete: would update $TOOL_ROOT/$TAG"
    exit 0
fi

# --- Real update: download to a temp dir, stage the bundle, then swap. ---
TMP_DIR=""
STAGE_DIR=""
cleanup() {
    if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
        rm -rf -- "$TMP_DIR"
    fi
    if [[ -n "${STAGE_DIR:-}" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "$STAGE_DIR"
    fi
}
trap cleanup EXIT

TMP_DIR="$(mktemp -d)"
STAGE_DIR="$(mktemp -d "$TOOL_ROOT/.tmp.XXXXXX")"

licenses_note=0
for pair in "${PLATFORMS[@]}"; do
    asset_platform="${pair%%:*}"
    target="${pair##*:}"
    asset="$(asset_name "$asset_platform")"
    log INFO "downloading $asset..."
    if ! gh release download "$TAG" --repo "$REPO" --dir "$TMP_DIR" --pattern "$asset" --clobber; then
        die "could not download $asset from $REPO $TAG"
    fi
    mkdir -p "$STAGE_DIR/$target"
    if [[ "$target" == windows-* ]]; then
        mv "$TMP_DIR/$asset" "$STAGE_DIR/$target/mkcert.exe"
    else
        mv "$TMP_DIR/$asset" "$STAGE_DIR/$target/mkcert"
        chmod +x "$STAGE_DIR/$target/mkcert"
    fi
    [[ -s "$STAGE_DIR/$target"/mkcert* ]] || die "installed binary is empty: $STAGE_DIR/$target/mkcert"
    log INFO "installed $target (from $asset)"
done

# The mkcert release ships no checksums and no LICENSE asset; fetch the
# license from the tag so each platform directory carries it.
if license="$(curl -fsSL "https://raw.githubusercontent.com/${REPO}/${TAG}/LICENSE")"; then
    for pair in "${PLATFORMS[@]}"; do
        target="${pair##*:}"
        printf '%s\n' "$license" >"$STAGE_DIR/$target/LICENSE"
    done
    log INFO "fetched LICENSE from $REPO at $TAG"
else
    licenses_note=1
    log WARNING "could not fetch LICENSE from $REPO at $TAG; platform directories will have no LICENSE file"
fi

TAG_DIR="$TOOL_ROOT/$TAG"
rm -rf -- "$TAG_DIR"
mv "$STAGE_DIR" "$TAG_DIR"
STAGE_DIR=""

for dir in "$TOOL_ROOT"/v*/; do
    [[ -d "$dir" ]] || continue
    dir_name="$(basename "$dir")"
    if [[ "$dir_name" != "$TAG" ]]; then
        log INFO "removing old $dir_name"
        rm -rf -- "$dir"
    fi
done

if [[ "$licenses_note" -ne 0 ]]; then
    log WARNING "note: LICENSE files were not installed; fetch them manually if required"
fi

# Best-effort host verification: run the bundled binary for this machine.
host_os_raw="$(uname -s | tr '[:upper:]' '[:lower:]')"
host_arch_raw="$(uname -m | tr '[:upper:]' '[:lower:]')"
case "$host_os_raw" in
darwin*) host_os="macos" ;;
linux*) host_os="linux" ;;
msys* | mingw* | cygwin* | windows* | win*) host_os="windows" ;;
*) host_os="$host_os_raw" ;;
esac
case "$host_arch_raw" in
x86_64 | amd64) host_arch="x86_64" ;;
arm64 | aarch64) host_arch="arm64" ;;
*) host_arch="$host_arch_raw" ;;
esac
host_platform="$host_os-$host_arch"
host_bin=""
for cand in "$TAG_DIR/$host_platform/mkcert" "$TAG_DIR/$host_platform/mkcert.exe"; do
    if [[ -x "$cand" ]]; then
        host_bin="$cand"
    fi
done
if [[ -n "$host_bin" ]]; then
    if "$host_bin" -version >/dev/null 2>&1; then
        log INFO "host binary $host_platform runs (-version exited 0)"
    else
        log WARNING "host binary $host_platform failed to run (-version exited non-zero)"
    fi
else
    log WARNING "host platform $host_platform not in bundle; skipped host check"
fi

log INFO "done: $TAG_DIR now contains:"
for dir in "$TAG_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    log INFO "  $(basename "$dir")"
done
