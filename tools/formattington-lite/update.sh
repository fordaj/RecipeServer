#!/usr/bin/env bash
# update.sh — refresh bundled formattington-lite binaries from fordaj/formattington releases.
#
# Downloads the LITE assets of the latest release via gh (the full assets,
# which embed the upstream formatter binaries, are never downloaded),
# extracts each into tools/formattington-lite/<tag>/<platform>/ (platform
# matches the bundled <os>-<arch> layout: macos/linux/windows + x86_64/arm64;
# formattington assets use x64/arm64, so x64 -> x86_64), and deletes old
# version folders. The binary, NOTICE.md, and LICENSES/ are kept (the lite
# archive ships attribution for redistributed code); upstream full-release
# extras are not present in the lite archives. Old v*/ folders are deleted
# only after the new version is fully staged, so a failed download leaves
# the previous bundle intact.
#
# Usage:
#   tools/formattington-lite/update.sh              # download latest, replace old versions
#   tools/formattington-lite/update.sh --dry-run    # resolve tag + list assets, change nothing
#   tools/formattington-lite/update.sh --help       # usage
#
# Prerequisites: gh (https://cli.github.com/), tar (for .tar.gz assets), and
# unzip or 7z/7zz for the Windows .zip assets. Checksum verification runs
# only if a checksums.txt asset exists (formattington releases do not
# publish one today) and requires shasum or sha256sum. The script resolves
# its own directory, so it can be run from anywhere. Logging uses
# log <level> <message> from scripts/entry.sh (logamuffin, with printf
# fallback until tools/logamuffin is populated).
#
# Asset -> platform mapping (lite assets only; -full assets are ignored):
#   formattington-macos-arm64-lite.tar.gz  -> macos-arm64
#   formattington-macos-x64-lite.tar.gz    -> macos-x86_64
#   formattington-linux-arm64-lite.tar.gz  -> linux-arm64
#   formattington-linux-x64-lite.tar.gz    -> linux-x86_64
#   formattington-windows-arm64-lite.zip   -> windows-arm64
#   formattington-windows-x64-lite.zip     -> windows-x86_64
#
# Layout after a successful run (example for v0.0.1.0.51):
#   tools/formattington-lite/
#     update.sh
#     v0.0.1.0.51/
#       macos-arm64/formattington (+ NOTICE.md, LICENSES/)
#       macos-x86_64/formattington (+ NOTICE.md, LICENSES/)
#       linux-arm64/formattington (+ NOTICE.md, LICENSES/)
#       linux-x86_64/formattington (+ NOTICE.md, LICENSES/)
#       windows-arm64/formattington.exe (+ NOTICE.md, LICENSES/)
#       windows-x86_64/formattington.exe (+ NOTICE.md, LICENSES/)
#
# Env:
#   FORMATTINGTON_REPO  Repository slug (default: fordaj/formattington)
#   FORMATTINGTON_TAG   Pinned tag (default: latest release)

set -euo pipefail

# Logging via logamuffin (log <level> <message> from scripts/entry.sh,
# with printf fallback until tools/logamuffin is populated). Source the
# env cascade first so every later message goes through log().
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT_FOR_ENV=$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)
if [[ ! -f "$REPO_ROOT_FOR_ENV/scripts/entry.sh" ]]; then
    printf 'update.sh: error: env cascade not found: %s/scripts/entry.sh\n' "$REPO_ROOT_FOR_ENV" >&2
    exit 1
fi
# shellcheck disable=SC1091
. "$REPO_ROOT_FOR_ENV/scripts/entry.sh"

DRY_RUN=0
TAG="${FORMATTINGTON_TAG:-}"
REPO="${FORMATTINGTON_REPO:-fordaj/formattington}"

