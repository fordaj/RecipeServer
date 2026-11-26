"""Browser tests for the OIDC gate and its browser-side CSRF support."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from recipeserver.auth_config import AuthSettings
from recipeserver.authorization import AuthManager
from recipeserver.config import Configuration
from recipeserver.core import Core
from recipeserver.oidc import OIDCClient
from recipeserver.server import Server
from recipeserver.session import create_session

from .conftest import _free_port

SECRET = "browser-test-signing-secret"
ISSUER = "https://idp.example.com"
OWNER_SUB = "owner-sub"


class NoDiscoveryOIDC(OIDCClient):
    """Skip provider discovery; these tests only need the signed session."""

    def discover(self):
        pass


@pytest.fixture()
def auth_server(tmp_path, monkeypatch, source_dir):
    """Serve the generated site with authentication enabled, like the app does."""
    site = tmp_path / "site"
    monkeypatch.setattr(Configuration, "site_directory", property(lambda self: site))

    cfg = Configuration()
    cfg.source_directory = source_dir
    cfg.server_port = _free_port()
    core = Core(cfg)
    core.regen()

    settings = AuthSettings(
        enabled=True,
        issuer=ISSUER,
        client_id="recipeserver",
        client_secret="test-client-secret",
        redirect_uri=f"http://127.0.0.1:{cfg.server_port}/api/auth/callback",
        owner_sub=OWNER_SUB,
        session_secret=SECRET,
    )
    auth = AuthManager(settings, oidc_client=NoDiscoveryOIDC(settings), access_path=tmp_path / "access.json")
    server = Server(
        cfg,
        on_markdown_saved=core.on_markdown_save,
        on_config_saved=core.on_config_save,
        on_recipes_deleted=core.on_recipes_deleted,
        auth=auth,
    )
    server.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{cfg.server_port}", settings=settings)
    finally:
        server.stop()


def test_signed_in_page_scripts_send_csrf_token(auth_server, driver):
    """A write from a page script must pass the gate without a hand-built token.

    Page scripts (for example the index's AI recipe generator) deliberately
    post without an X-CSRF-Token header: generated pages are static and shared,
    so only assets/auth/auth.js can know the per-session token. An unknown API
    path answers 404 once the gate allows the request; a missing token would
    answer 403 with "You do not have permission to do that".
    """
    url = auth_server.url
    driver.get(url)

    cookie, _session = create_session(ISSUER, OWNER_SUB, "Owner", SECRET, 60)
    driver.add_cookie({"name": "rs_session", "value": cookie, "path": "/", "httpOnly": True})
    driver.refresh()

    result = driver.execute_async_script("""
        const done = arguments[0];
        fetch("/api/metadata-options", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        })
          .then(async (response) => done({ status: response.status, body: await response.text() }))
          .catch((error) => done({ error: String(error) }));
        """)

    assert "error" not in result, result
    assert result["status"] == 404, result
