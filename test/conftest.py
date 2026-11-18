"""Shared pytest configuration for the suite."""

import pytest


@pytest.fixture(autouse=True)
def isolated_history_directory(tmp_path, monkeypatch):
    """Point the history module at a scratch path.

    Without this, any test that triggers a recipe save would create snapshots
    in the developer's real user-data directory. (The HTTPS module has the
    same guard via RECIPE_SERVER_HTTPS_DIR; see the HTTPS pull request.)
    """
    monkeypatch.setenv("RECIPE_SERVER_HISTORY_DIR", str(tmp_path / "recipe-server-history"))
