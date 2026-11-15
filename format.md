# The format script (`format.sh`)

Runs [formattington](https://github.com/fordaj/formattington) over the repository with logging via logamuffin. It is the repo's one-command formatter.

## Usage

```bash
./format.sh [--check] [...]
```

All arguments are forwarded to `uv run formattington <args> all --config .formattington.json`. In practice: `./format.sh` to format, `./format.sh --check` for a dry-run check.

The committed `.formattington.json` declares four commands: `prettier` (CSS/JS/HTML/Markdown/YAML), `black` (Python; line-length 150 in `pyproject.toml` `[tool.black]`), `shfmt -i 2` (Bash), and `taplo` (TOML). As described in the root README and AGENTS.md, SVG icons under `src/recipeserver/assets/` are formatted with Prettier's HTML parser, and vendored KaTeX under `assets/katex/` is excluded via `.prettierignore`. `prettier` is PATH-only (`npm install -g prettier`) and `taplo` is expected on PATH; if a tool is missing, formattington exits `127` for that command.

Before formatting, the script sources [scripts/entry.sh](scripts/entry.md) for the `log()` helper, then `cd`s to the repository root so `--config .formattington.json` resolves regardless of the caller's directory.

## Related pages

- [scripts/entry.md](scripts/entry.md) · [scripts/env.md](scripts/env.md)
- [tools/formattington-lite/update.md](tools/formattington-lite/update.md) — the pinned fallback binary
- [README.md](README.md) — the Formattington background
