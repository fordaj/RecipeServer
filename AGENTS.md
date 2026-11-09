# AGENTS.md

## What this is

Local recipe-site generator and HTTP server. It reads a tree of `recipe.md` files, renders each to HTML, builds a searchable `index.html`, and serves the site with in-browser editing of metadata, ratings, and comments. Edits are written back to each recipe's YAML front matter and Markdown body.

There is no CI and no Python linter/typechecker configuration. Python formatting is via Black (line-length 150 in `pyproject.toml` `[tool.black]`) through `./format.sh`, which runs `uv run formattington python src test`. The only other formatter config is `.prettierrc`, which applies to JS/CSS/HTML.

## Commands

- Sync deps: `uv sync` (Python 3.14 required; `uv` owns `.venv`).
- Run: `./serve.sh` (same as `uv run python -m recipeserver`).
- Format: `./format.sh` (same as `uv run formattington python src test`; pass `--check` for a dry-run check).
- Run all tests: `uv run pytest`.
- Focused tests: `uv run pytest test/test_index_html_generator.py test/test_ratings.py`
  - Single test: `uv run pytest test/test_ratings.py::test_validate_ratings_accepts_example_shape_and_decimal_score`
- Runtime logs: `.logs/<argv0>.py.log` in the current directory. Pass `--log-level DEBUG` for more detail.

The repo does not include a test config file. On startup the app reads the recipe source directory from the `source_directory` key in `<user-data>/recipe-server-cfg.toml` (TOML; a legacy `config.txt` is migrated automatically); if that key is missing or points at a non-directory, it opens a Tk directory picker and writes the chosen path to that file. Optional local-model settings live in the same file (`model_endpoint`, `all_purpose_model_name`, and `image_analysis_model`; the legacy keys `model_name` and `server_name` are still read but normalized to the canonical keys on save). If `model_endpoint` is absent, startup asks for it with `input()` (Enter skips); a skipped value is saved so the app does not ask again. All of these values can also be edited in the browser through the **Configuration** entry in the home page's menu (`GET|POST /api/config`); each save triggers a full site rebuild.

## Logging conventions

- The logger is `loguru` (`src/recipeserver/_logger.py`), which does not do printf-style substitution. Never pass format arguments to log calls: `logger.info("... %s", value)` and `logger.info("... {}", value)` print the placeholders literally. Always use f-strings: `logger.info(f"... {value}")` (use `!r` to preserve repr formatting).

## Architecture / flow

- Entrypoint: `src/recipeserver/__main__.py` -> `core.main`. `handle_configuration()` resolves the recipe source directory and optional local-model settings, then `core.main` loads `NewRecipePrompt.md` and `NewRecipeFromImagePrompt.md`, builds `Core`, calls `regen()`, starts `Server`, and runs `Tray`.
- `core.regen()` deletes and recreates the site directory, copies `src/recipeserver/assets`, converts every `recipe.md` under the source tree in parallel, then rebuilds `index.html`.
- The site directory is `platformdirs.user_data_path("recipe-server") / "site"` (macOS: `~/Library/Application Support/recipe-server/site`). It is generated output and is recreated on every `regen()`.
- `markdown_to_html.py` renders a recipe page and injects metadata-derived HTML. `index_html_generator.py` builds the filter/sort index and metadata warnings. `server.py` serves the site and JSON APIs. `metadata_linter.py` owns the required-field list and warning text. `ai_recipe.py` checks a configured OpenAI-compatible local endpoint, fetches URL text, transcribes images via the image analysis model, and drafts recipe Markdown/metadata without writing files.
- APIs: `GET /health`, `GET /api/recipe-folders`, `POST /api/recipe`, `GET /api/ai-status`, `POST /api/ai-recipe`, `GET /api/markdown?path=...`, `GET|POST /api/recipe-editor?path=...`, `GET|POST /api/metadata/<field>?path=...`, and `GET|POST /api/config`. `path` must be a relative `.md` path inside the source directory. Every save regenerates that recipe page and the index; a configuration save triggers a full site rebuild.
- AI generation is opt-in. With no `model_endpoint`, the create dialog hides the From text/From URL/From Image controls. A configured but unreachable endpoint shows them disabled. `NewRecipePrompt.md` supplies the system prompt for drafting and `NewRecipeFromImagePrompt.md` supplies the transcription prompt, both re-read on every run. For images, `POST /api/ai-recipe` accepts `inputType=image` as multipart with an `image` file; the image analysis model transcribes it and the all-purpose model drafts from the transcription.
- Generated pages use root-absolute URLs such as `/assets/...` and `/recipe-dir/recipe.html`, so they must be served from the site root (port 8000); opening the files directly will not load their assets.
- Index metadata warnings are hidden by default and shown by the "Metadata Status" toggle. They do not block generation, serving, or saving.

