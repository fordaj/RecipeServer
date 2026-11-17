#!/usr/bin/env bash
# update.sh — refresh bundled caddy binaries from caddyserver/caddy releases.
#
# Downloads the latest release's per-platform binaries via gh, verifies
# SHA256 checksums (caddy ships a checksums.txt with every release), extracts
# each binary into tools/caddy/<tag>/<platform>/ (platform is the bundled
# <os>-<arch> layout: macos/linux/windows + x86_64/arm64, so mac-amd64 ->
# macos-x86_64, etc.), and deletes old version folders. Old v*/ folders are
# deleted only after the new version is fully staged, so a failed download
# leaves the previous bundle intact.
#
# Only the caddy binary and the upstream LICENSE are kept; the release
# archives also carry a README, which is dropped.
#
# Usage:
#   tools/caddy/update.sh              # download latest, replace old versions
#   tools/caddy/update.sh --dry-run    # resolve tag + list assets, change nothing
#   tools/caddy/update.sh --help       # usage
#
# Prerequisites: gh (https://cli.github.com/), tar/unzip. The script resolves
# its own directory, so it can be run from anywhere. Logging uses
# log <level> <message> from scripts/entry.sh (logamuffin, with printf fallback).
#
# Layout after a successful run (current pin v2.11.9):
#   tools/caddy/
#     update.sh
#     v2.11.9/
#       macos-arm64/caddy
#       macos-x86_64/caddy
#       linux-arm64/caddy
#       linux-x86_64/caddy
#       windows-arm64/caddy.exe
#       windows-x86_64/caddy.exe
#
# Env:
#   CADDY_REPO  Repository slug (default: caddyserver/caddy)
#   CADDY_TAG   Pinned tag (default: latest release)

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
TAG="${CADDY_TAG:-}"
REPO="${CADDY_REPO:-caddyserver/caddy}"

usage() {
    cat <<'EOF'
Usage: tools/caddy/update.sh [--dry-run] [--tag TAG] [--repo REPO]

Download the latest caddy release from GitHub via gh, extract each
platform binary into tools/caddy/<tag>/<platform>/ (platform is the
bundled <os>-<arch> layout, e.g. mac-amd64 -> macos-x86_64), and delete
old version folders. Only the caddy binary and the upstream LICENSE are
kept.

Flags:
  --dry-run, -n   Resolve tag + list planned assets, change nothing.
  --tag TAG       Pin a specific release tag (default: latest release).
  --repo REPO     Repository slug (default: caddyserver/caddy).
  --help, -h      Show this help.

Env:
  CADDY_REPO  Repository slug (overridden by --repo).
  CADDY_TAG   Pinned tag (overridden by --tag).
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
need_cmd tar

TOOL_ROOT="$SCRIPT_DIR"
[[ -d "$TOOL_ROOT" ]] || die "caddy bundle directory not found: $TOOL_ROOT"
log INFO "caddy bundle directory: $TOOL_ROOT"
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

# parse_stem_to_platform <stem> sets PLATFORM (e.g. caddy_2.11.9_mac_amd64 ->
# macos-x86_64) or returns 1 for unknown values. caddy names its assets
# mac_<arch> / linux_<arch> / windows_<arch>.
parse_stem_to_platform() {
    local stem="$1"
    if [[ "$stem" =~ [-_](mac|darwin|macos|linux|windows)[-_](amd64|arm64|x86_64|x64)$ ]]; then
        case "${BASH_REMATCH[1]}" in
        mac | darwin | macos) PLATFORM="macos" ;;
        linux) PLATFORM="linux" ;;
        windows) PLATFORM="windows" ;;
        esac
        case "${BASH_REMATCH[2]}" in
        amd64 | x86_64 | x64) PLATFORM="${PLATFORM}-x86_64" ;;
        arm64) PLATFORM="${PLATFORM}-arm64" ;;
        esac
        return 0
    fi
    return 1
}

strip_archive_ext() {
    local name="$1"
    case "$name" in
    *.tar.gz) printf '%s' "${name%.tar.gz}" ;;
    *.zip) printf '%s' "${name%.zip}" ;;
    *) printf '%s' "$name" ;;
    esac
}

if [[ "$DRY_RUN" -eq 1 ]]; then
    log INFO "DRY RUN: no download, extraction, or deletion will happen"
    log INFO "release $TAG assets:"
    assets_list=$(gh release view "$TAG" --repo "$REPO" --json assets -q '.assets[].name' ||
        die "could not list assets for $TAG in $REPO")
    [[ -n "$assets_list" ]] || die "no assets found for $TAG in $REPO"
    asset_count=0
    while IFS= read -r asset; do
        [[ -n "$asset" ]] || continue
        case "$asset" in
        *.tar.gz | *.zip)
            stem="$(strip_archive_ext "$asset")"
            asset_count=$((asset_count + 1))
            if parse_stem_to_platform "$stem"; then
                log INFO "  $asset -> $TAG/$PLATFORM"
            else
                log INFO "  $asset -> unknown platform (would fail)"
            fi
            ;;
        *checksums*.txt)
            log INFO "  $asset (checksums)"
            ;;
        *)
            log INFO "  $asset (ignored)"
            ;;
        esac
    done <<<"$assets_list"
    ((asset_count > 0)) || die "no platform archives found for $TAG in $REPO"
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

