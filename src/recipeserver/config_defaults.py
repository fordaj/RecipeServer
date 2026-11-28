"""Authoritative default values for configuration settings (leaf module).

Configuration, the HTTP server, the renderers, and the tray all need these
values when a setting is absent. Defining them once here keeps a default from
silently differing between the persisted configuration, an API response, a
generated page, and the editor UI.
"""

from __future__ import annotations

DEFAULT_RECIPE_SERVER_NAME = "My Recipe Server"
DEFAULT_SERVER_PORT = 8000
DEFAULT_SERVER_BIND_ADDRESS = "0.0.0.0"
MAX_PORT = 65535

DEFAULT_FOOD_COLOR = "#8d5542"

DEFAULT_DICTATION_ENABLED = True
DEFAULT_TRANSCRIPTION_ENDPOINT = "http://localhost:11434"
DEFAULT_TRANSCRIPTION_MODEL = "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0"

# Minutes before unload: -1 never unloads, 0 unloads immediately, N keeps the
# model for N minutes. Stored as text in TOML, like server_port.
DEFAULT_KEEP_ALIVE_MINUTES = "0"
