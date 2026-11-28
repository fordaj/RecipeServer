"""The `recipeserver` package and its console-script entry point.

Importing the package is deliberately light: the server, tray, and Tk-based
configuration are only loaded when the application is actually started. This
keeps leaf modules usable without pulling in the whole process stack.
"""

from __future__ import annotations


def main() -> None:
    """Run the application from the console script or ``python -m recipeserver``.

    Startup has one implementation: argument parsing, logging, configuration,
    and the build/serve/tray sequence all live in the modules below. The lazy
    imports keep ``import recipeserver`` cheap and avoid an import cycle
    through the package root.
    """
    from ._logger import setup_logger
    from .config import Configuration
    from .core import main as run_server
    from .core import parse_args

    args = parse_args()
    setup_logger(args.log_level)
    cfg = Configuration()
    cfg.handle_configuration()
    run_server(cfg)
