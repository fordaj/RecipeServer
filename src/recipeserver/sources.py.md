# Source-list helpers (`src/recipeserver/sources.py`)

```mermaid
flowchart LR
    source("<img src='barnacle:file-text.svg' width='20' alt=''/><br/>front matter<br/>source: {...}") --> norm("<img src='barnacle:file-code.svg' width='20' alt=''/><br/>normalize_sources()<br/>list of dicts")
    norm --> fmt("<img src='barnacle:file-code.svg' width='20' alt=''/><br/>source_format()<br/>lower-cased")
    fmt --> icon("<img src='barnacle:image.svg' width='20' alt=''/><br/><u>source_icon_key()<br/>website · book · ai · user</u>")
    fmt --> title("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>source_title()<br/>title or company</u>")
    click icon href "markdown_to_html/extras.py.md"
    click title href "index_html_generator.py.md"
    class source mdFile
    class norm,fmt,title goFile
    classDef mdFile fill:#dcd6ce,stroke:#6b6255,color:#292524
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

Shared rendering rules for the recipe's `source` front matter, used by both the recipe page and the index card so the two never drift.

## Public surface

- `TITLED_SOURCE_FORMATS = {"website", "book"}` — the formats that show an explicit "Source" detail on the index card.
- `normalize_sources(metadata)` — the `source` metadata as a list of dicts (a single dict is wrapped; non-dict entries dropped).
- `source_format(source)` — lower-cased `format` string.
- `source_title(source)` — best-effort display title: `title`, falling back to `company` for websites.
- `source_icon_key(fmt)` — maps a format to its icon key: `website`/`book`/`ai`, otherwise `user`.

## Where it is used

[markdown_to_html/extras.py.md](markdown_to_html/extras.py.md) renders the per-recipe sources block; [index_html_generator.py.md](index_html_generator.py.md) renders the card's Source detail (only for `TITLED_SOURCE_FORMATS`).

## Related pages

- [markdown_to_html/extras.py.md](markdown_to_html/extras.py.md)
- [index_html_generator.py.md](index_html_generator.py.md)
- [README.md](README.md) — the package hub
