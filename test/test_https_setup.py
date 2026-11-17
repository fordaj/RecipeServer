"""Tests for the optional HTTPS front-end (https_setup.py).

Unit tests stub the network and the subprocesses; the integration test at
the end drives the real bundled mkcert and Caddy binaries to serve the
library over HTTPS, which is what CI on macOS and Windows verifies.
"""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from recipeserver import https_setup
from recipeserver.config import (
    HTTPS_ENABLED_KEY,
    HTTPS_EXTRA_NAMES_KEY,
    Configuration,
)
from recipeserver.https_setup import (
    HttpsSetupError,
    build_caddyfile,
    collect_san_names,
    parse_extra_names,
    resolve_caddy_binary,
    resolve_mkcert_binary,
    san_signature,
    tailscale_names,
    _usable_ip,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _unverified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


# ----- parse_extra_names -----------------------------------------------------


def test_parse_extra_names_splits_on_commas_whitespace_and_newlines():
    assert parse_extra_names("recipes.example.com, 192.168.1.25\n::1\nalias.local") == [
        "recipes.example.com",
        "192.168.1.25",
        "::1",
        "alias.local",
    ]


def test_parse_extra_names_canonicalises_and_dedupes():
    assert parse_extra_names("Recipes.Example.COM recipes.example.com") == ["recipes.example.com"]


def test_parse_extra_names_allows_wildcards():
    assert parse_extra_names("*.example.com") == ["*.example.com"]


def test_parse_extra_names_empty_value():
    assert parse_extra_names("") == []
    assert parse_extra_names(None) == []
    assert parse_extra_names("   ,  \n ") == []


def test_parse_extra_names_rejects_garbage():
    with pytest.raises(ValueError, match="nope/not-a-host"):
        parse_extra_names("good.example.com, nope/not-a-host")

    with pytest.raises(ValueError, match="host name or IP"):
        parse_extra_names("https://example.com")


def test_usable_ip():
    assert _usable_ip("192.168.1.25")
    assert _usable_ip("100.64.0.9")  # CGNAT-space Tailscale address
    assert _usable_ip("fd7a:115c:a1e0::9")
    assert not _usable_ip("127.0.0.1")
    assert not _usable_ip("::1")
    assert not _usable_ip("169.254.0.1")
    assert not _usable_ip("fe80::1")
    assert not _usable_ip("not-an-ip")


# ----- collect_san_names ------------------------------------------------------


def test_collect_san_names_covers_localhost_hostname_and_interfaces(monkeypatch):
    monkeypatch.setattr(https_setup, "local_interface_addresses", lambda: ["192.168.1.25", "fd7a:115c:a1e0::9"])
    monkeypatch.setattr(https_setup, "tailscale_names", lambda: ([], []))

    sans = collect_san_names("")

    assert sans[0:3] == ["localhost", "127.0.0.1", "::1"]
    hostname = socket.gethostname().strip()
    if hostname:
        assert hostname in sans
    assert "192.168.1.25" in sans
    assert "fd7a:115c:a1e0::9" in sans
    # The mDNS form is only offered when the machine has a bare host name.
    bare = socket.gethostname().strip()
    if bare and "." not in bare:
        assert f"{bare}.local" in sans


def test_collect_san_names_includes_tailscale(monkeypatch):
    monkeypatch.setattr(https_setup, "local_interface_addresses", lambda: [])
    monkeypatch.setattr(https_setup, "tailscale_names", lambda: (["machine.example-tailnet.ts.net"], ["100.64.0.9", "fd7a:115c:a1e0::9"]))

    sans = collect_san_names("")

    assert "machine.example-tailnet.ts.net" in sans
    assert "100.64.0.9" in sans
    assert "fd7a:115c:a1e0::9" in sans


def test_collect_san_names_includes_extra_names_and_dedupes(monkeypatch):
    monkeypatch.setattr(https_setup, "local_interface_addresses", lambda: ["192.168.1.25"])
    monkeypatch.setattr(https_setup, "tailscale_names", lambda: ([], []))

    sans = collect_san_names("192.168.1.25, host.example.com 192.168.1.25")

    assert sans.count("192.168.1.25") == 1
    assert "host.example.com" in sans


def test_collect_san_names_drops_invalid_extra_names(monkeypatch):
    monkeypatch.setattr(https_setup, "local_interface_addresses", lambda: [])
    monkeypatch.setattr(https_setup, "tailscale_names", lambda: ([], []))

    sans = collect_san_names("good.example.com, not/a/host")

    assert "good.example.com" not in sans  # the whole extra value is discarded on error


def test_san_signature_changes_with_the_names():
    before = san_signature(["localhost", "127.0.0.1"])
    after = san_signature(["localhost", "192.168.1.25"])

    assert before != after
    assert san_signature(["localhost", "127.0.0.1"]) == before
    assert san_signature(["a"]) != san_signature(["b"])


# ----- tailscale --------------------------------------------------------------


def test_tailscale_names_parses_dns_name_and_ips(monkeypatch):
    monkeypatch.setattr(
        https_setup,
        "tailscale_status",
        lambda: {"Self": {"DNSName": "my-machine.tail1234.ts.net.", "TailscaleIPs": ["100.64.0.9", "fd7a:115c:a1e0::9"]}},
    )

    names, ips = tailscale_names()

    assert names == ["my-machine.tail1234.ts.net"]
    assert ips == ["100.64.0.9", "fd7a:115c:a1e0::9"]


def test_tailscale_names_without_tailscale(monkeypatch):
    monkeypatch.setattr(https_setup, "tailscale_status", lambda: {})

    assert tailscale_names() == ([], [])


def test_tailscale_status_without_the_cli(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert https_setup.tailscale_status() == {}


def test_tailscale_status_handles_broken_json(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tailscale")

    def broken(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="not json", stderr="")

    monkeypatch.setattr(subprocess, "run", broken)

    assert https_setup.tailscale_status() == {}


# ----- binary resolution -------------------------------------------------------


def test_resolve_caddy_binary_prefers_the_environment_override(tmp_path, monkeypatch):
    override = tmp_path / "caddy"
    override.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("CADDY_BIN", str(override))

    assert resolve_caddy_binary() == override


def test_resolve_caddy_binary_rejects_a_missing_override(monkeypatch):
    monkeypatch.setenv("CADDY_BIN", "/does/not/exist/caddy")

    with pytest.raises(HttpsSetupError, match="CADDY_BIN"):
        resolve_caddy_binary()


def test_resolve_binaries_fall_back_to_the_repo_bundle():
    # Both tools are committed for the current platform, so the fallback
    # must find them with no environment overrides in place.
    assert resolve_caddy_binary().name in ("caddy", "caddy.exe")
    assert resolve_mkcert_binary().name in ("mkcert", "mkcert.exe")


# ----- Caddyfile ----------------------------------------------------------------


def test_build_caddyfile_fronts_the_internal_server():
    cert_file = Path("/tmp/cert dir/cert.pem")
    key_file = Path("/tmp/cert dir/key.pem")
    caddyfile = build_caddyfile(8000, 5123, cert_file, key_file)

    assert "https://:8000" in caddyfile
    assert "admin off" in caddyfile
    assert "auto_https off" in caddyfile
    # Paths are JSON-escaped into the Caddyfile (quoted, backslashes doubled).
    assert f"tls {https_setup._caddyfile_quote(str(cert_file))} {https_setup._caddyfile_quote(str(key_file))}" in caddyfile
    assert "reverse_proxy http://127.0.0.1:5123" in caddyfile
    # The generated comment marks the file as machine-managed.
    assert caddyfile.startswith("# Generated by RecipeServer")


# ----- ensure_certificate ---------------------------------------------------------


def test_ensure_certificate_reuses_a_current_certificate(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    monkeypatch.setattr(https_setup, "collect_san_names", lambda extra=None: ["localhost", "127.0.0.1"])
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/nonexistent/mkcert"))
    monkeypatch.setattr(https_setup, "_cert_needs_renewal", lambda _cert: False)

    directory.mkdir(parents=True)
    (directory / https_setup.CERT_FILENAME).write_text("cert", encoding="utf-8")
    (directory / https_setup.KEY_FILENAME).write_text("key", encoding="utf-8")
    (directory / https_setup.SAN_SIGNATURE_FILENAME).write_text(san_signature(["localhost", "127.0.0.1"]) + "\n", encoding="utf-8")

    result = https_setup.ensure_certificate(SimpleNamespace(https_extra_names=""))

    assert result.cert_file == directory / https_setup.CERT_FILENAME


def test_ensure_certificate_regenerates_when_the_sans_change(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    monkeypatch.setattr(https_setup, "collect_san_names", lambda extra=None: ["localhost", "10.0.0.5"])
    monkeypatch.setattr(https_setup, "ensure_ca_installed", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))

    calls = []

    def fake_run(command, *_args, **_kwargs):
        calls.append(command)
        if "-CAROOT" in command:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        # Emulate mkcert writing the cert files it was pointed at.
        cert_file = Path(command[command.index("-cert-file") + 1])
        key_file = Path(command[command.index("-key-file") + 1])
        cert_file.write_text("cert", encoding="utf-8")
        key_file.write_text("key", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = https_setup.ensure_certificate(SimpleNamespace(https_extra_names=""))

    assert result.sans == ("localhost", "10.0.0.5")
    assert calls and calls[0][0] == str(Path("/fake/mkcert"))
    assert "10.0.0.5" in calls[0]
    assert (directory / https_setup.SAN_SIGNATURE_FILENAME).read_text(encoding="utf-8").strip() == san_signature(["localhost", "10.0.0.5"])


def test_ensure_certificate_reports_mkcert_failure(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    monkeypatch.setattr(https_setup, "collect_san_names", lambda extra=None: ["localhost"])
    monkeypatch.setattr(https_setup, "ensure_ca_installed", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))

    def failing(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", failing)

    with pytest.raises(HttpsSetupError, match="boom"):
        https_setup.ensure_certificate(SimpleNamespace(https_extra_names=""))
    # A failed generation leaves no half-written certificate behind.
    assert not (directory / https_setup.CERT_FILENAME).exists()
    assert not (directory / https_setup.KEY_FILENAME).exists()


# ----- ensure_ca_installed -------------------------------------------------------


def test_ensure_ca_installed_is_silent_once_installed(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    caroot = tmp_path / "caroot"
    caroot.mkdir()
    (caroot / "rootCA.pem").write_text("public-cert", encoding="utf-8")

    monkeypatch.setattr(https_setup, "_run_caroot", lambda _mkcert: caroot)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0))

    directory.mkdir(parents=True)
    (directory / https_setup.CA_MARKER_FILENAME).write_text("installed\n", encoding="utf-8")
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))

    assert https_setup.ensure_ca_installed() == caroot
    assert calls == []  # the CA is trusted already; mkcert -install is not re-run


def test_ensure_ca_installed_runs_mkcert_install_once(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    caroot = tmp_path / "caroot"

    monkeypatch.setattr(https_setup, "_run_caroot", lambda _mkcert: caroot)
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))

    calls = []

    def fake_run(command, *_args, **_kwargs):
        calls.append(command)
        assert command == [str(Path("/fake/mkcert")), "-install"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert https_setup.ensure_ca_installed() == caroot
    assert (directory / https_setup.CA_MARKER_FILENAME).is_file()


def test_ensure_ca_installed_reports_install_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(tmp_path / "https"))
    monkeypatch.setattr(https_setup, "_run_caroot", lambda _mkcert: None)
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))

    with pytest.raises(HttpsSetupError, match="mkcert -install"):
        https_setup.ensure_ca_installed()


