# Startup and site regeneration (`src/recipeserver/core.py`)

The application spine. `main(cfg)` builds the site, starts the HTTP server, and runs the tray; `Core` owns the site directory and the parallel recipe conversion.

## Public surface

- `DEFAULT_WORKERS = 8`, `MAX_WORKERS = 16`, `get_worker_count()` — thread-pool sizing for recipe conversion (`min(MAX_WORKERS, max(DEFAULT_WORKERS, cpu_count))`).
- `QUIT_POLL_INTERVAL_SECONDS = 0.25` — poll interval for the non-macOS shutdown path.
- `Core` — holds `cfg`, a `_regen_lock`, and a `_recipes` map. Methods:
  - `convert_recipe(markdown)` — renders one `recipe.md` to HTML next to `site/` preserving the source tree structure, and copies the recipe's images into the page directory. Rejects anything outside the source directory or not named `recipe.md`.
  - `regen()` / `_regen_locked()` — full rebuild: deletes and recreates the site directory, copies `assets/`, finds every `recipe.md` under the source tree, converts them in parallel, then rebuilds `index.html`. One broken recipe is logged and skipped so the rest of the site still builds.
  - `on_markdown_save(markdown)` — re-render one recipe and rebuild the index (called after editor saves).
  - `on_recipes_deleted(paths)` — drop deleted recipes from the index and unlink their pages.
  - `on_config_save()` — full rebuild after a configuration change.
- `parse_args()` — `--log-level LEVEL` (`-l`), choices from `LogLevel` ([_logger.md](_logger.md)), default `INFO`.
- `main(cfg)` — `Core(cfg)` → `regen()` → `Server(...)` ([server.md](server.md)) → `Tray(...)` ([tray.md](tray.md)). On macOS the tray runs on the main thread; elsewhere it runs detached and this thread polls the shutdown event.

The server binds `0.0.0.0` on the configured port (default 8000); if the port is in use at startup, `Server.start()` logs an error and exits (see [server.md](server.md)).

## Related pages

- [__main__.md](__main__.md) — the `python -m recipeserver` wrapper
- [server.md](server.md) — the HTTP server wired up here
- [tray.md](tray.md) — the tray icon wired up here
- [index_html_generator.md](index_html_generator.md) — builds `index.html`
- [markdown_to_html/converter.md](markdown_to_html/converter.md) — renders each recipe page
- [README.md](README.md) — the package hub
