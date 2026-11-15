# The system tray (`src/recipeserver/tray.py`)

```mermaid
flowchart LR
    main["core.main()"] --> tray["Tray(server, on_quit)"]
    tray --> open["Open Recipes<br/>browser → localhost:port"]
    tray --> status["Server: Running/Stopped<br/>Start · Stop"]
    tray --> quit["Quit<br/>shutdown event"]
    click main href "core.py.md"
    click status href "server.py.md"
```

The `pystray`-based tray icon: open the site, see server status, start/stop the server, quit. Created by [core.py.md](core.py.md)'s `main()` after the server starts.

## `Tray`

`__init__(server, on_quit)` builds a `pystray.Icon("RecipeServer", …)` with a menu:

- **Open Recipes** (default action) — opens `http://localhost:<port>` in the browser; the port is read from `server.port` (falls back to 8000).
- **Server: Running/Stopped** — disabled status item, refreshed via `icon.update_menu()` after start/stop.
- **Start Server** / **Stop Server** — visible only when applicable; start failures (e.g. port in use) are logged, and `Server.start()` itself exits the process when the port is taken.
- **Quit** — sets the shutdown event (`on_quit`), which stops the tray and the server.

The icon image is `assets/logo.png` (RGBA). `run()` blocks on the main thread (used on macOS, where the tray must run there); `run_detached()` runs it in the background (used on Windows/Linux, where the main thread polls the quit event instead). `stop()` stops the icon.

## Related pages

- [core.py.md](core.py.md) — constructs and runs the tray
- [server.py.md](server.py.md) — start/stop/is_running semantics
- [README.md](README.md) — the package hub
