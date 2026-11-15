# Icon loading (`src/recipeserver/markdown_to_html/icons.py`)

SVG icons live as standalone `.svg` files in `assets/`. Reading them through this module is the one place the "never embed ad-hoc inline SVG markup" rule is implemented on the Python side (the JS equivalent is `loadSvgIcon` in `assets/icons.js`).

## Public surface

- `ASSETS_DIR` — `src/recipeserver/assets` (resolved from `__file__`).
- Named path constants for every asset icon used by the generators: `GAUGE_SVG`, `CHEF_HAT_SVG`, `POT_SVG`, `TAG_SVG`, `QUILL_SVG`, `UTENSILS_SVG`, `PIN_SVG`, `BOOK_SVG`, `AI_SVG`, `USER_SVG`, `USER_ROUND_SVG`, `LINK_SVG`, `NOTEBOOK_SVG`, `PENCIL_SVG`, `PLUS_SVG`, `ARCHIVE_SVG`, `INFO_SVG`.
- `read_svg(asset_path)` — `lru_cache`d file read.
- `icon_html(asset_path, class_name=None)` — returns the SVG markup, optionally forcing one class name. Used by the page shell and feedback sections.
- `append_svg_icon(parent, path)` — appends the parsed SVG to a soup element with `aria-hidden="true"` and `focusable="false"`. Used for the inline overview/extra icons.

Both helpers raise `ValueError` when the asset contains no `<svg>` element.

## Related pages

- [page.md](page.md) — shell icons (notebook, pencil)
- [overview.md](overview.md) · [extras.md](extras.md) · [feedback.md](feedback.md) — consumers
- [README.md](../README.md) — the package hub