# ----- configuration --------------------------------------------------------------


def test_https_disabled_by_default():
    cfg = Configuration()

    assert cfg.https_enabled is False
    assert cfg.https_extra_names == ""


def _load_https_config(tmp_path, monkeypatch, extra_lines=""):
    source = tmp_path / "recipes"
    source.mkdir(exist_ok=True)
    config_file = tmp_path / "recipe-server-cfg.toml"
    config_file.write_text(
        f'source_directory = {json.dumps(str(source))}\nmodel_endpoint = ""\n{extra_lines}',
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)
    config = Configuration()
    config.handle_configuration(config_file)
    return config, config_file


def test_https_enabled_round_trips_through_toml(tmp_path, monkeypatch):
    config, config_file = _load_https_config(tmp_path, monkeypatch)

    values = config.get_config_values()
    assert values[HTTPS_ENABLED_KEY] == "false"
    assert values[HTTPS_EXTRA_NAMES_KEY] == ""

    changed = config.apply_config_values({HTTPS_ENABLED_KEY: "true", HTTPS_EXTRA_NAMES_KEY: "recipes.example.com, 10.0.0.5"})

    assert changed == [HTTPS_ENABLED_KEY, HTTPS_EXTRA_NAMES_KEY]
    assert config.https_enabled is True
    assert config.https_extra_names == "recipes.example.com 10.0.0.5"
    assert Configuration()._parse_toml_config(config_file.read_text(encoding="utf-8"))[1][HTTPS_ENABLED_KEY] == "true"


