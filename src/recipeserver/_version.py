"""Package version lookup shared by the HTML generators.

The package metadata is missing when the code runs from a source tree that
was never installed (for example in tests), so fall back to a placeholder
instead of raising at import time.
"""

try:
    from importlib.metadata import version as _package_version

    PACKAGE_VERSION = _package_version("recipeserver")
except Exception:  # pragma: no cover - package metadata unavailable in tests
    PACKAGE_VERSION = "0.0.0"
