# The mkcert bundle (`tools/mkcert/`)

[mkcert](https://github.com/FiloSottile/mkcert) issues locally-trusted development certificates. RecipeServer uses it for the optional HTTPS mode: when HTTPS is enabled in the configuration, the app generates a certificate covering every address this machine answers to (`.local` hostname, LAN IPv4/IPv6 addresses, Tailscale name, plus any extra names from `https_extra_names`) and the bundled Caddy serves it (see "Optional HTTPS front-end" in `src/recipeserver/https_setup.py`, documented in `src/recipeserver/https_setup.py.md` in the repository). The first enable runs `mkcert -install` — the one step that asks for anything (the user's password via `sudo` on macOS; system root-store access on Windows).

## Layout

```text
mkcert release assets (raw executables — no archives):
  mkcert-v1.4.4-darwin-amd64  → tools/mkcert/v1.4.4/macos-x86_64/mkcert
  mkcert-v1.4.4-darwin-arm64  → tools/mkcert/v1.4.4/macos-arm64/mkcert
  mkcert-v1.4.4-linux-amd64   → tools/mkcert/v1.4.4/linux-x86_64/mkcert
  mkcert-v1.4.4-linux-arm64   → tools/mkcert/v1.4.4/linux-arm64/mkcert
  mkcert-v1.4.4-windows-amd64.exe → tools/mkcert/v1.4.4/windows-x86_64/mkcert.exe
  mkcert-v1.4.4-windows-arm64.exe → tools/mkcert/v1.4.4/windows-arm64/mkcert.exe
```

The release ships raw executables — no platform archives and no checksums file — so `update.sh` verifies each download by size (non-empty) and by running `mkcert -version` on the host, and fetches the upstream `LICENSE` from the tag (BSD-3-Clause) into each platform directory.

## `update.sh` in detail

1. Resolves the tag (latest release, or `--tag vX.Y.Z`), validating the tag shape (`vX.Y.Z...`). `--repo`/env `MKCERT_REPO` overrides the upstream repository slug (default `FiloSottile/mkcert`; env `MKCERT_TAG` pins the tag, overridden by `--tag`).
2. Downloads each asset via `gh release download --pattern <asset>` (one release download per platform), into a staging directory under `v<tag>/<platform>/`.
3. Fetches `LICENSE` from `raw.githubusercontent.com/<repo>/<tag>/LICENSE` and copies it into each platform directory. If the fetch fails the bundle still installs (a warning is logged), matching the checksums-tolerant behavior of the other bundles.
4. Swaps in the new version directory and deletes superseded `v*/` ones, then smoke-tests the host binary (`mkcert -version` exits 0).

Unknown arguments exit `2`. `--dry-run` lists the six target assets and what would change without touching anything.

The `<platform>` directory names match the env cascade: `macos|linux|windows` + `x86_64|arm64`. The pinned tag is `v1.4.4`, selected via `MKCERT_VERSION_DIR` in `scripts/.common.env` and exposed to scripts as `MKCERT_BIN` by `scripts/.<platform>.env`; see [../../scripts/env.sh.md](../../scripts/env.sh.md).

## How the repository uses it

`src/recipeserver/https_setup.py` owns the runtime flow: it resolves the binary (the `MKCERT_BIN` environment variable, this bundle, or `mkcert` on `PATH`), checks whether the local CA is installed (a marker file under the user data directory plus the existence of `mkcert -CAROOT`/`rootCA.pem`; if not, `mkcert -install` runs once), and issues (or reuses) a certificate covering this machine's names. Certificates are reissued only when the name list changes. mkcert is not consulted at serving time; Caddy only reads the generated PEMs.

## Related pages

- [../README.md](../README.md) — the bundle index
- [../caddy/update.sh.md](../caddy/update.sh.md) — the other half of HTTPS setup
- [../../scripts/env.sh.md](../../scripts/env.sh.md) — how `MKCERT_BIN` is selected
