# The whisper-native bundle (`tools/whisper-native/`)

[whisper-native](https://github.com/fordaj/whisper-native) ships precompiled, CPU-only, cross-platform native binaries of [whisper.cpp](https://github.com/ggml-org/whisper.cpp). RecipeServer uses it for the dictation feature: the app manages the `whisper-server` process (started lazily, stopped on shutdown — see `src/recipeserver/whisper_server.py`), which transcribes the recorded search phrase locally. No Python ML dependency is required, which keeps `uv sync` working on platforms where `faster-whisper`'s transitive `onnxruntime` has no wheel (notably macOS x86_64).

## Layout

```text
tools/whisper-native/
  update.sh                     # refresh from fordaj/whisper-native releases
  v1.9.5/
    macos-arm64/whisper-server
    macos-x86_64/whisper-server
    linux-arm64/whisper-server
    linux-x86_64/whisper-server
    windows-arm64/whisper-server.exe
    windows-x86_64/whisper-server.exe
```

Only `whisper-server` is bundled; the release archives also carry `whisper-cli`, which RecipeServer does not use.

## `update.sh` in detail

Archives are `.tar.gz` (macOS/Linux) and `.zip` (Windows); each is flat and carries the binaries, the upstream licenses, and a `WHISPER-NATIVE-BUILDINFO.txt`. The script:

1. Resolves the tag (latest release, or `--tag vX.Y.Z`), validating the tag shape (`vX.Y.Z...`). `--repo`/env `WHISPER_NATIVE_REPO` override the upstream repository slug (default `fordaj/whisper-native`; env `WHISPER_NATIVE_TAG` pins the tag, overridden by `--tag`).
2. Downloads via `gh`, then verifies every downloaded archive against the upstream `checksums.txt` or `SHA256SUMS.txt` (`shasum -a 256 -c` or `sha256sum -c`). A missing checksum for a downloaded asset is fatal; a release without any checksums file only warns.
3. Extracts each archive (`tar` for `.tar.gz`; `unzip`, falling back to `7z`/`7zz` for `.zip`), copies `whisper-server[.exe]` into `v<tag>/<platform>/`, makes it executable, and copies `LICENSE`, `LICENSE.whisper.cpp`, and `WHISPER-NATIVE-BUILDINFO.txt` alongside it.
4. Swaps in the new version directory and deletes superseded `v*/` ones, then smoke-tests the host binary (`whisper-server -h` exits 0). The server has no `--version` flag, so the check only proves the binary runs.

Unknown arguments exit `2`. `--dry-run` lists assets and what would change without touching anything.

The `<platform>` directory names match the env cascade: `macos|linux|windows` + `x86_64|arm64`. The pinned tag is `v1.9.5` (version parity with upstream whisper.cpp v1.9.5), selected via `WHISPER_NATIVE_VERSION_DIR` in `scripts/.common.env` and exposed to scripts as `WHISPER_SERVER_BIN` by `scripts/.<platform>.env`; see [../../scripts/env.sh.md](../../scripts/env.sh.md).

## How the repository uses it

`src/recipeserver/whisper_server.py` owns the runtime lifecycle: it resolves the binary (the `WHISPER_SERVER_BIN` environment variable, this bundle, or `whisper-server` on `PATH`), downloads the ggml model weights on first use into the user data directory, starts the server on an ephemeral loopback port, waits until the model is in memory, and stops the process on app shutdown or when dictation is disabled in the configuration. Model weights are **not** part of the release; they are downloaded from Hugging Face on first use.

## Related pages

- [../README.md](../README.md) — the bundle index
- [../../scripts/README.md](../../scripts/README.md) — the scripts that consume the bundle
- [../../scripts/env.sh.md](../../scripts/env.sh.md) — how `WHISPER_SERVER_BIN` is selected