def test_https_extra_names_load_from_toml(tmp_path, monkeypatch):
    config, _ = _load_https_config(tmp_path, monkeypatch, 'https_enabled = true\nhttps_extra_names = "Recipes.Example.COM, 10.0.0.5"\n')

    assert config.https_enabled is True
    assert config.https_extra_names == "recipes.example.com 10.0.0.5"


def test_https_extra_names_ignores_a_hand_edited_invalid_value(tmp_path, monkeypatch, caplog):
    config, _ = _load_https_config(tmp_path, monkeypatch, 'https_extra_names = "not/a/host"\n')

    assert config.https_extra_names == ""


def test_https_extra_names_validation_rejects_bad_input():
    cfg = Configuration()

    with pytest.raises(ValueError, match="extra certificate names"):
        cfg.apply_config_values({HTTPS_EXTRA_NAMES_KEY: "not/a/host"})


def test_https_enabled_validation_rejects_bad_input():
    cfg = Configuration()

    with pytest.raises(ValueError, match="true or false"):
        cfg.apply_config_values({HTTPS_ENABLED_KEY: "sometimes"})


# ----- server binding --------------------------------------------------------------


def test_server_binds_configured_port_over_plain_http():
    from recipeserver.server import Server

    cfg = Configuration()
    cfg.https_enabled = False
    cfg.server_port = _free_port()

    server = Server(cfg)
    server.start()
    try:
        assert server.scheme == "http"
        assert server.bind_port == cfg.server_port
        with socket.create_connection(("127.0.0.1", cfg.server_port), timeout=2):
            pass
    finally:
        server.stop()


