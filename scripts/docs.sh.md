# The docs generator (`scripts/docs.sh`)

```mermaid
flowchart LR
    docs["scripts/docs.sh"] --> entry["entry.sh"]
    entry --> env["env.sh + hidden<br/>.*.env cascade"]
    env --> bin["BARNACLE_BIN<br/>tools/barnacle/v…/barnacle"]
    bin --> config[".barnacle.json"]
    config --> site["./site/"]
    click entry href "entry.sh.md"
    click env href "env.sh.md"
```

Generates the documentation site you are reading: it runs the pinned barnacle binary (`tools/barnacle/update.sh.md`) against this repository.

Barnacle scans the working tree for Markdown (`.md`) and Mermaid (`.mmd`) files, renders each as a page, and keeps relative links between them. Generated output is static HTML; it is written to `./site/` by default and is never committed (it is in `.gitignore`).

## Usage

```bash
scripts/docs.sh                       # generate into ./site/
scripts/docs.sh --site ./public       # forward --site to barnacle
scripts/docs.sh --config ./docs/barnacle.json
scripts/docs.sh --help                # usage for this script
```

Any arguments other than `--help`/`-h` are forwarded to barnacle verbatim; see `barnacle --help` for `--config`/`--site` semantics. Barnacle exits non-zero and leaves no half-built site on failure; regenerating into a directory previously produced by barnacle wipes and rebuilds it.

## How it locates barnacle

Sources [entry.sh.md](entry.sh.md); `BARNACLE_BIN` comes from the [cascade](env.sh.md) (`tools/barnacle/v<version>/<platform>/barnacle[.exe]`). If the bundle is missing or not executable, the script fails — via `log ERROR` — with instructions to run `tools/barnacle/update.sh` (or set `BARNACLE_BIN` explicitly). It then runs barnacle with the repository root as the working directory, so barnacle's auto-discovered `./.barnacle.json` (optional) and its default `./site/` output land at the repository root regardless of the caller's cwd.

## What the site contains

Every hand-written page in the tree, including this one — see the [root README](../README.md) and [AGENTS.md](../AGENTS.md). `.git`, `node_modules`, `vendor`, `dist`, and the output directory are always excluded by barnacle; hidden files and directories (the cascade's `.common.env` et al.) are skipped by default. `.barnacle.json` additionally excludes `tools/`, `test/`, the vendored KaTeX tree (`src/recipeserver/assets/katex`), and the three model-prompt files (`NewRecipePrompt.md`, `NewRecipeFromImagePrompt.md`, `FindOneForMePrompt.md`) — content files, vendored third-party docs, and pinned binaries' docs are not rendered as pages.

## Related pages

- `tools/barnacle/update.sh.md` — the pinned binaries and how to refresh them (not rendered in the site)
- [entry.sh.md](entry.sh.md) · [env.sh.md](env.sh.md)
