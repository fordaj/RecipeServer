"""Package version and asset URL helpers shared by the HTML generators.

The package metadata is missing when the code runs from a source tree that
was never installed (for example in tests), so fall back to a placeholder
instead of raising at import time.

``versioned_asset_url`` appends a content hash to an asset URL so browsers
pick up changed assets. The hash is derived from the asset bytes on every
call, so the URL always reflects the file currently on disk; no cache is
involved.
"""

import hashlib
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets"

try:
    from importlib.metadata import version as _package_version

    PACKAGE_VERSION = _package_version("recipeserver")
except Exception:  # pragma: no cover - package metadata unavailable in tests
    PACKAGE_VERSION = "0.0.0"


def versioned_asset_url(url: str) -> str:
    """Append a content hash so browsers pick up changed assets."""
    asset_path = ASSETS_DIR / url.removeprefix("/assets/")
    digest = hashlib.sha1(asset_path.read_bytes()).hexdigest()[:10]
    return f"{url}?v={digest}"
