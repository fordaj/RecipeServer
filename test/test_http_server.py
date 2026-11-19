"""Tests for the HTTP transport behavior of the static site server.

Covers the HTTP/1.1 keep-alive framing (a browser must be able to reuse one
connection for many assets without the server hanging it) and the
configurable bind address.
"""

from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import errno
from threading import Thread
from types import SimpleNamespace
from urllib.request import urlopen
import socket

import pytest

from recipeserver.server import (
    LOCALHOST,
    LISTEN_BACKLOG,
    RecipeRequestHandler,
    Server,
    _RecipeThreadingHTTPServer,
    _ThreadingHTTPServerIPv6,
)


@pytest.fixture()
def site_server(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><body>home</body></html>\n", encoding="utf-8", newline="\n")
    (site / "app.css").write_text("body { color: red; }\n", encoding="utf-8", newline="\n")
    (site / "docs").mkdir()

    source = tmp_path / "source"
    source.mkdir()
    handler = partial(RecipeRequestHandler, directory=str(site), source_directory=source)
    server = ThreadingHTTPServer((LOCALHOST, 0), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"{LOCALHOST}:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_browser_can_reuse_one_connection_for_many_assets(site_server):
    connection = HTTPConnection(site_server, timeout=5)
    connection.request("GET", "/app.css")
    first = connection.getresponse()
    assert first.status == 200
    body = first.read()
    assert body == b"body { color: red; }\n"

    # The same connection is still open and usable: no hang, no reset.
    connection.request("GET", "/index.html")
    second = connection.getresponse()
    assert second.status == 200
    assert second.read() == b"<html><body>home</body></html>\n"
    connection.close()


def test_static_assets_revalidate_and_html_is_never_cached(site_server):
    connection = HTTPConnection(site_server, timeout=5)
    connection.request("GET", "/app.css")
    asset = connection.getresponse()
    assert asset.status == 200
    assert asset.version == 11  # HTTP/1.1
    assert asset.getheader("Cache-Control") == "no-cache"
    assert asset.getheader("Content-Length") == str(len(b"body { color: red; }\n"))
    asset.read()

    connection.request("GET", "/index.html")
    html = connection.getresponse()
    assert html.status == 200
    assert html.getheader("Cache-Control") == "no-store"
    assert html.getheader("Content-Length") is not None
    html.read()
    connection.close()


def test_directory_redirect_carries_content_length(site_server):
    # SimpleHTTPRequestHandler issues a bodyless 301 for a directory without
    # a trailing slash; over HTTP/1.1 that response must declare an empty
    # body or a keep-alive client waits forever.
    connection = HTTPConnection(site_server, timeout=5)
    connection.request("GET", "/docs")
    response = connection.getresponse()
    assert response.status == 301
    assert response.getheader("Content-Length") == "0"
    response.read()
    connection.close()


def test_keep_alive_after_an_error_response(site_server):
    connection = HTTPConnection(site_server, timeout=5)
    connection.request("GET", "/no-such-file.css")
    response = connection.getresponse()
    assert response.status == 404
    response.read()

    connection.request("GET", "/app.css")
    followup = connection.getresponse()
    assert followup.status == 200
    assert followup.read() == b"body { color: red; }\n"
    connection.close()


def test_unparseable_request_receives_a_400_response_not_an_empty_drop(site_server):
    # A client that speaks TLS at this plain-HTTP port hands the parser
    # bytes it cannot understand. The error path used to crash in
    # end_headers (self.path was never set), so the connection closed with
    # zero response bytes — which a proxy in front turns into 502 Bad
    # Gateway. The client must get a well-formed 400 response instead.
    host, port = site_server.split(":")
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        # Three words with an unparsable protocol version: the exact class
        # of bytes the access log shows arriving from clients speaking TLS
        # at this plain-HTTP port.
        sock.sendall(b"GARBAGE ONE FOO\\r\\n\\r\\n")
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    response = b"".join(chunks)
    # The request line cannot be classified, so the response carries no
    # status line (HTTP/0.9 semantics), but the error body must arrive —
    # the connection must not close with zero response bytes, which is
    # what a proxy in front turns into 502 Bad Gateway.
    assert response, "server closed the connection without sending a response"
    assert b"Error code: 400" in response


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOCALHOST, 0))
        return sock.getsockname()[1]


def _server_for(tmp_path, bind_address: str | None = None) -> tuple[Server, int]:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><body>home</body></html>\n", encoding="utf-8", newline="\n")
    port = _free_port()
    cfg = SimpleNamespace(
        site_directory=site,
        source_directory=tmp_path,
        server_port=port,
    )
    # Omit the key entirely to exercise the built-in default bind address.
    if bind_address is not None:
        cfg.server_bind_address = bind_address
    return Server(cfg), port


def test_listen_backlog_exceeds_socketserver_default():
    # The TCPServer default is 5; Windows answers a full backlog with an
    # explicit reset (WSAECONNREFUSED) which a reverse proxy surfaces as
    # 502 Bad Gateway, so the server must enlarge it.
    assert LISTEN_BACKLOG >= 128
    assert _RecipeThreadingHTTPServer.request_queue_size == LISTEN_BACKLOG
    assert _ThreadingHTTPServerIPv6.request_queue_size == LISTEN_BACKLOG


def test_server_binds_wildcard_by_default(tmp_path):
    server, port = _server_for(tmp_path)
    server.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert response.status == 200
    finally:
        server.stop()


def test_server_binds_loopback_when_configured(tmp_path):
    server, port = _server_for(tmp_path, "127.0.0.1")
    server.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert response.status == 200
    finally:
        server.stop()


def test_server_binds_wildcard_when_configured(tmp_path):
    server, port = _server_for(tmp_path, "0.0.0.0")
    server.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert response.status == 200
    finally:
        server.stop()


def test_server_binds_ipv6_loopback_when_configured(tmp_path):
    try:
        server, port = _server_for(tmp_path, "::1")
        server.start()
    except OSError as exc:
        if exc.errno in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
            pytest.skip("IPv6 is not available on this machine")
        raise
    try:
        with urlopen(f"http://[::1]:{port}/", timeout=5) as response:
            assert response.status == 200
    finally:
        server.stop()
