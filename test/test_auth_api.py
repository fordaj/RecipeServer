import json
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest

from recipeserver.auth_config import AuthSettings
from recipeserver.authorization import AuthManager, Permission
from recipeserver.config import CONFIG_FILENAME, Configuration
from recipeserver.oidc import new_login_flow
from recipeserver.server import RecipeRequestHandler
from recipeserver.session import create_session

SECRET = "a-long-persistent-signing-secret"
ISSUER = "https://idp.example.com"
REDIRECT_URI = "https://recipes.example.com/api/auth/callback"


class FakeOIDC:
    """Avoids discovery/network in the HTTP tests; protocol has its own tests."""

    def discover(self):
        pass

    def authorization_url(self, state, nonce, challenge):
        return f"{ISSUER}/authorize?state={quote(state)}&nonce={quote(nonce)}&code_challenge={quote(challenge)}"

    def exchange_code(self, code, verifier):
        raise AssertionError("not used")

    def verify_id_token(self, id_token, nonce):
        raise AssertionError("not used")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def request(base, path, *, method="GET", headers=None, body=None, follow=True):
    opener = build_opener() if follow else build_opener(NoRedirect)
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = Request(base + path, data=body, method=method, headers=request_headers)
    try:
        with opener.open(req) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers), error.read()


