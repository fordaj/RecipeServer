# The package initializer (`src/recipeserver/__init__.py`)

```mermaid
flowchart LR
    console("<img src='barnacle:file-cog.svg' width='20' alt=''/><br/>pyproject.toml<br/>console script") --> pkg("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>recipeserver/__init__.py</u>")
    pkg --> core("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>core.py<br/>from .core import *</u>")
    click pkg href "README.md"
    click core href "core.py.md"
    class pkg,core goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

One line: `from .core import *`. It re-exports the public names of [core.py.md](core.py.md) — the `Core` class, `main`, `parse_args`, `get_worker_count`, and the worker-count/poll constants — at package scope.

This is what makes the `recipeserver` console script declared in `pyproject.toml` (`recipeserver = "recipeserver:main"`) work: the entry point resolves `main` straight off the package.

Note the import has side effects you should be aware of: importing `recipeserver` imports `core`, which imports `server`, `tray`, `index_html_generator`, and the rest of the stack, including `pystray` and `tkinter` via `config`. Importing the package is not import-light.

## Related pages

- [core.py.md](core.py.md) — the startup pipeline and `Core`
- [**main**.md](__main__.py.md) — `python -m recipeserver` entry
- [README.md](README.md) — the package hub
