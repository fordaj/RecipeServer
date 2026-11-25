import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from recipeserver.auth_config import AuthSettings
from recipeserver.authorization import AuthManager
from recipeserver.oidc import OIDCError, OIDCClient, new_login_flow, read_login_flow
from recipeserver.session import SESSION_COOKIE, parse_cookies

SECRET = "a-long-persistent-signing-secret"


class FakeProvider:
    def __init__(self):
        self.nonce = ""
        self.last_token_body = {}
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_ProviderHandler, self))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def settings(self):
        return AuthSettings(
            enabled=True,
            issuer=self.base,
            client_id="recipeserver",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/auth/callback",
            owner_sub="owner-sub",
            session_secret=SECRET,
        )

    def id_token(self, nonce):
        return jwt.encode(
            {
                "iss": self.base,
                "aud": "recipeserver",
                "sub": "sub-1",
                "name": "Ada",
                "nonce": nonce,
                "iat": 1700000000,
                "exp": 4102444800,
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )


class _ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, provider, *args, **kwargs):
        self.provider = provider
        super().__init__(*args, **kwargs)

    def log_message(self, *_args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        base = self.provider.base
        if path == "/.well-known/openid-configuration":
            self._send(
                {
                    "issuer": base,
                    "authorization_endpoint": f"{base}/authorize",
                    "token_endpoint": f"{base}/token",
                    "jwks_uri": f"{base}/jwks",
                }
            )
            return
        if path == "/jwks":
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.provider.private_key.public_key()))
            key.update(kid="test-key", alg="RS256", use="sig")
            self._send({"keys": [key]})
            return
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/token":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.provider.last_token_body = parse_qs(self.rfile.read(length).decode("utf-8"))
        self._send({"id_token": self.provider.id_token(self.provider.nonce)})


@pytest.fixture
def provider():
    instance = FakeProvider()
    try:
        yield instance
    finally:
        instance.stop()


def test_discovery_token_exchange_and_verification(provider):
    client = OIDCClient(provider.settings())
    client.discover()

    _flow, cookie, challenge = new_login_flow(SECRET, "/")
    flow = read_login_flow(cookie, SECRET)
    provider.nonce = flow["nonce"]
    location = client.authorization_url(flow["state"], flow["nonce"], challenge)
    assert "code_challenge_method=S256" in location
    assert "client_id=recipeserver" in location
    assert "prompt=login" in location

    id_token = client.exchange_code("the-code", flow["verifier"])
    assert provider.last_token_body["code"] == ["the-code"]
    assert provider.last_token_body["code_verifier"] == [flow["verifier"]]
    issuer, subject, name = client.verify_id_token(id_token, flow["nonce"])
    assert (issuer, subject, name) == (provider.base, "sub-1", "Ada")

    with pytest.raises(OIDCError):
        client.verify_id_token(id_token, "the-wrong-nonce")


def test_full_login_flow_and_failures(provider, tmp_path):
    manager = AuthManager(provider.settings(), access_path=tmp_path / "access.json")

    location, flow_cookie = manager.begin_login("/recipes?x=1")
    assert location.startswith(provider.base + "/authorize")
    flow = read_login_flow(flow_cookie, SECRET)
    provider.nonce = flow["nonce"]

    session, session_cookie, next_url = manager.finish_login({"code": ["code"], "state": [flow["state"]]}, flow_cookie)
    assert session.subject == "sub-1"
    assert session.name == "Ada"
    assert next_url == "/recipes?x=1"
    assert SESSION_COOKIE in parse_cookies(f"rs_session={session_cookie}")

    with pytest.raises(OIDCError):
        manager.finish_login({"code": ["code"], "state": ["not-the-state"]}, flow_cookie)
    with pytest.raises(OIDCError):
        manager.finish_login({"error": ["access_denied"]}, flow_cookie)
    with pytest.raises(OIDCError):
        manager.finish_login({"code": ["code"], "state": [flow["state"]]}, None)
