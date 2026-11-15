# The `recipeserver` package

All of RecipeServer's implementation lives here: the startup pipeline, the `recipe.md` → HTML renderers, the index generator, the HTTP server, the tray, and the asset tree. The console script declared in `pyproject.toml` (`recipeserver = "recipeserver:main"`) resolves through this package.

Looking for the big picture? Start with the root [README.md](../../README.md) and [AGENTS.md](../../AGENTS.md). To render this documentation, see [scripts/docs.md](../../scripts/docs.md).

## Entry points and startup

- [**init**.py](__init__.md) — re-exports `core` at package scope (console script target)
- [**main**.py](__main__.md) — `python -m recipeserver`
- [core.py](core.md) — startup, site regeneration, parallel conversion
- [config.py](config.md) — the TOML configuration, legacy migration, Tk folder picker, prompt loading
- [_logger.py](_logger.md) — loguru setup (`setup_logger`, `LogLevel`)
- [_version.py](_version.md) — `PACKAGE_VERSION`, `versioned_asset_url`

## Rendering pipeline

- [markdown_to_html/**init**.py](markdown_to_html/__init__.md) — package exports (`MarkdownToHTMLConverter`, `VERSION`)
- [markdown_to_html/converter.py](markdown_to_html/converter.md) — orchestrates the recipe-page stages
- [markdown_to_html/page.py](markdown_to_html/page.md) — the HTML page shell
- [markdown_to_html/quantities.py](markdown_to_html/quantities.md) — inline-code quantities → scaler spans
- [markdown_to_html/overview.py](markdown_to_html/overview.md) — rating/makes/difficulty/meals strip
- [markdown_to_html/extras.py](markdown_to_html/extras.md) — contributor, sources, and version blocks
- [markdown_to_html/feedback.py](markdown_to_html/feedback.md) — comments and ratings sections
- [markdown_to_html/icons.py](markdown_to_html/icons.md) — asset SVG loading
- [index_html_generator.py](index_html_generator.md) — the searchable/sortable index and metadata warnings
- [image_handler.py](image_handler.md) — supported images, hero selection, accent colors
- [color_utils.py](color_utils.md) — dark-mode accent remapping

## HTTP and editing

- [server.py](server.md) — `ThreadingHTTPServer`, the `/api/*` routes
- [ai_recipe.py](ai_recipe.md) — optional Ollama integration, recipe drafting
- [metadata_options.py](metadata_options.md) — in-use metadata values for the editor dropdowns
- [metadata_linter.py](metadata_linter.md) — required-field warnings
- [recipe_utils.py](recipe_utils.md) — shared metadata/JSON/markup helpers
- [sources.py](sources.md) — shared `source` front-matter rendering rules
- [shopping_list.py](shopping_list.md) — ingredient scraping for the shopping list
- [archive.py](archive.md) — on-demand 7z archives of source/site
- [menu.py](menu.md) — the sandwich menu markup
- [tray.py](tray.md) — the pystray tray icon

## Also in this tree

- `NewRecipePrompt.md`, `NewRecipeFromImagePrompt.md`, `FindOneForMePrompt.md` — model prompts, loaded at startup, not rendered as documentation
- `assets/` — CSS, JavaScript, icons, fonts, and the vendored KaTeX distribution under `assets/katex/` (third-party; not documented file-by-file)

## Testing

Tests live in `test/` (pytest) and run with `uv run pytest`; they cover the renderers, the APIs, and the tray, and are not documented page-by-page.
