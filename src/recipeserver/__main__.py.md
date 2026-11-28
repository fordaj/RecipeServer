# The module entry point (`src/recipeserver/__main__.py`)

```mermaid
flowchart LR
    start("<img src='barnacle:terminal.svg' width='20' alt=''/><br/>python -m recipeserver") --> main("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>recipeserver.main()</u>")
    click main href "__init__.py.md"
    class main goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

Enables `python -m recipeserver`. The module delegates to
[recipeserver.main()](__init__.py.md), which is also the console-script entry
point, so both ways of starting the app run exactly the same sequence:
argument parsing, logger setup, configuration resolution, then the build,
serve, and tray pipeline in [core.py.md](core.py.md).

## Related pages

- [**init**.md](__init__.py.md) — package initializer and console-script entry
- [core.py.md](core.py.md) — `parse_args()` and `main()`
- [config.py.md](config.py.md) — `Configuration` and `handle_configuration()`
- [README.md](README.md) — the package hub