def test_server_binds_ephemeral_loopback_port_in_https_mode():
    from recipeserver.server import Server

    cfg = Configuration()
    cfg.https_enabled = True
    cfg.server_port = _free_port()

    server = Server(cfg)
    server.start()
    try:
        assert server.scheme == "https"
        assert server.bind_port != cfg.server_port
        assert server.bind_port > 0
        # The embedded server is not on the public port.
        with pytest.raises(OSError):
            with socket.create_connection(("127.0.0.1", cfg.server_port), timeout=0.5):
                pass
        with socket.create_connection(("127.0.0.1", server.bind_port), timeout=2):
            pass
    finally:
        server.stop()


def test_set_https_switches_the_listener(tmp_path):
    from recipeserver.server import Server

    cfg = Configuration()
    cfg.https_enabled = False
    cfg.server_port = _free_port()

    server = Server(cfg)
    server.start()
    try:
        assert server.bind_port == cfg.server_port

        server.set_https(True)
        assert server.bind_port != cfg.server_port

        server.set_https(False)
        assert server.bind_port == cfg.server_port
    finally:
        server.stop()


# ----- end-to-end over the real binaries ------------------------------------------


def _mkcert_available() -> bool:
    try:
        resolve_mkcert_binary()
        resolve_caddy_binary()
    except HttpsSetupError:
        return False
    return True


