# The index page (`src/recipeserver/index_html_generator.py`)

```mermaid
flowchart TD
    recipes("<img src='barnacle:database.svg' width='20' alt=''/><br/>Recipe triples<br/>(metadata, html_file, title)") --> cards("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>_RecipeCard<br/>title · hero · rating · warnings<br/>food color</u>")
    cards --> page("<img src='barnacle:app-window.svg' width='20' alt=''/><br/><u>index.html<br/>search · sort · filter</u>")
    page --> menu("<img src='barnacle:menu.svg' width='20' alt=''/><br/>sandwich menu<br/>+ Metadata Status toggle")
    click cards href "metadata_linter.py.md"
    click page href "menu.py.md"
    class cards goFile
    class page htmlFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
    classDef htmlFile fill:#ffc48a,stroke:#c2410c,color:#431407
```

Builds `index.html`: the searchable, sortable grid of recipe cards with filter menus, a reviewer filter, and advisory metadata warnings. Called by [core.py.md](core.py.md) after every regeneration (`Core._update_index`); output goes to `<site>/index.html`.

## Key pieces

- `Recipe` — the `(metadata, html_file, title)` triple the converter produces; `IndexHTMLGenerator.add()` collects them before `convert()` renders the page.
- `FILTER_FIELDS` — the multi-select filters in the Advanced section, in display order: meals, cuisine, status, categories, tags, contributors, sourceTitles. `MAX_REVIEW_FILTER_OPTIONS = 30` caps the reviewer dropdown (ranked by number of recipes rated, most active first).
- `_prepare_card(recipe, filter_values)` → `_RecipeCard` — computes everything one card needs: title (heading → front-matter `title` → directory name), hero image URL, the recipe's `--food-color` accent (`food_color` — the same color the recipe page sets, via the shared `get_recipe_accent_color` in [image_handler.py.md](image_handler.py.md)), average rating, filter values, `data-*` attributes, and the metadata warnings from [metadata_linter.py.md](metadata_linter.py.md).
- Card colors: `_recipe_food_color` mirrors the converter's heading color ([converter.py.md](markdown_to_html/converter.py.md)) so each card uses the same color as its recipe page; `_card_color_styles` emits one `--food-color` (plus `--food-color-hover`) rule per distinct `data-food-color` on the `<li>` cards, each with a `prefers-color-scheme: dark` variant mirroring the page default.
- `convert()` — aggregates filter option counts, renders the page shell (`_render_page`), and writes `index.html`.
- Page chrome: `_page_head_html`, `_page_header_html`, `_toolbar_html`, `_results_bar_html`, `_version_footer_html`. The toolbar includes the sandwich menu ([menu.py.md](menu.py.md)), filter menus, and the **Metadata Status** toggle — warnings are advisory and hidden by default.
- The search field sits in a `.speech-input` wrapper with a `.speech-button` next to it: the dictation button that records a search phrase instead of asking for the keyboard. The button is generated `hidden` and only revealed by `assets/speech-button/speech-button.js` when the page was loaded over HTTPS, because the browser only hands out the microphone to secure pages. The recording is transcribed by the server ([transcriber.py.md](transcriber.py.md)). When dictation is disabled in the configuration (`dictation_enabled`, see [config.py.md](config.py.md)), the button, its CSS/JS, and the `.speech-input` wrapper are omitted from the generated page and the search field renders as a plain control.
- Stable test hooks: the search input carries `data-testid="recipe-search"`, the list carries `data-testid="recipe-list"`, every recipe item carries `data-testid="recipe-item"`, and each card carries `data-food-color` holding the recipe page's `--food-color`. The Selenium browser tests under `test/e2e/` select on these.
- Accent color: `_food_color_style` emits a per-page `--food-color` override with a `prefers-color-scheme: dark` variant via [color_utils.py.md](color_utils.py.md); `FOOD_COLOR_HOVER_MIX_PERCENT = 82` weights the hover `color-mix()`. Cards use their own accent instead of the page default: `_card_color_styles` gives every card the color of its recipe page (see the Card colors bullet above).
- Assets URLs are content-hashed via `versioned_asset_url` ([_version.py.md](_version.py.md)); icons are inlined from `assets/*.svg` (never inline ad-hoc SVG). The page also inlines `SERVICE_WORKER_REGISTRATION_SNIPPET`, which registers `assets/sw.js` (scope `/assets/`, cache-first for hashed assets, stale-while-revalidate for recipe images) so a flaky client connection does not lose subresources — browsers do not retry a failed asset request. Pages themselves are never cached by the worker (they are `no-store`).
- The page also loads the AI assistant bubble (`assets/ai-assistant/`, after `icons.js`); the bubble renders itself only when `/api/ai-status` reports the local model is configured. On mobile it hides on scroll-down and returns on scroll-up, and a long press starts dictation when dictation is enabled and the page came over HTTPS ([ai_assistant.py.md](ai_assistant.py.md)).

The filter UI (`data-*` attributes, `filter-*` controls) is consumed by `assets/index.js`; the reviewer filter re-averages ratings per selected reviewer without hiding recipes (that logic is browser-side, not in this file).

## Related pages

- [core.py.md](core.py.md) — calls `add()`/`convert()`
- [metadata_linter.py.md](metadata_linter.py.md) — the warnings rendered on cards
- [menu.py.md](menu.py.md) — the sandwich menu markup used in the toolbar
- [sources.py.md](sources.py.md) — shared source-list rendering rules
- [transcriber.py.md](transcriber.py.md) — the transcription behind the dictation button
- [ai_assistant.py.md](ai_assistant.py.md) — the chat behind the bubble loaded on the page
- [README.md](README.md) — the package hub