usage() {
    cat <<'EOF'
Usage: tools/formattington-lite/update.sh [--dry-run] [--tag TAG] [--repo REPO]

Download the latest formattington release's LITE assets from GitHub via
gh, extract each platform binary into tools/formattington-lite/<tag>/<platform>/
(platform matches the bundled <os>-<arch> layout, e.g. macos-arm64; the
assets' x64 is mapped to x86_64), and delete old version folders. The
binary, NOTICE.md, and LICENSES/ are kept; -full assets are never
downloaded.

Flags:
  --dry-run, -n   Resolve tag + list planned assets, change nothing.
  --tag TAG       Pin a specific release tag (default: latest release).
  --repo REPO     Repository slug (default: fordaj/formattington).
  --help, -h      Show this help.

Env:
  FORMATTINGTON_REPO  Repository slug (overridden by --repo).
  FORMATTINGTON_TAG   Pinned tag (overridden by --tag).
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
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1 (https://cli.github.com/)"
}

need_cmd gh

if [[ "$DRY_RUN" -ne 1 ]]; then
    need_cmd tar
    # Windows lite assets are .zip; macOS/Linux lite assets are .tar.gz.
    if command -v unzip >/dev/null 2>&1; then
        ZIP_EXTRACT=(unzip -q)
    elif command -v 7zz >/dev/null 2>&1; then
        ZIP_EXTRACT=(7zz x -y)
    elif command -v 7z >/dev/null 2>&1; then
        ZIP_EXTRACT=(7z x -y)
    else
        die "required command not found: unzip or 7z/7zz (needed for the Windows .zip assets; brew install unzip / apt-get install unzip)"
    fi
fi

FORMATTINGTON_ROOT="$SCRIPT_DIR"
[[ -d "$FORMATTINGTON_ROOT" ]] || die "formattington-lite bundle directory not found: $FORMATTINGTON_ROOT"
log INFO "formattington-lite bundle directory: $FORMATTINGTON_ROOT"
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

# parse_stem_to_platform <stem> sets PLATFORM (e.g.
# formattington-macos-x64-lite -> macos-x86_64) or returns 1 for
# unknown values. Sets globals to avoid subshell-die pitfalls. The
# assets use x64/arm64 after the os, and the bundled layout uses
# x86_64/arm64, so x64 is mapped to x86_64 here. The arch may itself
# contain "_" (x86_64), so the suffix is matched as a whole instead of
# splitting on the last "_".
parse_stem_to_platform() {
    local stem="$1"
    case "$stem" in
    formattington-macos-x86_64-lite | formattington-macos-x64-lite | formattington-darwin-amd64-lite) PLATFORM="macos-x86_64" ;;
    formattington-macos-arm64-lite | formattington-darwin-arm64-lite) PLATFORM="macos-arm64" ;;
    formattington-linux-x86_64-lite | formattington-linux-x64-lite | formattington-linux-amd64-lite) PLATFORM="linux-x86_64" ;;
    formattington-linux-arm64-lite) PLATFORM="linux-arm64" ;;
    formattington-windows-x86_64-lite | formattington-windows-x64-lite | formattington-windows-amd64-lite) PLATFORM="windows-x86_64" ;;
    formattington-windows-arm64-lite) PLATFORM="windows-arm64" ;;
    *) return 1 ;;
    esac
}

# asset_kind <filename> prints "lite-archive", "full-archive",
# "checksums", or "ignored". Only lite archives are ever downloaded.
asset_kind() {
    case "$1" in
    *-lite.tar.gz | *-lite.zip) printf 'lite-archive\n' ;;
    *-full.tar.gz | *-full.zip) printf 'full-archive\n' ;;
    checksums.txt) printf 'checksums\n' ;;
    *) printf 'ignored\n' ;;
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
        kind="$(asset_kind "$asset")"
        case "$kind" in
        lite-archive)
            asset_count=$((asset_count + 1))
            stem="${asset%.tar.gz}"
            stem="${stem%.zip}"
            if parse_stem_to_platform "$stem"; then
                log INFO "  $asset -> $TAG/$PLATFORM"
            else
                log INFO "  $asset -> unknown platform (would fail)"
            fi
            ;;
        full-archive)
            log INFO "  $asset (ignored: full release)"
            ;;
        checksums)
            log INFO "  $asset (checksums)"
            ;;
        *)
            log INFO "  $asset (ignored)"
            ;;
        esac
    done <<<"$assets_list"
    ((asset_count > 0)) || die "no lite assets found for $TAG in $REPO"
    shopt -s nullglob
    old_found=0
    for dir in "$FORMATTINGTON_ROOT"/v*/; do
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
    log INFO "dry run complete: would update $FORMATTINGTON_ROOT/$TAG"
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
STAGE_DIR="$(mktemp -d "$FORMATTINGTON_ROOT/.tmp.XXXXXX")"

log INFO "downloading $TAG lite assets from $REPO..."
gh release download "$TAG" --repo "$REPO" --dir "$TMP_DIR" --pattern '*-lite.tar.gz' --pattern '*-lite.zip' --pattern 'checksums.txt' --clobber

