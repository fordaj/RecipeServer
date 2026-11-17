"""Shared pytest configuration for the suite."""

import pytest


@pytest.fixture(autouse=True)
def isolated_https_directory(tmp_path, monkeypatch):
    """Point the HTTPS module's user-data directory at a scratch path.

    Without this, any test that reaches the HTTPS code path (directly or
    through `Core._reconcile_https`) would create certificate files in the
    developer's real user-data directory and could invoke `mkcert -install`.
    """
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(tmp_path / "recipe-server-https"))
