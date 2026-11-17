# The logamuffin bundle (`tools/logamuffin/`)

```mermaid
flowchart LR
    gh("<img src='barnacle:download.svg' width='20' alt=''/><br/><u>gh release view<br/>--repo logamuffin</u>") --> assets("<img src='barnacle:package.svg' width='20' alt=''/><br/>platform archives<br/>.tar.gz · .zip")
    assets --> verify("<img src='barnacle:check.svg' width='20' alt=''/><br/>checksums<br/>checksums.txt / SHA256SUMS.txt")
    verify --> extract("<img src='barnacle:package-open.svg' width='20' alt=''/><br/>extract binary")
    extract --> stage("<img src='barnacle:folder.svg' width='20' alt=''/><br/>stage v<tag>/<platform>/")
    stage --> swap("<img src='barnacle:folder-sync.svg' width='20' alt=''/><br/><u>swap + delete old v*/</u>")
    click gh href "../README.md"
    click swap href "../../scripts/env.sh.md"
    class gh dlNode
    class assets boxNode
    class verify checkNode
    class stage,swap folder
    classDef dlNode fill:#93e2e2,stroke:#0f766e,color:#042f2e
    classDef boxNode fill:#e8cf9d,stroke:#a16207,color:#33240a
    classDef checkNode fill:#9fe8c9,stroke:#0f766e,color:#052e22
    classDef folder fill:#f0c558,stroke:#8a6d1c,color:#332a05
```

[Logamuffin](https://github.com/fordaj/logamuffin) is a structured-logging binary: the backend behind the `log()` shell function defined in [scripts/entry.sh](../../scripts/entry.sh.md). Every repository script routes its output through it, with a printf fallback when the binary is missing.

## Layout

```text
tools/logamuffin/
  update.sh                     # refresh from fordaj/logamuffin releases
  v0.1.3.0.35/
    macos-arm64/logamuffin
    macos-x86_64/logamuffin
    linux-arm64/logamuffin
    linux-x86_64/logamuffin
    windows-arm64/logamuffin.exe
    windows-x86_64/logamuffin.exe
```

## `update.sh` in detail

Archives are `.tar.gz` (macOS/Linux) and `.zip` (Windows). The script:

1. Resolves the tag (latest release, or `--tag vX.Y.Z...`), validating the tag shape. `--repo`/env `LOGAMUFFIN_REPO` override the slug (default `fordaj/logamuffin`; env `LOGAMUFFIN_TAG` pins the tag, overridden by `--tag`).
2. Downloads via `gh` and verifies downloaded archives against `checksums.txt` or `SHA256SUMS.txt`. A missing checksum for a downloaded asset is fatal; a release without any checksums file only warns.
3. Extracts each archive, copies the `logamuffin` binary into `v<tag>/<platform>/`, makes it executable, and verifies it is non-empty.
4. Swaps in the new version directory and deletes superseded `v*/` ones, then smoke-tests the host binary (`logamuffin --version`).

Only the binary is kept — no LICENSE or NOTICE files are retained by this bundle. Unknown arguments exit `2`. `--dry-run` lists assets and what would change without touching anything.

## How the repository uses it

[scripts/entry.sh](../../scripts/entry.sh.md) resolves `LOGAMUFFIN_BIN` through the [env cascade](../../scripts/env.sh.md) and forwards every `log LEVEL MESSAGE…` call to the binary with `LOG_SOURCE` set to the call site; when the binary is absent, `log()` falls back to a printf implementation. `scripts/release.sh` logs a warning naming `tools/logamuffin/update.sh` when the binary is missing.

## Related pages

- [../README.md](../README.md) — the bundle index
- [../../scripts/entry.sh.md](../../scripts/entry.sh.md) — the `log()` consumer
- [../../scripts/README.md](../../scripts/README.md)
