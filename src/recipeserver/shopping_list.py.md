# Shopping list scraping (`src/recipeserver/shopping_list.py`)

```mermaid
flowchart LR
    pages("<img src='barnacle:app-window.svg' width='20' alt=''/><br/>generated recipe pages<br/>(HTML)") --> scrape("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>scrape_ingredients()</u>")
    scrape --> parse("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>parse_ingredient()<br/>name · unit · range</u>")
    parse --> api("<img src='barnacle:globe.svg' width='20' alt=''/><br/>GET /api/shopping-list")
    api --> browser("<img src='barnacle:globe.svg' width='20' alt=''/><br/>browser<br/>per-recipe scaler + checklist")
    click scrape href "server.py.md"
    click parse href "markdown_to_html/quantities.py.md"
    class pages htmlFile
    class scrape,parse goFile
    classDef htmlFile fill:#ffc48a,stroke:#c2410c,color:#431407
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

Ingredient scraping for the shopping list. The shopping list opens from the index in selection mode; `GET /api/shopping-list?path=…` (repeated) returns each selected recipe's ingredients, and the browser combines them with per-recipe scaling.

The ingredients come from the **generated recipe pages**, not the Markdown: a heading whose text mentions "ingredient" opens an ingredients section, every list item inside the section is an ingredient, and the next heading closes the section again. This module parses the HTML with BeautifulSoup.

## Public surface

- `scrape_ingredients(html)` — walks headings and list items in document order; returns a list of dicts with `html` (inner HTML of the `<li>`, so the caller can render it and keep the `.quantity` spans the recipe scaler needs), `name` (normalized lower-case, punctuation stripped, leading "of" dropped), `unit` (alias-normalized; trailing plural "s" dropped except after "e"/"ss"), and `has_range` (true when the quantity span carries `data-quantity-end`).
- `parse_ingredient(markup)` — the per-item parser used by `scrape_ingredients`. The name and unit say which ingredient it is, so the shopping list can add amounts from several recipes together.
- `HEADING_TAGS`, `INGREDIENT_KEYWORD = "ingredient"`, `_SCRAPE_SELECTOR`, `_NAME_PREFIXES = ("of ",)`, `_PUNCTUATION` — the scraping rules, exported for tests.

## Where it is used

[server.py.md](server.py.md) `_handle_shopping_list_get` — one scrape per selected recipe's generated page. The scaler and the combined-list UI live in `assets/recipe-scaler.js` and `assets/shopping-list/`.

## Related pages

- [server.py.md](server.py.md) — the endpoint
- [markdown_to_html/quantities.py.md](markdown_to_html/quantities.py.md) — produces the `.quantity` spans scraped here
- [README.md](README.md) — the package hub
