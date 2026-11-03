# AGENTS.md

## What this is

Local recipe-site generator and HTTP server. It reads a tree of `recipe.md` files, renders each to HTML, builds a searchable `index.html`, and serves the site with in-browser editing of metadata, ratings, and comments (written back to YAML front matter).

No CI, no Python linter/typechecker/formatter config. Only `.prettierrc` applies, to JS/CSS/HTML.

## Commands

- Sync deps: `uv sync` (Python 3.14 required; uv owns `.venv`).
- Run: `./serve.sh` or `uv run python -m recipeserver`.
- Focused tests: `uv run pytest test/test_index_html_generator.py test/test_ratings.py`
  - Single test: `uv run pytest test/test_ratings.py::test_validate_ratings_accepts_example_shape_and_decimal_score`
- `test/config.txt` is gitignored/local; tests that need config pass a path explicitly. On a fresh checkout the app opens a Tk directory picker.
- Runtime logs are written to `.logs/<argv0>.py.log`; use `--log-level DEBUG` for more.

Known baseline: 3 tests in `test/test_index_html_generator.py` fail on `main` because `metadata_linter._REQUIRED_FIELDS` now includes `ratings`/`createdOn`, while the test expectations still assume 5 required fields. Check the linter before assuming your change caused them.

## Architecture / flow

- Entrypoint: `src/recipeserver/__main__.py` -> `core.main`. It builds `Core`, calls `regen()`, starts `Server` on fixed port 8000, then runs `Tray`.
- `core.regen()` deletes and recreates the output site, copies `src/recipeserver/assets`, converts all `recipe.md` files in parallel, then rebuilds `index.html`.
- Generated output lives in the OS user-data dir (macOS: `~/Library/Application Support/recipe-server/site`), not in the repo. The source recipe dir comes from `<user-data>/config.txt`.
- `markdown_to_html.py` renders recipes and injects metadata-derived HTML; `index_html_generator.py` builds the filter/sort index; `server.py` serves the site plus JSON APIs (`/api/markdown`, `/api/recipe-editor`, `/api/metadata/*`); `metadata_linter.py` drives index warnings.
- `metadata.py` (`RecipeMetadata`) is currently unused; live code works on raw frontmatter dicts.
- Generated pages reference absolute `/assets/...` URLs, so test through the server rather than opening files directly.

## Recipe data conventions

- A recipe is a directory containing an exactly-named `recipe.md` plus its images; the source tree shape is preserved under the site dir.
- The recipe title comes from the first `# ` heading in the Markdown, not front matter `title`. Hero image and accent color come from the first image file found in that recipe directory.
- Front matter is YAML. Lint-required fields: `ratings`, `contributor`, `createdOn`, `meals`, `categories`, `makes`, `difficulty`.
- Metadata naming is inconsistent: the editor API uses singular `category`, while the linter/index use `categories`. Be deliberate about which field you read/write.
- Inline-code quantities become scaler spans (`1/2 cup`, `1 1/2 tbsp`, `1-2 tbsp`, `1 1/2-2 1/2 tbsp`). Unparseable `<code>` produces a lint warning; unit aliases live in `_UNIT_ALIASES`.
- Server-side edits rewrite the whole `recipe.md` via `python-frontmatter` and update `updatedOn`.
- MathJax is vendored under `src/recipeserver/assets/mathjax`; there is no JS package/build step in this repo.
