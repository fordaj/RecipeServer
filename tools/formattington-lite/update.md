# The formattington-lite bundle (`tools/formattington-lite/`)

[Formattington](https://github.com/fordaj/formattington) is the repository's formatter. RecipeServer uses formattington two ways: the primary path is the pinned `uv` dev dependency invoked by [format.sh](../../format.md) (`uv run formattington all --config .formattington.json`), and this bundle is the committed binary fallback for environments where the uv path is unavailable. The `-lite` binaries redistribute nothing; the `NOTICE.md` and `LICENSES/` in each platform directory travel with the release archives anyway.

## Layout

```text
tools/formattington-lite/
  update.bash                     # refresh from fordaj/formattington releases
  v0.0.2.0.53/
    macos-arm64/formattington
    macos-arm64/NOTICE.md
    macos-arm64/LICENSES/<tool>.txt
    … (one directory per platform)
```

Platform directories: `macos-arm64`, `macos-x86_64`, `linux-arm64`, `linux-x86_64`, `windows-arm64`, `windows-x86_64`.

## `update.bash` in detail

Archives are `.tar.gz` (macOS/Linux) and `.zip` (Windows). The script:

1. Resolves the tag (latest release, or `--tag vX.Y.Z...`), validating the tag shape. `--repo`/env `FORMATTINGTON_REPO` override the slug (default `fordaj/formattington`; env `FORMATTINGTON_TAG` pins the tag, overridden by `--tag`). Asset stems may carry a `-lite` or `-full` suffix (e.g. `…_darwin-arm64-lite`); the platform is parsed from the os-arch part and `-lite`/`-full` are accepted and stripped — both variants map onto the same platform directory, so the script expects exactly one archive per platform.
2. Downloads via `gh` and verifies downloaded archives against `checksums.txt` or `SHA256SUMS.txt`. Missing checksum file: a warning, not fatal.
3. Extracts each archive, copies the `formattington` binary into `v<tag>/<platform>/`, keeps `NOTICE.md` and `LICENSES/` alongside it (recursively), and makes the binary executable.
4. Swaps in the new version directory and deletes superseded `v*/` ones, then smoke-tests the host binary (`formattington --version`).

Unknown arguments exit `2`. `--dry-run` lists assets and what would change without touching anything.

## How the repository uses it

[format.sh](../../format.md) does not call this binary — it uses the pinned uv dependency. The bundle exists so a checkout without working uv/network access still has a formattington on hand; the repository's `README.md` credits it as the formatting fallback in the "Bundled tooling and CI" table.

## Related pages

- [../README.md](../README.md) — the bundle index
- [../../format.md](../../format.md) — the formatting entry point
- [../../scripts/README.md](../../scripts/README.md)