class _EchoHandler(BaseHTTPRequestHandler):
    seen_headers: list[dict] = []

    def do_GET(self):
        _EchoHandler.seen_headers.append({key.lower(): value for key, value in self.headers.items()})
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # silence the default request logging
        pass


@pytest.mark.skipif(not _mkcert_available(), reason="bundled mkcert/caddy binaries not available on this platform")
def test_https_roundtrip_through_caddy(tmp_path, monkeypatch):
    """Serve the library over HTTPS through real mkcert and Caddy binaries."""
    https_dir = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(https_dir))
    monkeypatch.setenv("CAROOT", str(tmp_path / "caroot"))
    # The CA is "installed" here only as a bookkeeping step; mkcert creates
    # an untrusted throwaway CA in the temporary CAROOT for the certificate.
    monkeypatch.setattr(https_setup, "ensure_ca_installed", lambda *_a, **_k: None)

    upstream = ThreadingHTTPServer(("127.0.0.1", _free_port()), _EchoHandler)
    _EchoHandler.seen_headers.clear()
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    cfg = SimpleNamespace(server_port=_free_port(), https_extra_names="")
    try:
        caddy = https_setup.start_https(cfg, upstream.server_address[1])
    except HttpsSetupError as exc:
        upstream.shutdown()
        upstream.server_close()
        pytest.fail(f"HTTPS did not start: {exc}")

    try:
        assert (https_dir / https_setup.CERT_FILENAME).is_file()
        assert (https_dir / https_setup.KEY_FILENAME).is_file()
        assert (https_dir / https_setup.CADDYFILE_FILENAME).is_file()
        with urlopen(f"https://127.0.0.1:{cfg.server_port}/health", timeout=5, context=_unverified_context()) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"status": "ok"}
    finally:
        caddy.stop()
        upstream.shutdown()
        upstream.server_close()

    # Caddy forwards over HTTPS with X-Forwarded-Proto set (this is what
    # gates the dictation button in the browser).
    assert _EchoHandler.seen_headers
    assert _EchoHandler.seen_headers[-1].get("x-forwarded-proto") == "https"


def test_export_root_ca_copies_the_public_certificate(tmp_path, monkeypatch, capsys):
    caroot = tmp_path / "caroot"
    caroot.mkdir()
    (caroot / "rootCA.pem").write_text("public-ca-cert", encoding="utf-8")
    monkeypatch.setattr(https_setup, "_run_caroot", lambda _mkcert: caroot)
    site = tmp_path / "site"
    site.mkdir()

    destination = https_setup.export_root_ca(site, mkcert="/fake/mkcert")

    assert destination == site / https_setup.ROOT_CA_SITE_FILENAME
    assert destination.read_text(encoding="utf-8") == "public-ca-cert"


def test_export_root_ca_missing_ca_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(https_setup, "_run_caroot", lambda _mkcert: None)

    assert https_setup.export_root_ca(tmp_path, mkcert="/fake/mkcert") is None


# ----- runtime reconciliation (Core) -----------------------------------------


