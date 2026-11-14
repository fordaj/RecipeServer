# NOTICE — third-party formatters redistributed by Formattington

Formattington orchestrates existing open-source tools. The `formattington-<platform>-full` release binaries redistribute unmodified upstream executables for the tools listed below (and, for Prettier and markdownlint, binaries built at release time from pinned upstream npm sources with Bun). The `formattington-<platform>-lite` binaries redistribute nothing. This file and the `LICENSES/` directory are included in every release archive so the notices below travel with the binaries.

Each tool belongs to its upstream project and remains under its own license. Formattington does not reimplement these tools. Upstream sources, licenses, and copyright attributions (license texts are in `LICENSES/<tool>.txt`):

| Tool | Source | License | Redistribution |
| ---- | ------ | ------- | -------------- |
| shfmt | https://github.com/mvdan/sh | BSD-3-Clause | unmodified upstream release binaries |
| clang-format | https://github.com/cpp-linter/clang-tools-static-binaries (LLVM via https://github.com/llvm/llvm-project) | Unlicense (repackaged LLVM binaries); upstream LLVM is Apache-2.0 WITH LLVM-exception (see `LICENSES/llvm-LICENSE.txt`) | unmodified upstream binaries; SHA-512 verified at fetch time against the upstream index |
| black | https://github.com/psf/black | MIT | unmodified upstream release binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/black/update.sh` (macOS x86_64 is built from source on a native Intel Mac; the tag's commit hash is pinned) |
| prettier | https://github.com/prettier/prettier | MIT | built at release time from the pinned npm lockfile (`formatters/prettier/pnpm-lock.yaml`; every tarball's SHA-512 integrity is pinned) |
| markdownlint | https://github.com/igorshubovych/markdownlint-cli | MIT | built at release time from the pinned npm lockfile (`formatters/markdownlint/pnpm-lock.yaml`; every tarball's SHA-512 integrity is pinned) |
| taplo | https://github.com/tamasfe/taplo | MIT | unmodified upstream release binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/taplo/update.sh` |
| stylua | https://github.com/JohnnyMorganz/StyLua | MPL-2.0 | unmodified upstream release binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/stylua/update.sh`; the corresponding source is available at the URL above |
| cljfmt | https://github.com/weavejester/cljfmt | EPL-1.0 | unmodified upstream release binaries; SHA-256 verified at fetch time against upstream-published `.sha256` sidecars; the corresponding source is available at the URL above |
| google-java-format | https://github.com/google/google-java-format | Apache-2.0 | unmodified upstream native binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/google-java-format/update.sh` |
| ktfmt | https://github.com/Kotlin/ktfmt | Apache-2.0 | unmodified upstream native binaries; SHA-256 verified at fetch time against upstream-published `.sha256` sidecars |
| elm-format | https://github.com/avh4/elm-format | BSD-3-Clause | unmodified upstream static binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/elm-format/update.sh` |
| fourmolu | https://github.com/fourmolu/fourmolu | BSD-3-Clause | unmodified upstream release binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/fourmolu/update.sh` |
| shfmt | https://github.com/mvdan/sh | BSD-3-Clause | unmodified upstream release binaries; SHA-256 verified at fetch time against hashes pinned in `formatters/shfmt/update.sh` |

Every tool listed above is fetched at release time and verified hard-fail on mismatch — either against upstream-published checksums (clang-format, cljfmt, ktfmt) or against SHA-256/SHA-512 hashes pinned in this repository (`formatters/<tool>/update.sh` for the binary downloads, `pnpm-lock.yaml` for the npm-built bundles). All tools listed are redistributed unmodified — Formattington never patches, recompresses, or re-links upstream binaries.

MPL-2.0 (stylua) and EPL-1.0 (cljfmt) notices

- MPL-2.0: the upstream binaries are redistributed unmodified; the complete corresponding source code is available at https://github.com/JohnnyMorganz/StyLua (MPL-2.0 permits this combined with reproduction of the license text, which is in `LICENSES/stylua.txt`).
- EPL-1.0: the upstream binaries are redistributed unmodified; the complete corresponding source code is available at https://github.com/weavejester/cljfmt (EPL-1.0 section 3; license text in `LICENSES/cljfmt.txt`).

Additional resources

- Stack Overflow Developer Survey 2026, "Programming, scripting, and markup languages", All Respondents — licensed under ODbL 1.0. Formattington's presented order derives from that dataset; see `AGENTS.md`, "Presentation order", for attribution.
- Formattington itself is licensed under the MIT License (see `LICENSE`).
