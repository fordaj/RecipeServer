# The sandwich menu (`src/recipeserver/menu.py`)

```mermaid
flowchart LR
    menu("<img src='barnacle:file-code.svg' width='20' alt=''/><br/>sandwich_menu_html(include_edit_recipe=…)") --> edit("<img src='barnacle:pen-line.svg' width='20' alt=''/><br/><u>Edit Recipe<br/>id=edit-recipe<br/>recipe pages only</u>")
    menu --> config("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>Configuration<br/>data-config=open</u>")
    menu --> source("<img src='barnacle:download.svg' width='20' alt=''/><br/><u>Download Source Archive<br/>data-archive=source</u>")
    menu --> site("<img src='barnacle:download.svg' width='20' alt=''/><br/><u>Download Site Archive<br/>data-archive=site</u>")
    click config href "server.py.md"
    click source href "archive.py.md"
    click site href "archive.py.md"
    class menu,config goFile
    class edit goFile
    class source,site dlNode
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
    classDef dlNode fill:#93e2e2,stroke:#0f766e,color:#042f2e
```

Reusable hamburger menu markup — deliberately independent of any one page. `sandwich_menu_html()` returns the markup, `MENU_CSS_URL`/`MENU_JS_URL` point at the shared stylesheet and script, and colors come from `definitions.css` so the menu picks up light/dark themes automatically. The index page includes the default menu; the recipe page includes the identical menu with `include_edit_recipe=True` to add an **Edit Recipe** entry.

## Public surface

- `sandwich_menu_html(*, include_edit_recipe: bool = False)` — `<nav class="sandwich-menu">` with a toggle button (`aria-expanded`, `aria-haspopup="menu"`) and a hidden `role="menu"` panel containing:
  - **Edit Recipe** — `id="edit-recipe"`, only when `include_edit_recipe=True` (pencil icon). The recipe page passes this flag; `recipe-editor.js` queries `#edit-recipe` to open the recipe editor and closes the menu on the way. It is the first item in the panel. The index page omits it.
  - **Configuration** — `data-config="open"` (opens the configuration dialog; `assets/config-editor.js` drives it)
  - **Download Source Archive** — `data-archive="source"`
  - **Download Site Archive** — `data-archive="site"`

  Plus a `role="status"` live region for menu feedback. The archive entries hit `/api/archive/source` and `/api/archive/site` ([server.py.md](server.py.md), [archive.py.md](archive.py.md)).

- `MENU_CSS_URL` / `MENU_JS_URL` — content-hashed URLs via `versioned_asset_url` ([_version.py.md](_version.py.md)).
- `_menu_icon_html(icon_path, class_name)` — inlines an asset SVG with `currentColor`-friendly markup and `aria-hidden="true"`.

The menu requires a positioned ancestor (e.g. a `position: relative` page header) for the top-left anchoring in `menu.css`.

## Where it is used

[index_html_generator.py.md](index_html_generator.py.md) (toolbar) and [markdown_to_html/page.py.md](markdown_to_html/page.py.md) (recipe page header, with `include_edit_recipe=True`).

## Related pages

- [archive.py.md](archive.py.md) — what the archive items download
- [index_html_generator.py.md](index_html_generator.py.md) — consumer with the default menu
- [markdown_to_html/page.py.md](markdown_to_html/page.py.md) — consumer with the Edit Recipe entry
- [README.md](README.md) — the package hub
