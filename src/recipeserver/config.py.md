# Configuration (`src/recipeserver/config.py`)

```mermaid
flowchart TD
    toml("<img src='barnacle:file-cog.svg' width='20' alt=''/><br/>recipe-server-cfg.toml<br/>(user-data dir)") --> cfg("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>Configuration</u>")
    legacy("<img src='barnacle:file-text.svg' width='20' alt=''/><br/>legacy config.txt") -. migrated .-> toml
    missing{{"<img src='barnacle:hexagon.svg' width='20' alt=''/><br/>source_directory<br/>missing/invalid?"}} -->|yes| picker("<img src='barnacle:folder-search.svg' width='20' alt=''/><br/>Tk folder picker")
    picker --> cfg
    toml --> cfg
    cfg --> startup("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>handle_configuration()</u>")
    click startup href "core.py.md"
    click cfg href "server.py.md"
    class cfg,startup goFile
    class missing hexNode
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
    classDef hexNode fill:#ffe08a,stroke:#a16207,color:#422006
```

Everything about the runtime configuration lives here: the `recipe-server-cfg.toml` file in the user-data directory, the legacy `config.txt` migration, the Tk folder picker, the optional local-AI settings, and the prompt files.

## The on-disk files

- Config file: `<user-data>/recipe-server-cfg.toml` (macOS: `~/Library/Application Support/recipe-server/recipe-server-cfg.toml`). A legacy `config.txt` in the same directory is read on startup and rewritten as TOML (the legacy file is then removed).
- Site directory: `user_data_path("recipe-server") / "site"` — generated output, recreated on every regeneration. Never store content there.
- Prompts: `NewRecipePrompt.md` and `NewRecipeFromImagePrompt.md`, re-read on every run so edits take effect on next start.
- Runtime logs: `.logs/<argv0>.py.log` relative to the cwd (see [_logger.py.md](_logger.py.md)).

## `Configuration`

Mutable bag of settings with property setters that normalize and validate (assignment never raises; invalid non-blank typed values fall back to defaults with a logged warning). Keys and their `CONFIG_FIELDS` entries — `recipe_server_name`, `source_directory`, `model_endpoint`, `all_purpose_model_name`, `image_analysis_model`, `server_port` (default 8000), `food_color`, `dictation_enabled` — are the single source of truth for the Configuration editor UI: `field_specs()`, `get_config_values()`, and `apply_config_values()` all derive from `CONFIG_FIELDS`, so adding a field means appending one `ConfigField`.

`dictation_enabled` is the one boolean field. It is stored in the TOML file as a real TOML boolean (`dictation_enabled = true`), round-trips through `get_config_values()` as the string `"true"`/`"false"`, is edited in the UI as a checkbox (`input_type="checkbox"`), and defaults to `true`. `_parse_toml_config` accepts either the TOML boolean or a quoted `"true"`/`"false"` string; `_normalize_dictation_enabled` accepts the usual truthy spellings for hand-edited values. When dictation is saved as disabled, [core.py.md](core.py.md) stops the managed whisper-server ([transcriber.py.md](transcriber.py.md)) and generated index pages omit the dictation button ([index_html_generator.py.md](index_html_generator.py.md)).

Legacy read-only keys: `model_name` → `all_purpose_model_name`, `server_name` → `recipe_server_name` (normalized on save). `categories`-style singular field handling lives in [recipe_utils.py](recipe_utils.py.md), not here.

## Startup flow

`handle_configuration(optional_config_path=None)` resolves the config file (migrating legacy when present), reads and parses it, resolves the source directory (Tk directory picker when missing/invalid — cancel exits), applies loaded settings (prompting for the Ollama endpoint with `input()` when the key is absent; Enter skips and the empty setting is saved), loads the prompts, and persists everything back to TOML.

## Validation helpers

`_normalize_model_endpoint` (adds a scheme if omitted, requires http/https), `_normalize_server_port` (1–65535), `_normalize_food_color` (`#rgb`/`#rrggbb`, normalized to lowercase `#rrggbb`), `_normalize_dictation_enabled` (TOML boolean or truthy/falsy spelling), `_validate_source_directory` (must be an existing directory). `_parse_toml_config` accepts a bare-integer `server_port` and a boolean `dictation_enabled`; `_parse_config` reads the legacy line-based format.

## Where it is used

[core.py.md](core.py.md) constructs it in `__main__.py` startup; [server.py.md](server.py.md) exposes `GET|POST /api/config` through it; [ai_recipe.py.md](ai_recipe.py.md) reads the model settings via `AIConfigView`.

## Related pages

- [core.py.md](core.py.md) — startup
- [server.py.md](server.py.md) — the configuration API
- [README.md](README.md) — the package hub