class FakeServer:
    def __init__(self, bind_port: int = 8000, running: bool = True, events: list | None = None):
        self._https = False
        self.is_running = running
        self._bind_port = bind_port
        self.mode = "http"
        self.start_calls = 0
        self.stop_calls = 0
        self.events = events if events is not None else []

    @property
    def bind_port(self):
        return self._bind_port

    @property
    def port(self):
        return 8000

    @property
    def scheme(self):
        return "https" if self._https else "http"

    def start(self):
        self.start_calls += 1
        self._bind_port = 45678 if self._https else 8000
        self.is_running = True
        self.events.append("server-start")

    def stop(self):
        self.stop_calls += 1
        self.is_running = False
        self.events.append("server-stop")

    def set_https(self, enabled: bool):
        enabled = bool(enabled)
        mode_changed = enabled != self._https
        self._https = enabled
        self.mode = "https" if enabled else "http"
        self.events.append(f"server-set-https:{enabled}")
        if not mode_changed or not self.is_running:
            # Mirror the real listener contract: without a running listener
            # only the mode is recorded.
            return
        # A real switch rebinds the listener to a new port.
        self.stop()
        self.start()


class FakeCaddy:
    def __init__(self, events: list | None = None):
        self.is_running = True
        self.stop_calls = 0
        self.events = events if events is not None else []

    def stop(self):
        self.is_running = False
        self.stop_calls += 1
        self.events.append("caddy-stop")


def _core(tmp_path):
    from recipeserver import core as core_module
    from recipeserver.core import Core

    cfg = SimpleNamespace(
        source_directory=tmp_path,
        site_directory=tmp_path / "site",
        https_enabled=False,
        dictation_enabled=True,
    )
    core = Core.__new__(Core)  # avoid Configuration requirements
    core.cfg = cfg
    from threading import Lock

    core._regen_lock = Lock()
    core._recipes = {}
    core._server = None
    core._caddy = None
    core._caddy_bind_port = None
    return core_module, core


def test_reconcile_https_noop_keeps_caddy(tmp_path, monkeypatch):
    core_module, core = _core(tmp_path)
    events: list[str] = []
    server = FakeServer(events=events)
    core.attach_server(server)

    created: list[tuple[int, list[str]]] = []

    def fake_start_https(_cfg, bind_port):
        created.append((bind_port, events))
        caddy = FakeCaddy(events)
        events.append("caddy-start")
        return caddy

    monkeypatch.setattr(core_module, "start_https", fake_start_https)

    core._reconcile_https()
    assert created == []
    assert server.mode == "http"

    cfg = core.cfg
    cfg.https_enabled = True
    core._reconcile_https()
    assert created and created[0][0] == 45678
    assert server.mode == "https"
    assert server.bind_port == 45678
    # Python leaves the public port before Caddy takes it.
    assert events.index("server-stop") < events.index("caddy-start")

    # Saving an unrelated configuration change does not bounce Caddy.
    events.clear()
    created.clear()
    core._reconcile_https()
    assert created == []
    assert "caddy-stop" not in events

    cfg.https_enabled = False
    core._reconcile_https()
    assert server.mode == "http"
    assert server.bind_port == 8000
    assert core._caddy is None
    # Caddy releases the public port before Python takes it back.
    assert events.index("caddy-stop") < events.index("server-stop")


def test_reconcile_https_rolls_back_when_caddy_fails(tmp_path, monkeypatch):
    core_module, core = _core(tmp_path)
    events: list[str] = []
    server = FakeServer(events=events)
    core.attach_server(server)

    def fake_start_https(_cfg, _bind_port):
        raise HttpsSetupError("port 8000 is already in use")

    monkeypatch.setattr(core_module, "start_https", fake_start_https)

    core.cfg.https_enabled = True
    with pytest.raises(HttpsSetupError, match="port 8000"):
        core._reconcile_https()

    # Plain HTTP is back on the configured port and no half-started Caddy lingers.
    assert server.mode == "http"
    assert server.bind_port == 8000
    assert server.is_running
    assert core._caddy is None