shopt -s nullglob
archives=("$TMP_DIR"/*-lite.tar.gz "$TMP_DIR"/*-lite.zip)
((${#archives[@]} > 0)) || die "no lite assets downloaded from $REPO $TAG"
log INFO "downloaded ${#archives[@]} lite archives"

if [[ -f "$TMP_DIR/checksums.txt" ]]; then
    log INFO "verifying checksums..."
    if command -v shasum >/dev/null 2>&1; then
        (cd "$TMP_DIR" && shasum -a 256 -c checksums.txt) || die "checksum verification failed for $TAG"
    elif command -v sha256sum >/dev/null 2>&1; then
        (cd "$TMP_DIR" && sha256sum -c checksums.txt) || die "checksum verification failed for $TAG"
    else
        die "checksums.txt present but neither shasum nor sha256sum found"
    fi
    log INFO "checksums verified"
else
    log INFO "release publishes no checksums.txt; skipping verification"
fi

for archive in "${archives[@]}"; do
    base="$(basename "$archive")"
    stem="${base%.tar.gz}"
    stem="${stem%.zip}"
    if ! parse_stem_to_platform "$stem"; then
        die "unknown platform in asset '$base' (expected formattington-<os>-<arch>-lite such as macos-arm64)"
    fi
    if [[ -e "$STAGE_DIR/$PLATFORM" ]]; then
        die "duplicate asset for platform $PLATFORM (from $base)"
    fi
    log INFO "extracting $base -> $TAG/$PLATFORM"
    extract_dir="$TMP_DIR/extract-$PLATFORM"
    mkdir -p "$extract_dir"
    case "$base" in
    *.tar.gz)
        tar -xzf "$archive" -C "$extract_dir"
        ;;
    *.zip)
        case "${ZIP_EXTRACT[0]}" in
        unzip) "${ZIP_EXTRACT[@]}" "$archive" -d "$extract_dir" ;;
        *) "${ZIP_EXTRACT[@]}" "$archive" -o"$extract_dir" >/dev/null ;;
        esac
        ;;
    esac
    # The lite archives nest a top-level <asset-stem>/ directory holding
    # the binary, NOTICE.md, and LICENSES/. Accept a root-level binary too,
    # in case the layout ever flattens.
    bin_src=""
    for cand in "$extract_dir"/*/formattington "$extract_dir"/*/formattington.exe "$extract_dir"/formattington "$extract_dir"/formattington.exe; do
        if [[ -f "$cand" ]]; then
            bin_src="$cand"
        fi
    done
    [[ -n "$bin_src" ]] || die "no formattington binary in $base (expected formattington or formattington.exe in the archive)"
    inner_dir="$(dirname "$bin_src")"
    bin_name="$(basename "$bin_src")"
    target_dir="$STAGE_DIR/$PLATFORM"
    mkdir -p "$target_dir"
    cp -p "$bin_src" "$target_dir/$bin_name"
    chmod +x "$target_dir/$bin_name"
    # Keep the attribution files that ship in the lite archive.
    if [[ -f "$inner_dir/NOTICE.md" ]]; then
        cp -p "$inner_dir/NOTICE.md" "$target_dir/NOTICE.md"
    fi
    if [[ -d "$inner_dir/LICENSES" ]]; then
        cp -pR "$inner_dir/LICENSES" "$target_dir/LICENSES"
    fi
    [[ -s "$target_dir/$bin_name" ]] || die "installed binary is empty: $target_dir/$bin_name"
    log INFO "installed $PLATFORM/$bin_name (from $base)"
    rm -rf -- "$extract_dir"
done

TAG_DIR="$FORMATTINGTON_ROOT/$TAG"
rm -rf -- "$TAG_DIR"
mkdir -p "$FORMATTINGTON_ROOT"
mv "$STAGE_DIR" "$TAG_DIR"
STAGE_DIR=""

for dir in "$FORMATTINGTON_ROOT"/v*/; do
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
for cand in "$TAG_DIR/$host_platform/formattington" "$TAG_DIR/$host_platform/formattington.exe"; do
    if [[ -x "$cand" ]]; then
        host_bin="$cand"
    fi
done
if [[ -n "$host_bin" ]]; then
    host_ver="$("$host_bin" --version 2>&1 || true)"
    log INFO "host binary $host_platform reports: $host_ver"
    expected_ver="${TAG#v}"
    case "$host_ver" in
    *"$TAG"* | *"$expected_ver"*) ;;
    *) log WARNING "host binary version '$host_ver' does not contain $TAG" ;;
    esac
else
    log WARNING "host platform $host_platform not in bundle; skipped version check"
fi

log INFO "done: $TAG_DIR now contains:"
for dir in "$TAG_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    log INFO "  $(basename "$dir")"
done
