# The release script (`scripts/release.sh`)

```mermaid
flowchart TD
    start("<img src='barnacle:terminal.svg' width='20' alt=''/><br/><u>scripts/release.sh</u>") --> checks("<img src='barnacle:check.svg' width='20' alt=''/><br/>git + gh checks<br/>clean tree required")
    checks --> versioner("<img src='barnacle:binary.svg' width='20' alt=''/><br/><u>versioner --repo-dir <root></u>")
    versioner --> tag("<img src='barnacle:tag.svg' width='20' alt=''/><br/>tag v<version>")
    tag --> push("<img src='barnacle:upload.svg' width='20' alt=''/><br/>git push origin <tag>")
    push --> gh("<img src='barnacle:tag.svg' width='20' alt=''/><br/>gh release create --generate-notes")
    click versioner href "version.sh.md"
    click start href "entry.sh.md"
    class start shFile
    class checks checkNode
    class tag,gh tagNode
    classDef shFile fill:#abe07a,stroke:#3f6212,color:#16280a
    classDef checkNode fill:#9fe8c9,stroke:#0f766e,color:#052e22
    classDef tagNode fill:#f6b8d4,stroke:#be185d,color:#500724
```

Computes the next version with versioner (dogfooding the bundled binary), tags `HEAD`, pushes the tag, and creates a GitHub release — for version tracking only. Unlike the Versioner and Logamuffin tools, RecipeServer ships no binaries or archives in its releases: no `.exe` uploads, no zip archives, just a tag and auto-generated release notes (`gh release create … --generate-notes`).

## Usage

```bash
scripts/release.sh             # compute version, tag, push, gh release create
scripts/release.sh --dry-run   # compute + verify only, touch nothing remote
```

`--dry-run`/`-n` allows a dirty working tree and skips `gh`; a real release requires a clean working tree, `git`, and `gh` authenticated via `gh auth login`. Unknown arguments are a usage error (exit `2`).

## What it does

1. Sources the env cascade via [entry.sh.md](entry.sh.md). Logging goes through `log()` (logamuffin, with the printf fallback).
2. Verifies `git` (and, for a real release, `gh` authentication), finds the repository root with `git rev-parse --show-toplevel`.
3. Requires a clean working tree; `--dry-run` only warns. Fetches tags from origin (warning only in `--dry-run`).
4. Resolves `VERSIONER_BIN` (via the cascade or PATH), checks it is executable, prints its version, and computes the next `VERSION`/`TAG` by running versioner against the repo root. The tag must match `vX.Y.Z.W.V`.
5. Refuses to proceed if the tag already exists locally or on origin.
6. Creates an annotated tag `v<version>`, pushes it, and runs `gh release create <tag> --title "recipeserver <tag>" --generate-notes` (version tracking only, no assets). If a release for the tag already exists, it errors out noting the tag was pushed.

## Caveat

None currently. The entry-point check resolves the repository root as the parent of the `scripts/` directory (the same idiom as the other scripts), so `$SCRIPT_DIR/scripts/entry.sh` points at the real cascade.

## Related pages

- [version.sh.md](version.sh.md) — prints the same computed version
- `tools/versioner/update.sh.md` — refreshing the bundled versioner (not rendered in the site)
- [env.sh.md](env.sh.md) · [entry.sh.md](entry.sh.md)
