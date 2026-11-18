# Icon loading (`src/recipeserver/markdown_to_html/icons.py`)

```mermaid
flowchart LR
    assets("<img src='barnacle:folder.svg' width='20' alt=''/><br/>assets/*.svg<br/>standalone files") --> read("<img src='barnacle:file-code.svg' width='20' alt=''/><br/>read_svg()<br/>lru_cache")
    read --> html("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>icon_html()<br/>svg markup + class</u>")
    read --> append("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>append_svg_icon()<br/>soup element</u>")
    click html href "page.py.md"
    click append href "overview.py.md"
    class assets folder
    class read,html,append goFile
    classDef folder fill:#f0c558,stroke:#8a6d1c,color:#332a05
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

SVG icons live as standalone `.svg` files in `assets/`. Reading them through this module is the one place the "never embed ad-hoc inline SVG markup" rule is implemented on the Python side (the JS equivalent is `loadSvgIcon` in `assets/icons.js`).

## Public surface

- `ASSETS_DIR` — `src/recipeserver/assets` (resolved from `__file__`).
- Named path constants for every asset icon used by the generators: `GAUGE_SVG`, `CHEF_HAT_SVG`, `POT_SVG`, `TAG_SVG`, `QUILL_SVG`, `UTENSILS_SVG`, `PIN_SVG`, `BOOK_SVG`, `AI_SVG`, `USER_SVG`, `USER_ROUND_SVG`, `LINK_SVG`, `NOTEBOOK_SVG`, `PENCIL_SVG`, `PLUS_SVG`, `ARCHIVE_SVG`, `INFO_SVG`.
- `read_svg(asset_path)` — `lru_cache`d file read.
- `icon_html(asset_path, class_name=None)` — returns the SVG markup, optionally forcing one class name. Used by the page shell and feedback sections.
- `append_svg_icon(parent, path)` — appends the parsed SVG to a soup element with `aria-hidden="true"` and `focusable="false"`. Used for the inline overview/extra icons.

Both helpers raise `ValueError` when the asset contains no `<svg>` element.

## Related pages

- [page.py.md](page.py.md) — shell icons (notebook)
- [overview.py.md](overview.py.md) · [extras.py.md](extras.py.md) · [feedback.py.md](feedback.py.md) — consumers
- [README.md](../README.md) — the package hub
