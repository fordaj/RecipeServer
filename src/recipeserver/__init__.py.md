# The package initializer (`src/recipeserver/__init__.py`)

```mermaid
flowchart TD
    console("<img src='barnacle:file-cog.svg' width='20' alt=''/><br/>console script") --> main("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>recipeserver.main()<br/>lazy startup</u>")
    module("<img src='barnacle:terminal.svg' width='20' alt=''/><br/>python -m recipeserver") --> main
    main --> args("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>core.parse_args()</u>")
    args --> log("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>_logger.setup_logger()</u>")
    log --> cfg("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>Configuration.<br/>handle_configuration()</u>")
    cfg --> run("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>core.main(cfg)</u>")
    click args href "core.py.md"
    click log href "_logger.py.md"
    click cfg href "config.py.md"
    click run href "core.py.md"
    class main goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

The package owns one public function, `main()`, which is the console-script
entry point declared in `pyproject.toml` (`recipeserver = "recipeserver:main"`)
and the function [**main**.py.md](__main__.py.md) calls for
`python -m recipeserver`. Both routes therefore execute the same startup
sequence, and the console script works without arguments.

The body imports the rest of the stack only when called. Importing
`recipeserver` — or a leaf module such as `recipeserver.shopping_list` — no
longer loads `core`, `server`, `tray`, `config`, `tkinter`, or `pystray`. This
removes the import cycle that previously routed every module through the
orchestrator. `test/test_startup_entrypoints.py` enforces both properties.

## Related pages

- [core.py.md](core.py.md) — `parse_args()` and `main(cfg)`
- [**main**.md](__main__.py.md) — `python -m recipeserver` entry
- [README.md](README.md) — the package hub