log INFO "downloading $TAG assets from $REPO..."
gh release download "$TAG" --repo "$REPO" --dir "$TMP_DIR" --pattern '*.tar.gz' --pattern '*.zip' --pattern '*checksums*.txt' --clobber

shopt -s nullglob
archives=()
for archive in "$TMP_DIR"/*.tar.gz "$TMP_DIR"/*.zip; do
    [[ -e "$archive" ]] || continue
    archives+=("$archive")
done
((${#archives[@]} > 0)) || die "no platform archives downloaded from $REPO $TAG"
log INFO "downloaded ${#archives[@]} platform archives"

checksums_file=""
for candidate in "$TMP_DIR"/*checksums*.txt; do
    [[ -f "$candidate" ]] || continue
    checksums_file="$candidate"
    break
done
if [[ -n "$checksums_file" ]]; then
    log INFO "verifying checksums ($(basename "$checksums_file"))..."
    checksum_tool=""
    if command -v shasum >/dev/null 2>&1; then
        checksum_tool="shasum -a 256"
    elif command -v sha256sum >/dev/null 2>&1; then
        checksum_tool="sha256sum"
    fi
    [[ -n "$checksum_tool" ]] || die "checksums file present but neither shasum nor sha256sum found"
    verify_list="$TMP_DIR/.verify-list"
    : >"$verify_list"
    for archive in "${archives[@]}"; do
        base="$(basename "$archive")"
        grep -F " $base" "$checksums_file" >>"$verify_list" ||
            die "no checksum entry for downloaded asset $base in $(basename "$checksums_file")"
    done
    # Entries are "<sha>  <name>" (or with a leading *), relative to $TMP_DIR.
    (cd "$TMP_DIR" && $checksum_tool -c "$verify_list") || die "checksum verification failed for $TAG"
    log INFO "checksums verified"
else
    log WARNING "no checksums in $TAG release; skipping verification"
fi

# Extract one archive into a destination directory, format-agnostic.
extract_archive() {
    local archive="$1" dest="$2"
    case "$archive" in
    *.tar.gz)
        tar -xzf "$archive" -C "$dest"
        ;;
    *.zip)
        need_cmd unzip
        unzip -q "$archive" -d "$dest"
        ;;
    *)
        die "unsupported archive format: $archive"
        ;;
    esac
}

for archive in "${archives[@]}"; do
    base="$(basename "$archive")"
    stem="$(strip_archive_ext "$base")"
    if ! parse_stem_to_platform "$stem"; then
        die "unknown platform in asset '$base' (expected mac|linux|windows + amd64|arm64)"
    fi
    if [[ -e "$STAGE_DIR/$PLATFORM" ]]; then
        die "duplicate asset for platform $PLATFORM (from $base)"
    fi
    # Only the six bundled platforms are installed; freebsd and the
    # architecture-specific arm builds (armv5/v6/v7/riscv64/ppc64le/s390x)
    # are skipped on purpose.
    case "$PLATFORM" in
    macos-x86_64 | macos-arm64 | linux-x86_64 | linux-arm64 | windows-x86_64 | windows-arm64) ;;
    *)
        log INFO "skipping $base (platform $PLATFORM is not bundled)"
        continue
        ;;
    esac
    log INFO "extracting $base -> $TAG/$PLATFORM"
    extract_dir="$TMP_DIR/extract-$PLATFORM"
    mkdir -p "$extract_dir"
    extract_archive "$archive" "$extract_dir"
    bin_src=""
    for cand in "$extract_dir/caddy" "$extract_dir/caddy.exe"; do
        if [[ -f "$cand" ]]; then
            bin_src="$cand"
            break
        fi
    done
    if [[ -z "$bin_src" ]]; then
        # Some archives nest everything under a single top-level directory.
        for cand in "$extract_dir"/*/caddy "$extract_dir"/*/caddy.exe; do
            if [[ -f "$cand" ]]; then
                bin_src="$cand"
                break
            fi
        done
    fi
    [[ -n "$bin_src" ]] || die "no caddy binary in $base (expected caddy or caddy.exe)"
    bin_name="$(basename "$bin_src")"
    target_dir="$STAGE_DIR/$PLATFORM"
    mkdir -p "$target_dir"
    cp -p "$bin_src" "$target_dir/$bin_name"
    chmod +x "$target_dir/$bin_name"
    [[ -s "$target_dir/$bin_name" ]] || die "installed binary is empty: $target_dir/$bin_name"
    for extra in LICENSE; do
        if [[ -f "$extract_dir/$extra" ]]; then
            cp -p "$extract_dir/$extra" "$target_dir/$extra"
        fi
    done
    log INFO "installed $PLATFORM/$bin_name (from $base)"
    rm -rf -- "$extract_dir"
done

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
for cand in "$TAG_DIR/$host_platform/caddy" "$TAG_DIR/$host_platform/caddy.exe"; do
    if [[ -x "$cand" ]]; then
        host_bin="$cand"
    fi
done
if [[ -n "$host_bin" ]]; then
    if "$host_bin" version >/dev/null 2>&1; then
        log INFO "host binary $host_platform runs (version exited 0)"
    else
        log WARNING "host binary $host_platform failed to run (version exited non-zero)"
    fi
else
    log WARNING "host platform $host_platform not in bundle; skipped host check"
fi

log INFO "done: $TAG_DIR now contains:"
for dir in "$TAG_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    log INFO "  $(basename "$dir")"
done
