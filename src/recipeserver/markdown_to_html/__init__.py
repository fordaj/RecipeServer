"""Render recipe Markdown files to full HTML pages.

The pipeline stages live in sibling modules (``quantities``, ``overview``,
``extras``, ``feedback``, ``page``, ``icons``); this package exports the
orchestrator and the package version used on the pages.
"""

from .._version import PACKAGE_VERSION as VERSION
from .converter import MarkdownToHTMLConverter

__all__ = ["MarkdownToHTMLConverter", "VERSION"]
