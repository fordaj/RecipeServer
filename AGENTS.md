# AGENTS.md

## What this is

Local recipe-site generator and HTTP server. It reads a tree of `recipe.md` files, renders each to HTML, builds a searchable `index.html`, and serves the site with in-browser editing of metadata, ratings, and comments. Edits are written back to each recipe's YAML front matter and Markdown body.

There is no CI and no Python linter/typechecker/formatter configuration. The only formatter config is `.prettierrc`, which applies to JS/CSS/HTML.

## Commands

- Sync deps: `uv sync` (Python 3.14 required; `uv` owns `.venv`).
- Run: `./serve.sh` (same as `uv run python -m recipeserver`).
- Run all tests: `uv run pytest`.
- Focused tests: `uv run pytest test/test_index_html_generator.py test/test_ratings.py`
  - Single test: `uv run pytest test/test_ratings.py::test_validate_ratings_accepts_example_shape_and_decimal_score`
- Runtime logs: `.logs/<argv0>.py.log` in the current directory. Pass `--log-level DEBUG` for more detail.

The repo does not include a test config file. On startup the app reads the recipe source directory from `<user-data>/config.txt`; if that file is missing, empty, or points at a non-directory, it opens a Tk directory picker and writes the chosen path to that file.

## Architecture / flow

- Entrypoint: `src/recipeserver/__main__.py` -> `core.main`. `handle_configuration()` resolves the recipe source directory, then `core.main` builds `Core`, calls `regen()`, starts `LibraryWatcher`, starts `Server`, and runs `Tray`. Shutdown stops the watcher, tray, and server.
- `core.regen()` deletes and recreates the site directory, copies `src/recipeserver/assets`, converts every `recipe.md` under the source tree in parallel, then rebuilds `index.html`. `Core.refresh_all()` does the same rebuild while holding the regeneration lock.
- `file_watcher.LibraryWatcher` watches the source tree with `watchdog`, filters out hidden/temp/generated paths, debounces event bursts, and calls `Core.handle_file_changes`. `Core` refreshes affected recipes, copies/prunes images, removes deleted recipe pages, rebuilds the index once, and increments `Core.revision`. Directory moves use a full rebuild; directory deletes only rebuild when they contained a tracked recipe.
- `Core._source_signatures` stores SHA-256 hashes for `recipe.md` files and `(mtime_ns, size)` for their images after they are reflected in the site. This skips the app's own browser saves, touch-only `recipe.md` changes, and no-op watcher events. On a transient conversion failure the last good page is kept and the old signature is left in place so the next event retries.
- Watcher startup failures (missing backend, permissions, watch limits) are logged and reported as `False`; the app still serves the site without live sync.
- The site directory is `platformdirs.user_data_path("recipe-server") / "site"` (macOS: `~/Library/Application Support/recipe-server/site`). It is generated output and is recreated by full rebuilds.
- `markdown_to_html.py` renders a recipe page and injects metadata-derived HTML. `index_html_generator.py` builds the filter/sort index and metadata warnings. `server.py` serves the site and JSON APIs. `metadata_linter.py` owns the required-field list and warning text.
- APIs: `GET /api/revision`, `GET /api/markdown?path=...`, `GET|POST /api/recipe-editor?path=...`, and `GET|POST /api/metadata/<field>?path=...`. `path` must be a relative `.md` path inside the source directory. Every save regenerates that recipe page and the index.
- Generated pages use root-absolute URLs such as `/assets/...` and `/recipe-dir/recipe.html`, so they must be served from the site root (port 8000); opening the files directly will not load their assets.
- `assets/live-refresh.js` polls `/api/revision` and reloads the page when it changes. If the recipe editor has unsaved changes (`dialog.dataset.dirty`), it shows a dismissible notice instead of reloading.
- Index metadata warnings are hidden by default and shown by the "Metadata Status" toggle. They do not block generation, serving, or saving.

## Recipe data conventions

- A recipe is a directory containing a file named exactly `recipe.md`, plus its images. The source tree shape is preserved under the site directory.
- A recipe page's title comes from the first `# ` heading in the Markdown. The index uses that heading too; if the heading is absent, it falls back to front matter `title`, then the directory name.
- The hero image and accent color use the first image in filename-sorted order from the recipe directory. Supported extensions are defined once in `image_handler.IMAGE_EXTENSIONS`. If a directory has multiple images, that sort order decides which one is the hero and drives the accent color.
- Front matter is YAML. The lint-required fields are `ratings`, `contributor`, `createdOn`, `meals`, `categories`, `makes`, and `difficulty`. "Required" means the index shows a warning; it does not prevent building or saving.
- The canonical field name is plural `categories`. The legacy singular `category` is accepted wherever metadata is read (index, recipe overview, metadata API, editor load) but is normalized to `categories` and removed on save. New code and new recipe data must use `categories`.
- Inline-code quantities become scaler spans (`1/2 cup`, `1 1/2 tbsp`, `1-2 tbsp`, `1 1/2-2 1/2 tbsp`). Unparseable `<code>` produces a lint warning; unit aliases live in `_UNIT_ALIASES` in `markdown_to_html.py`.
- `POST /api/recipe-editor` rewrites the whole `recipe.md` through `python-frontmatter` and updates `updatedOn`. The per-field metadata endpoint rewrites the file but does not update `updatedOn`, so rating/comment activity does not change last-edited sorting.
- MathJax is vendored under `src/recipeserver/assets/mathjax`; there is no JS package or build step in this repo.

## Intentional design

These choices are deliberate and are not bugs to "fix":

- This is a local desktop app, not a headless service. Startup may open a Tk directory picker, and the process runs a `pystray` tray icon. The server listens on fixed port 8000, binds `0.0.0.0`, and has no authentication; the tray opens `http://localhost:8000`.
- Generated HTML is disposable output. The Markdown files in the source tree are the source of truth, and the site directory is deleted and rebuilt on every startup and on full fallback rebuilds. Never store source content or manual edits in the site directory.
- Live library sync is intentional. External changes are applied incrementally when possible, and the tray **Refresh Library** action is the manual fallback for a missed filesystem event. Browser saves still use the direct save callback; the watcher skips their already-applied source signatures.
- Browser edits are written back to the source Markdown, not to generated HTML. The editor is the only path that updates `updatedOn`.
- Metadata warnings are advisory. Missing required fields are allowed in the data and only surface through the hidden index warning chips.
- Front matter uses `categories`; the singular `category` support is a read-only compatibility path for older recipes, not an alternative naming convention.
- Root-absolute URLs are intentional so generated pages remain independent of where the site is hosted; they require serving from the site root.
