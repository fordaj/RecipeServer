# AI streaming (`src/recipeserver/ai_streaming.py`)

```mermaid
flowchart TD
    recipe("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>server.py<br/>/api/ai-recipe</u>") --> run
    assistant("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>server.py<br/>/api/ai-assistant</u>") --> run
    run("<img src='barnacle:layers.svg' width='20' alt=''/><br/><u>ai_streaming.py<br/>one SSE lifecycle</u>") --> events("<img src='barnacle:zap.svg' width='20' alt=''/><br/>status · metrics · error · result")
    click recipe href "server.py.md"
    click assistant href "server.py.md"
    class run goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

The single owner of the Server-Sent Events wire format and of the lifecycle
shared by both streamed AI endpoints. [server.py.md](server.py.md) supplies the
response object, the domain generator, and its own non-streaming behavior; it
no longer writes SSE frames or duplicates terminal-event handling.

## Public interface

- `EventStream(wfile)` — `begin(responder)` writes the no-store, close-delimited
  headers; `send(event)` writes one `event:`/`data:` frame; `error(...)` and
  `result(...)` write the two terminal events.
- `StreamClosed` — a browser disconnect during a write.
- `run_stream(wfile, responder, generate, expected_exceptions, error_event,
error_state, result_event, label)` — begin the stream, call the generator
  with `send`, convert expected failures to an error event, unexpected ones to
  a generic error, and a successful result to the terminal event. A disconnect
  ends the stream quietly.

The browser side reads these frames through `assets/sse.js`; the two readers
and this writer are kept compatible by the AI streaming tests.

## Related pages

- [server.py.md](server.py.md) — the two endpoints and their non-stream paths
- [ai_recipe.py.md](ai_recipe.py.md) · [ai_assistant.py.md](ai_assistant.py.md) — the generators
- [README.md](README.md) — the package hub