def test_reconcile_https_with_stopped_server_records_the_mode_only(tmp_path, monkeypatch):
    core_module, core = _core(tmp_path)
    server = FakeServer(running=False)
    core.attach_server(server)

    created = []

    def fake_start_https(_cfg, bind_port):
        created.append(bind_port)
        return FakeCaddy()

    monkeypatch.setattr(core_module, "start_https", fake_start_https)

    core.cfg.https_enabled = True
    core._reconcile_https()

    # Nothing is proxied to, so Caddy is not started; the mode is recorded
    # so the tray's Start brings both up together.
    assert created == []
    assert server.mode == "https"
    assert not server.is_running

    core.start_all()
    # The fake rebinds like the real server: an ephemeral port in HTTPS
    # mode, so Caddy is created against it.
    assert server.start_calls == 1
    assert server.bind_port == 45678
    assert created == [45678]


# ----- renewal ---------------------------------------------------------------


def test_cert_needs_renewal_true_for_expired_cert(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    cert.write_text("cert", encoding="utf-8")
    import _ssl

    monkeypatch.setattr(_ssl, "_test_decode_cert", lambda _path: {"notAfter": "Jan  1 00:00:00 2020 GMT"})

    assert https_setup._cert_needs_renewal(cert) is True


def test_cert_needs_renewal_false_for_long_lived_cert(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    cert.write_text("cert", encoding="utf-8")
    import _ssl

    monkeypatch.setattr(_ssl, "_test_decode_cert", lambda _path: {"notAfter": "Jan  1 00:00:00 2999 GMT"})

    assert https_setup._cert_needs_renewal(cert) is False


def test_cert_needs_renewal_true_for_unreadable_cert(tmp_path):
    cert = tmp_path / "cert.pem"
    cert.write_bytes(b"not a pem")

    assert https_setup._cert_needs_renewal(cert) is True


def test_cert_needs_renewal_false_for_unknown_format(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    cert.write_text("cert", encoding="utf-8")
    import _ssl

    monkeypatch.setattr(_ssl, "_test_decode_cert", lambda _path: {"notAfter": "whenever"})

    assert https_setup._cert_needs_renewal(cert) is False


def test_ensure_certificate_reissues_when_the_cert_nears_expiry(tmp_path, monkeypatch):
    directory = tmp_path / "https"
    monkeypatch.setenv("RECIPE_SERVER_HTTPS_DIR", str(directory))
    monkeypatch.setattr(https_setup, "collect_san_names", lambda extra=None: ["localhost"])
    monkeypatch.setattr(https_setup, "_cert_needs_renewal", lambda _cert: True)
    monkeypatch.setattr(https_setup, "ensure_ca_installed", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(https_setup, "resolve_mkcert_binary", lambda *a, **k: Path("/fake/mkcert"))

    directory.mkdir(parents=True)
    (directory / https_setup.CERT_FILENAME).write_text("cert", encoding="utf-8")
    (directory / https_setup.KEY_FILENAME).write_text("key", encoding="utf-8")
    (directory / https_setup.SAN_SIGNATURE_FILENAME).write_text(san_signature(["localhost"]) + "\n", encoding="utf-8")

    calls = []

    def fake_run(command, *_args, **_kwargs):
        calls.append(command)
        if "-CAROOT" in command:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")
        cert_file = Path(command[command.index("-cert-file") + 1])
        cert_file.write_text("cert-new", encoding="utf-8")
        Path(command[command.index("-key-file") + 1]).write_text("key-new", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    https_setup.ensure_certificate(SimpleNamespace(https_extra_names=""))

    assert [c for c in calls if "-cert-file" in c], "mkcert was not re-run for the near-expiry certificate"


def test_start_caddy_requires_a_running_server(tmp_path, monkeypatch):
    core_module, core = _core(tmp_path)
    server = FakeServer(running=False)
    # The real server reports bind_port == 0 when it is not running.
    server._bind_port = 0
    core.attach_server(server)
    monkeypatch.setattr(core_module, "start_https", lambda *_a, **_k: pytest.fail("start_https must not be called"))

    cfg = core.cfg
    cfg.https_enabled = True
    with pytest.raises(HttpsSetupError, match="not running"):
        core.start_caddy()