@pytest.fixture
def auth_server(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "Cake").mkdir(parents=True)
    (source / "Cake" / "recipe.md").write_text("# Cake\n", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Index</h1>", encoding="utf-8")
    (site / "assets").mkdir()
    (site / "assets" / "icons.js").write_text("// icons", encoding="utf-8")

    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        "\n".join(
            [
                f"source_directory = {json.dumps(str(source))}",
                'model_endpoint = ""',
                'oidc_client_secret = "super-secret-value"',
                f'session_secret = "{SECRET}"',
                'auth_enabled = "true"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("builtins.input", lambda *_: "")
    config = Configuration()
    config.handle_configuration(config_file)

    settings = AuthSettings(
        enabled=True,
        issuer=ISSUER,
        client_id="recipeserver",
        client_secret="super-secret-value",
        redirect_uri=REDIRECT_URI,
        owner_sub="owner-sub",
        session_secret=SECRET,
        session_lifetime_minutes=60,
    )
    manager = AuthManager(settings, oidc_client=FakeOIDC(), access_path=tmp_path / "access.json")
    handler = partial(
        RecipeRequestHandler,
        directory=str(site),
        source_directory=source,
        config=config,
        auth=manager,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", manager, config_file
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def owner_headers():
    cookie, session = create_session(ISSUER, "owner-sub", "Owner", SECRET, 60)
    return {
        "Cookie": f"rs_session={cookie}",
        "X-CSRF-Token": session.csrf_token(SECRET),
        "Origin": "https://recipes.example.com",
    }


def viewer_headers():
    cookie, session = create_session(ISSUER, "viewer-sub", "Viewer", SECRET, 60)
    return {"Cookie": f"rs_session={cookie}", "X-CSRF-Token": session.csrf_token(SECRET)}


def test_status_is_public_and_never_contains_secrets(auth_server):
    base, _manager, _config_file = auth_server

    status, _headers, body = request(base, "/api/auth/status")
    text = body.decode("utf-8")

    assert status == 200
    data = json.loads(text)
    assert data["enabled"] is True
    assert data["authenticated"] is False
    assert data["permission"] == "view"
    for secret in (SECRET, "super-secret-value", "client_secret", "session_secret"):
        assert secret not in text


def test_guest_none_redirects_pages_and_401s_apis_but_assets_stay_public(auth_server):
    base, manager, _config_file = auth_server
    manager.update_access(Permission.NONE, Permission.VIEW)

    status, headers, _body = request(base, "/", follow=False)
    assert status == 302
    assert "/api/auth/login?next=" in headers["Location"]

    status, _headers, body = request(base, "/api/markdown?path=Cake%2Frecipe.md")
    assert status == 401
    assert json.loads(body)["loginUrl"].startswith("/api/auth/login")

    status, headers, _body = request(base, "/", method="HEAD", follow=False)
    assert status == 302
    assert "/api/auth/login" in headers["Location"]

    status, _headers, _body = request(base, "/assets/icons.js")
    assert status == 200


def test_view_permission_allows_browsing_but_not_writes_or_config(auth_server):
    base, manager, _config_file = auth_server
    manager.update_access(Permission.VIEW, Permission.VIEW)
    headers = viewer_headers()

    assert request(base, "/")[0] == 200
    assert request(base, "/api/auth/status", headers=headers)[0] == 200
    assert request(base, "/api/config", headers=headers)[0] == 403
    assert request(base, "/api/markdown", method="POST", headers=headers, body=b"{}")[0] == 403
    # Feedback is deliberately allowed at View level.
    assert request(base, "/api/metadata/comments", method="POST", headers=headers, body=b"{}")[0] in (400, 404, 500)


def test_owner_can_edit_and_config_response_hides_auth_keys(auth_server):
    base, _manager, _config_file = auth_server
    headers = owner_headers()

    status, _headers, body = request(
        base,
        "/api/markdown",
        method="POST",
        headers=headers,
        body=json.dumps({"path": "Cake/recipe.md", "content": "# Cake\n\nUpdated.\n"}).encode("utf-8"),
    )
    assert status == 200, body

    status, _headers, body = request(base, "/api/config", headers=headers)
    assert status == 200
    text = body.decode("utf-8")
    for secret in (SECRET, "super-secret-value", "oidc_client_secret", "session_secret", "auth_enabled"):
        assert secret not in text


def test_csrf_and_origin_are_enforced_on_mutations(auth_server):
    base, _manager, _config_file = auth_server
    cookie, session = create_session(ISSUER, "owner-sub", "Owner", SECRET, 60)
    body = json.dumps({"path": "Cake/recipe.md", "content": "# Cake\n\nCSRF.\n"}).encode("utf-8")

    without_token = {"Cookie": f"rs_session={cookie}", "Origin": "https://recipes.example.com"}
    assert request(base, "/api/markdown", method="POST", headers=without_token, body=body)[0] == 403

    cross_origin = {
        "Cookie": f"rs_session={cookie}",
        "X-CSRF-Token": session.csrf_token(SECRET),
        "Origin": "https://evil.example",
    }
    assert request(base, "/api/markdown", method="POST", headers=cross_origin, body=body)[0] == 403

    assert request(base, "/api/markdown", method="POST", headers=owner_headers(), body=body)[0] == 200


def test_access_settings_persist(auth_server):
    base, _manager, config_file = auth_server
    payload = json.dumps({"guest": "none", "authenticated": "view"}).encode("utf-8")

    status, _headers, body = request(base, "/api/auth/settings", method="POST", headers=owner_headers(), body=payload)
    assert status == 200, body
    assert config_file.parent.joinpath("access.json").read_text(encoding="utf-8").strip().find('"none"') >= 0
    assert request(base, "/", follow=False)[0] == 302


def test_login_and_logout_cookies(auth_server):
    base, _manager, _config_file = auth_server

    status, headers, _body = request(base, "/api/auth/login?next=%2Findex.html", follow=False)
    assert status == 302
    assert headers["Location"].startswith(ISSUER + "/authorize")
    assert "rs_oidc_flow=" in headers["Set-Cookie"]

    status, headers, _body = request(base, "/api/auth/logout", method="POST", headers=owner_headers(), body=b"{}")
    assert status == 200
    assert "rs_session=" in headers["Set-Cookie"]
    assert "Max-Age=0" in headers["Set-Cookie"]
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "Secure" in headers["Set-Cookie"]


def test_bad_callback_state_clears_the_flow_cookie(auth_server):
    base, _manager, _config_file = auth_server
    _flow, cookie, _challenge = new_login_flow(SECRET, "/")

    status, headers, _body = request(
        base,
        "/api/auth/callback?code=abc&state=wrong",
        headers={"Cookie": f"rs_oidc_flow={cookie}"},
        follow=False,
    )
    assert status == 400
    assert "rs_oidc_flow=" in headers["Set-Cookie"]
    assert "Max-Age=0" in headers["Set-Cookie"]
