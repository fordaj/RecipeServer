# Metadata options (`src/recipeserver/metadata_options.py`)

Collects the values already used in the recipe library for the editor's dropdowns — meals, categories, cuisine, tags (multi-value) and status, contributor (single-value) — so the editor can offer them with the number of recipes that use each.

The values are read from the recipe Markdown files on request; they are never hard-coded into generated pages or front matter. The Markdown files stay the source of truth: adding a value to a recipe makes it available to every other recipe right away.

## Public surface

- `MULTI_VALUE_FIELDS = ("meals", "categories", "cuisine", "tags")`, `SINGLE_VALUE_FIELDS = ("status", "contributor")`, `OPTION_FIELDS` — the dropdown fields, in order.
- `collect_metadata_options(source_directory)` — walks `recipe.md` files under the source tree (skipping symlinks), reads front matter, and returns `{field: [{"value": …, "count": n}, …]}` sorted case-insensitively. A recipe counts once per value, even if it repeats it. Legacy singular `category` values count under `categories` (via `read_categories`). Unreadable recipes are logged and skipped.

## Where it is used

[server.md](server.md) `GET /api/metadata-options` serves this directly. The editor widget consumes the response (`assets/recipe-editor/metadata-picker.js`); the counts appear next to each option and on the chips.

## Related pages

- [server.md](server.md) — the endpoint
- [recipe_utils.md](recipe_utils.md) — `read_categories`
- [README.md](README.md) — the package hub
