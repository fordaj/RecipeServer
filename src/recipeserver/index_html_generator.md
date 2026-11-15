# The index page (`src/recipeserver/index_html_generator.py`)

Builds `index.html`: the searchable, sortable grid of recipe cards with filter menus, a reviewer filter, and advisory metadata warnings. Called by [core.md](core.md) after every regeneration (`Core._update_index`); output goes to `<site>/index.html`.

## Key pieces

- `Recipe` — the `(metadata, html_file, title)` triple the converter produces; `IndexHTMLGenerator.add()` collects them before `convert()` renders the page.
- `FILTER_FIELDS` — the multi-select filters in the Advanced section, in display order: meals, cuisine, status, categories, tags, contributors, sourceTitles. `MAX_REVIEW_FILTER_OPTIONS = 30` caps the reviewer dropdown (ranked by number of recipes rated, most active first).
- `_prepare_card(recipe, filter_values)` → `_RecipeCard` — computes everything one card needs: title (heading → front-matter `title` → directory name), hero image URL, average rating, filter values, `data-*` attributes, and the metadata warnings from [metadata_linter.md](metadata_linter.md).
- `convert()` — aggregates filter option counts, renders the page shell (`_render_page`), and writes `index.html`.
- Page chrome: `_page_head_html`, `_page_header_html`, `_toolbar_html`, `_results_bar_html`, `_version_footer_html`. The toolbar includes the sandwich menu ([menu.md](menu.md)), filter menus, and the **Metadata Status** toggle — warnings are advisory and hidden by default.
- Stable test hooks: the search input carries `data-testid="recipe-search"`, the list carries `data-testid="recipe-list"`, and every recipe item carries `data-testid="recipe-item"`. The Selenium browser tests under `test/e2e/` select on these.
- Accent color: `_food_color_style` emits a per-page `--food-color` override with a `prefers-color-scheme: dark` variant via [color_utils.md](color_utils.md); `FOOD_COLOR_HOVER_MIX_PERCENT = 82` weights the hover `color-mix()`.
- Assets URLs are content-hashed via `versioned_asset_url` ([_version.md](_version.md)); icons are inlined from `assets/*.svg` (never inline ad-hoc SVG).

The filter UI (`data-*` attributes, `filter-*` controls) is consumed by `assets/index.js`; the reviewer filter re-averages ratings per selected reviewer without hiding recipes (that logic is browser-side, not in this file).

## Related pages

- [core.md](core.md) — calls `add()`/`convert()`
- [metadata_linter.md](metadata_linter.md) — the warnings rendered on cards
- [menu.md](menu.md) — the sandwich menu markup used in the toolbar
- [sources.md](sources.md) — shared source-list rendering rules
- [README.md](README.md) — the package hub
