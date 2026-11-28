# Configuration API operations (`src/recipeserver/config_endpoints.py`)

```mermaid
flowchart TD
    config("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>config.py<br/>persisted settings</u>") --> api
    api("<img src='barnacle:layers.svg' width='20' alt=''/><br/><u>config_endpoints.py<br/>read · probe · apply</u>") --> handler("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>server.py<br/>status codes + routing</u>")
    api --> transcribe("<img src='barnacle:sliders-horizontal.svg' width='20' alt=''/><br/>transcription + dictation settings")
    click config href "config.py.md"
    click handler href "server.py.md"
    click transcribe href "transcriber.py.md"
    class api goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

The domain work behind `/api/config` and the live settings the dictation
endpoints need. [server.py.md](server.py.md) still owns routing, size-limit
error responses, and the site rebuild after a save; this module shapes the
payload and applies edits, never writing a response.

## Public interface

- `config_payload(config)` — `{values, fields, models}`; auth keys are still
  excluded because [config.py.md](config.py.md) owns that boundary.
- `probe_configured_models(config)` — best-effort model metadata via
  [ai_recipe.py.md](ai_recipe.py.md), using the canonical defaults from
  [config_defaults.py.md](config_defaults.py.md).
- `apply_config_payload(config, rfile, headers, max_size)` — parse, validate,
  persist, and return `(changed_keys, current_values)`.
- `dictation_enabled(config)` / `transcription_settings(config)` — the live
  values used by `/api/transcribe` and `/api/config/test-transcription`.

## Related pages

- [config.py.md](config.py.md) — persistence and the field registry
- [authorization.py.md](authorization.py.md) — the non-secret auth status payload
- [README.md](README.md) — the package hub