## Recipe data conventions

- A recipe is a directory containing a file named exactly `recipe.md`, plus its images. The source tree shape is preserved under the site directory.
- A recipe page's title comes from the first `# ` heading in the Markdown. The index uses that heading too; if the heading is absent, it falls back to front matter `title`, then the directory name.
- The hero image and accent color use the first image in filename-sorted order from the recipe directory. Supported extensions are defined once in `image_handler.IMAGE_EXTENSIONS`. If a directory has multiple images, that sort order decides which one is the hero and drives the accent color.
- Front matter is YAML. The lint-required fields are `ratings`, `contributor`, `createdOn`, `meals`, `categories`, `makes`, and `difficulty`. "Required" means the index shows a warning; it does not prevent building or saving.
- The canonical field name is plural `categories`. The legacy singular `category` is accepted wherever metadata is read (index, recipe overview, metadata API, editor load) but is normalized to `categories` and removed on save. New code and new recipe data must use `categories`.
- Inline-code quantities become scaler spans (`1/2 cup`, `1 1/2 tbsp`, `1-2 tbsp`, `1 1/2-2 1/2 tbsp`). Unparseable `<code>` produces a lint warning; unit aliases live in `_UNIT_ALIASES` in `markdown_to_html.py`.
- `POST /api/recipe-editor` rewrites the whole `recipe.md` through `python-frontmatter` and updates `updatedOn`. The per-field metadata endpoint rewrites the file but does not update `updatedOn`, so rating/comment activity does not change last-edited sorting.
- KaTeX is vendored under `src/recipeserver/assets/katex`; there is no JS package or build step in this repo.
- Icons are standalone `.svg` files in `src/recipeserver/assets/` (e.g. `chef-hat.svg`, `warning.svg`, `plus.svg`, `chevron-down.svg`). Never embed ad-hoc inline `<svg>` markup — or an encoded `data:image/svg+xml` URI — in Python, JS, or CSS files. Reuse an existing asset or add a new `.svg` file to `assets/` and reference it instead: in Python, read/inline the file via `_read_svg`/`_icon_html` (see `markdown_to_html.py`) or `_icon_path` (see `index_html_generator.py`); in JS, fetch the asset and inline it so `currentColor` styling is preserved; in CSS, use `url("/assets/<name>.svg")`. Vendored KaTeX files under `assets/katex/` are the only exception.

## Intentional design

These choices are deliberate and are not bugs to "fix":

- This is a local desktop app, not a headless service. Startup may open a Tk directory picker, and the process runs a `pystray` tray icon. The server listens on the configured port (`server_port`, default 8000), binds `0.0.0.0`, and has no authentication; the tray opens `http://localhost:<port>`. A port change takes effect on the next start.
- Generated HTML is disposable output. The Markdown files in the source tree are the source of truth, and the site directory is deleted and rebuilt on every startup. Never store source content or manual edits in the site directory.
- The local AI integration is optional and never writes recipe files. Its output only prefills the create dialog; the normal create endpoint is still the only path that saves a new recipe.
- Browser edits are written back to the source Markdown, not to generated HTML. The editor is the only path that updates `updatedOn`.
- Metadata warnings are advisory. Missing required fields are allowed in the data and only surface through the hidden index warning chips.
- Front matter uses `categories`; the singular `category` support is a read-only compatibility path for older recipes, not an alternative naming convention.
- Root-absolute URLs are intentional so generated pages remain independent of where the site is hosted; they require serving from the site root.
