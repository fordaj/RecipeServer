"""Build & serve harness for the scale tests.

Mirrors the e2e ``recipe_server`` fixture without the browser: a throwaway
source tree is built into a throwaway site directory, ``Core.regen()`` is
timed, and a real ``Server`` is started on an ephemeral loopback port with
its ``/health`` endpoint probed before and after measurements. No port 8000,
no real user data, no tray, no browser.

The site directory is redirected by temporarily replacing
``Configuration.site_directory`` (a read-only property) with one pointing at
the throwaway directory, exactly as the e2e tests redirect it with
``monkeypatch``. The redirect is plain Python so it can be held for the
whole lifetime of a module-scoped measurement run.
"""

from __future__ import annotations

import contextlib
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from recipeserver.config import Configuration
from recipeserver.core import Core, get_worker_count
from recipeserver.server import Server

HEALTH_TIMEOUT_SECONDS = 15.0
HEALTH_POLL_INTERVAL_SECONDS = 0.05


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def override_site_directory(site_dir: Path):
    """Point ``Configuration.site_directory`` at ``site_dir`` until the context exits."""
    original = Configuration.site_directory
    Configuration.site_directory = property(lambda self: site_dir)
    try:
        yield
    finally:
        Configuration.site_directory = original


@dataclass
class BuildResult:
    cfg: Configuration
    core: Core
    site_dir: Path
    wall_seconds: float
    worker_count: int


@dataclass
class ScaleServer:
    server: Server
    url: str
    startup_seconds: float


def build_site(source_dir: Path, site_dir: Path) -> BuildResult:
    """Build the site from ``source_dir`` and return the timed result."""
    cfg = Configuration()
    cfg.source_directory = source_dir
    cfg.server_port = free_port()

    core = Core(cfg)
    start = time.perf_counter()
    core.regen()
    wall_seconds = time.perf_counter() - start

    return BuildResult(
        cfg=cfg,
        core=core,
        site_dir=site_dir,
        wall_seconds=wall_seconds,
        worker_count=get_worker_count(),
    )


def start_server(build: BuildResult) -> ScaleServer:
    """Start the server and time until the first successful ``/health``."""
    server = Server(
        build.cfg,
        on_markdown_saved=build.core.on_markdown_save,
        on_config_saved=build.core.on_config_save,
        on_recipes_deleted=build.core.on_recipes_deleted,
    )
    url = f"http://127.0.0.1:{build.cfg.server_port}"

    start = time.perf_counter()
    server.start()
    try:
        deadline = time.perf_counter() + HEALTH_TIMEOUT_SECONDS
        while True:
            try:
                with urlopen(f"{url}/health", timeout=1.0) as response:
                    if response.status == 200:
                        break
            except Exception:
                if time.perf_counter() > deadline:
                    raise TimeoutError(f"Server did not answer /health within {HEALTH_TIMEOUT_SECONDS:.0f}s")
                time.sleep(HEALTH_POLL_INTERVAL_SECONDS)
    except BaseException:
        server.stop()
        raise

    return ScaleServer(server=server, url=url, startup_seconds=time.perf_counter() - start)


def stop_server(instance: ScaleServer | None) -> None:
    if instance is not None:
        instance.server.stop()
