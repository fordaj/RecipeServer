"""Tests for the bundled whisper-server lifecycle.

Covers model-name normalisation, binary resolution, the one-time model
download, and the process lifecycle (spawn, readiness, stop) against a
stub whisper-server — the real binary is exercised end to end by
test_speech_model.py, which is opt-in because it downloads model weights.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from recipeserver import whisper_server
from recipeserver.whisper_server import (
    BINARY_ENV_VAR,
    MODEL_DIR_ENV_VAR,
    WhisperServer,
    WhisperServerUnavailable,
    ensure_model,
    normalize_model_name,
    resolve_whisper_server_binary,
)

# ----- Model name ----- #


def test_normalize_model_name_defaults_to_base():
    assert normalize_model_name(None) == "base"
    assert normalize_model_name("") == "base"
    assert normalize_model_name("   ") == "base"


def test_normalize_model_name_accepts_plain_names():
    assert normalize_model_name("tiny") == "tiny"
    assert normalize_model_name("base.en") == "base.en"
    assert normalize_model_name("small_q8_0") == "small_q8_0"


def test_normalize_model_name_strips_the_ggml_decoration():
    assert normalize_model_name("ggml-tiny.bin") == "tiny"
    assert normalize_model_name("ggml-base.en.bin") == "base.en"


def test_normalize_model_name_rejects_paths():
    for value in ("../etc/passwd", "/usr/bin/python", "a/b", "..", "name with space"):
        with pytest.raises(WhisperServerUnavailable):
            normalize_model_name(value)


# ----- Binary resolution ----- #


def test_resolve_binary_uses_the_explicit_argument(tmp_path: Path):
    binary = tmp_path / "whisper-server"
    binary.write_text("", encoding="utf-8")

    assert resolve_whisper_server_binary(binary) == binary


def test_resolve_binary_rejects_a_missing_explicit_argument(tmp_path: Path):
    with pytest.raises(WhisperServerUnavailable):
        resolve_whisper_server_binary(tmp_path / "nope")


def test_resolve_binary_rejects_a_missing_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(BINARY_ENV_VAR, str(tmp_path / "nope"))

    with pytest.raises(WhisperServerUnavailable):
        resolve_whisper_server_binary()


def test_resolve_binary_uses_the_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    binary = tmp_path / "whisper-server"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv(BINARY_ENV_VAR, str(binary))

    assert resolve_whisper_server_binary() == binary


def test_resolve_binary_finds_the_newest_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    tools = tmp_path / "tools" / "whisper-native"
    for version in ("v1.0.0", "v1.9.5", "v1.2.3"):
        directory = tools / version / "macos-arm64"
        directory.mkdir(parents=True)
        (directory / whisper_server._binary_filename()).write_text("", encoding="utf-8")
    monkeypatch.setattr(whisper_server, "_bundled_tools_root", lambda: tools)
    monkeypatch.setattr(whisper_server, "_platform_dir_name", lambda: "macos-arm64")
    monkeypatch.delenv(BINARY_ENV_VAR, raising=False)

    assert resolve_whisper_server_binary().parent.parent.name == "v1.9.5"


def test_resolve_binary_reports_how_to_fix_it_when_nothing_is_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(whisper_server, "_bundled_tools_root", lambda: tmp_path / "empty")
    monkeypatch.setattr(whisper_server, "_platform_dir_name", lambda: "macos-arm64")
    monkeypatch.setattr(whisper_server.shutil, "which", lambda _name: None)
    monkeypatch.delenv(BINARY_ENV_VAR, raising=False)

    with pytest.raises(WhisperServerUnavailable) as error:
        resolve_whisper_server_binary()

    assert BINARY_ENV_VAR in str(error.value)
    assert "update.sh" in str(error.value)


# ----- Model download ----- #


def test_ensure_model_returns_an_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    existing = model_dir / "ggml-tiny.bin"
    existing.write_bytes(b"weights")
    monkeypatch.setenv(MODEL_DIR_ENV_VAR, str(model_dir))

    assert ensure_model("tiny") == existing


def test_ensure_model_downloads_on_first_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    model_dir = tmp_path / "models"
    monkeypatch.setenv(MODEL_DIR_ENV_VAR, str(model_dir))
    payload = b"ggml-weights" * 1024

    class FakeResponse:
        def __init__(self):
            self._buffer = io.BytesIO(payload)
            self.headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return self._buffer.read(size)

    opened = []

    def fake_urlopen(url, timeout=0):
        opened.append(url)
        return FakeResponse()

    monkeypatch.setattr(whisper_server, "urlopen", fake_urlopen)

    result = ensure_model("tiny")

    assert result == model_dir / "ggml-tiny.bin"
    assert result.read_bytes() == payload
    assert opened == [whisper_server.MODEL_URL_TEMPLATE.format(model="tiny")]
    assert not result.with_name(result.name + ".download").exists()


def test_ensure_model_reports_a_failed_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from urllib.error import URLError

    model_dir = tmp_path / "models"
    monkeypatch.setenv(MODEL_DIR_ENV_VAR, str(model_dir))

    def fake_urlopen(url, timeout=0):
        raise URLError("no route to huggingface.co")

    monkeypatch.setattr(whisper_server, "urlopen", fake_urlopen)

    with pytest.raises(WhisperServerUnavailable) as error:
        ensure_model("tiny")

    assert "ggml-tiny.bin" in str(error.value)
    assert not list(model_dir.glob("*.download"))


# ----- Process lifecycle ----- #


def _write_stub_server(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


STUB_SERVER = """
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({"text": "stub transcript"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""

CRASHING_STUB_SERVER = """
import sys
sys.stderr.write("whisper-server: failed to initialize whisper context\\n")
sys.exit(3)
"""


@pytest.mark.skipif(os.name == "nt", reason="the stub whisper-server relies on a shebang line; Windows uses the real binary in CI")
def test_whisper_server_starts_serves_and_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    stub = _write_stub_server(tmp_path / "whisper-server-stub", STUB_SERVER)
    monkeypatch.setattr(whisper_server, "ensure_model", lambda model=None: Path("ggml-stub.bin"))

    server = WhisperServer(model="tiny", binary=stub, startup_timeout=30)
    server.ensure_running()

    assert server.is_running
    assert server.base_url.startswith("http://127.0.0.1:")

    from urllib.request import urlopen

    with urlopen(f"{server.base_url}/", timeout=5) as response:
        assert response.status == 200

    server.stop()

    assert not server.is_running


@pytest.mark.skipif(os.name == "nt", reason="the stub whisper-server relies on a shebang line; Windows uses the real binary in CI")
def test_whisper_server_reports_an_early_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    stub = _write_stub_server(tmp_path / "whisper-server-stub", CRASHING_STUB_SERVER)
    monkeypatch.setattr(whisper_server, "ensure_model", lambda model=None: Path("ggml-stub.bin"))

    server = WhisperServer(model="tiny", binary=stub, startup_timeout=30)

    with pytest.raises(WhisperServerUnavailable) as error:
        server.ensure_running()

    assert "exited" in str(error.value)
    assert not server.is_running
