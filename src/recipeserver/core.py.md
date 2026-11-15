# Startup and site regeneration (`src/recipeserver/core.py`)

```mermaid
flowchart TD
    main["core.main(cfg)"] --> regen["Core.regen()"]
    regen --> convert["parallel convert<br/>recipe.md → html"]
    convert --> index["_update_index()<br/>index.html"]
    main --> server["Server(...)<br/>bind 0.0.0.0:port"]
    main --> tray["Tray(...)<br/>menu · open · quit"]
    click main href "__main__.py.md"
    click convert href "markdown_to_html/converter.py.md"
    click index href "index_html_generator.py.md"
    click server href "server.py.md"
    click tray href "tray.py.md"
```

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
- `parse_args()` — `--log-level LEVEL` (`-l`), choices from `LogLevel` ([_logger.py.md](_logger.py.md)), default `INFO`.
- `main(cfg)` — `Core(cfg)` → `regen()` → `Server(...)` ([server.py.md](server.py.md)) → `Tray(...)` ([tray.py.md](tray.py.md)). On macOS the tray runs on the main thread; elsewhere it runs detached and this thread polls the shutdown event.

The server binds `0.0.0.0` on the configured port (default 8000); if the port is in use at startup, `Server.start()` logs an error and exits (see [server.py.md](server.py.md)).

## Related pages

- [**main**.md](__main__.py.md) — the `python -m recipeserver` wrapper
- [server.py.md](server.py.md) — the HTTP server wired up here
- [tray.py.md](tray.py.md) — the tray icon wired up here
- [index_html_generator.py.md](index_html_generator.py.md) — builds `index.html`
- [markdown_to_html/converter.py.md](markdown_to_html/converter.py.md) — renders each recipe page
- [README.md](README.md) — the package hub
