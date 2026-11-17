# Repository script tooling (`scripts/`)

```mermaid
flowchart TD
    task("<img src='barnacle:terminal.svg' width='20' alt=''/><br/><u>A task script<br/>serve.sh, format.sh, …</u>") --> entry("<img src='barnacle:terminal.svg' width='20' alt=''/><br/><u>entry.sh</u>")
    entry --> env("<img src='barnacle:terminal.svg' width='20' alt=''/><br/><u>env.sh</u>")
    env --> common("<img src='barnacle:terminal.svg' width='20' alt=''/><br/>.common.env")
    env --> platform("<img src='barnacle:terminal.svg' width='20' alt=''/><br/>.<os>-<arch>.env")
    entry --> log("<img src='barnacle:logs.svg' width='20' alt=''/><br/>log()<br/>logamuffin or printf fallback")
    common --> bins("<img src='barnacle:binary.svg' width='20' alt=''/><br/><u>VERSIONER_BIN · LOGAMUFFIN_BIN<br/>RUNNER_SPAWNER_BIN · BARNACLE_BIN<br/>WHISPER_SERVER_BIN</u>")
    click entry href "entry.sh.md"
    click env href "env.sh.md"
    click task href "serve.sh.md"
    click bins href "docs.sh.md"
    class task,entry,env,common,platform shFile
    classDef shFile fill:#abe07a,stroke:#3f6212,color:#16280a
```

The `scripts/` directory carries the repository's build/release/docs tooling: an environment cascade the other scripts source, plus one entry point per task. Everything here is bash; nothing requires a global install beyond what each script documents.

Vernacular used in the headers (`log INFO`, `REPO_ROOT_DIR`, `VERSIONER_BIN`): read [entry.sh.md](entry.sh.md) first, then [env.sh.md](env.sh.md).

## The cascade (why the dotfiles exist)

- `scripts/entry.sh` — sources `scripts/env.sh` and defines `log()` (logamuffin, with a printf fallback). Sourced by the task scripts and by the tools' update scripts. See [entry.sh.md](entry.sh.md).
- `scripts/env.sh` — locates and sources the cascade below, then anchors the repository-relative `*_BIN` tool paths to the repository root. See [env.sh.md](env.sh.md).
- `scripts/.common.env`, `scripts/.<os>-<arch>.env` — the cascade proper. Hidden files, so barnacle does not render them as pages; [env.sh.md](env.sh.md) is their documentation. `.common.env` holds the platform-independent settings (`TOOLS_DIR=tools`, the `fordaj/*` upstream repos, versioner's `.versioner.json` settings, and the pinned `*_VERSION_DIR`s: versioner `v0.0.3.0.17`, logamuffin `v0.1.3.0.35`, runner-spawner `v0.0.1.2.16`, barnacle `v0.0.2.1.25`, whisper-native `v1.9.5`). Each platform file sets `PROJECT_PLATFORM` and the `*_BIN` paths for its `<os>-<arch>`.

## Task scripts

- [version.sh](version.sh.md) — print the repository version computed by versioner (`--format text|shell|json`).
- [format.sh](format.sh.md) — format the repository in place with formattington.
- [serve.sh](serve.sh.md) — launch the RecipeServer web app (development).
- [spawn-runners.sh](spawn-runners.sh.md) — spawn self-hosted GitHub Actions runners for this repository.
- [docs.sh](docs.sh.md) — generate the documentation site you are reading, with the bundled barnacle.
- [release.sh](release.sh.md) — compute the version, tag `HEAD`, push the tag, and create the GitHub release (version tracking only; see the caveat in [release.sh.md](release.sh.md)).
- [entry.sh](entry.sh.md) / [env.sh](env.sh.md) — the sourced cascade and `log()` helper (not entry points).

## Related pages

- `tools/README.md` — the bundled helper binaries these scripts resolve (not rendered in the site)
- [../README.md](../README.md)
- [../AGENTS.md](../AGENTS.md)
