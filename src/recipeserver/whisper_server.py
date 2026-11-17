"""Lifecycle of the bundled ``whisper-server`` process.

RecipeServer talks to a local speech-to-text engine for the dictation
button: the browser records a short clip and ``POST /api/transcribe``
returns its text. The engine is not a Python package — it is the
`whisper-server` binary from [fordaj/whisper-native](https://github.com/fordaj/whisper-native),
bundled under ``tools/whisper-native/<version>/<platform>/`` and refreshed
by ``tools/whisper-native/update.sh``. This module owns that binary:

- locating it (the ``WHISPER_SERVER_BIN`` environment variable, the
  repository bundle, or a ``whisper-server`` on ``PATH``),
- downloading the ggml model weights on first use (they are *not* part of
  the release; they come from Hugging Face, like upstream does),
- starting the server on demand, waiting until it is ready to answer, and
- stopping it again when the app shuts down or dictation is disabled.

The server binds the loopback interface on an ephemeral port and speaks no
authentication, so it is only ever reachable from this machine. It is
started lazily — on the first transcription, or never — so starting the app
never pays for the model load. A lock serialises model loading, server
startup, and shutdown; ``whisper-server`` itself serialises inference.

Tests point ``RECIPE_SERVER_WHISPER_MODEL_DIR`` at a temporary directory to
keep downloaded model weights out of the user data directory, and set
``RECIPE_SERVER_WHISPER_MODEL`` to pick a smaller model.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from platformdirs import user_data_path
from threading import RLock, Thread
from urllib.error import URLError
from urllib.request import urlopen

from ._logger import logger

# Environment variable that overrides the model name ("tiny", "base",
# "base.en", "small", ...). Any ggml model published by upstream works; the
# file ggml-<name>.bin is downloaded on first use when it is missing.
MODEL_NAME_ENV_VAR = "RECIPE_SERVER_WHISPER_MODEL"

# Environment variable that overrides the directory the model weights live
# in. Defaults to <user-data>/recipe-server/models. Mostly useful in tests.
MODEL_DIR_ENV_VAR = "RECIPE_SERVER_WHISPER_MODEL_DIR"

# Environment variable that points at a whisper-server binary. Wins over the
# bundled repository tools and PATH.
BINARY_ENV_VAR = "WHISPER_SERVER_BIN"

# "base" transcribes short dictation phrases quickly and matches the model
# size the faster-whisper integration used by default.
DEFAULT_MODEL_NAME = "base"

# The release bundles the whisper.cpp server at this relative path under the
# repository root (see tools/whisper-native/update.sh).
BUNDLED_TOOLS_DIR = Path("tools") / "whisper-native"

MODEL_URL_TEMPLATE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"
MODEL_FILENAME_TEMPLATE = "ggml-{model}.bin"

# The model name goes into a URL and a file name, so keep it to a conservative
# alphabet instead of letting it carry path separators.
_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

HOST = "127.0.0.1"

# The model load happens before the server starts listening, so readiness
# doubles as "the model is in memory". Generous, because the first load
# after a download can be slow on a cold disk.
STARTUP_TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 0.2

# How long to wait for the server to exit after it is asked to stop.
STOP_TIMEOUT_SECONDS = 5.0

DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# How many bytes of whisper-server output to keep for error messages.
OUTPUT_TAIL_BYTES = 4096


class WhisperServerUnavailable(RuntimeError):
    """Raised when whisper-server or its model cannot be used."""


def normalize_model_name(name: str | None) -> str:
    """Normalise a model name, rejecting values that are not plain names.

    A blank value falls back to the default. Accepts the full ``ggml-<name>.bin``
    spelling as a convenience and reduces it to ``<name>``.
    """
    model = (name or "").strip()
    if model.lower().startswith("ggml-"):
        model = model[len("ggml-") :]
    if model.lower().endswith(".bin"):
        model = model[: -len(".bin")]
    model = model.strip()
    if not model:
        return DEFAULT_MODEL_NAME
    if not _MODEL_NAME_PATTERN.match(model):
        raise WhisperServerUnavailable(f"Invalid Whisper model name: {name!r} (use letters, digits, dots, dashes and underscores)")
    return model


def _platform_dir_name() -> str:
    system = sys.platform
    if system.startswith("darwin"):
        os_name = "macos"
    elif system.startswith("linux"):
        os_name = "linux"
    elif system.startswith(("win", "msys", "cygwin")):
        os_name = "windows"
    else:
        os_name = system

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine or "unknown"
    return f"{os_name}-{arch}"


def _binary_filename() -> str:
    return "whisper-server.exe" if _platform_dir_name().startswith("windows-") else "whisper-server"


def _version_key(version_dir: Path) -> tuple[int, ...]:
    parts = version_dir.name.lstrip("v").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return ()


def _bundled_tools_root() -> Path:
    """Repository root-anchored path to the bundled whisper-native tools."""
    return Path(__file__).resolve().parents[2] / BUNDLED_TOOLS_DIR


def resolve_whisper_server_binary(binary: Path | str | None = None) -> Path:
    """Locate the whisper-server binary.

    Order: the explicit argument, the ``WHISPER_SERVER_BIN`` environment
    variable, the bundled repository tools (newest version directory wins),
    then ``whisper-server`` on ``PATH``. Raises :class:`WhisperServerUnavailable`
    with an actionable message when nothing usable is found.
    """
    if binary is not None:
        candidate = Path(binary)
        if candidate.is_file():
            return candidate
        raise WhisperServerUnavailable(f"whisper-server binary not found: {candidate}")

    env_binary = os.environ.get(BINARY_ENV_VAR, "").strip()
    if env_binary:
        candidate = Path(env_binary)
        if candidate.is_file():
            return candidate
        raise WhisperServerUnavailable(f"{BINARY_ENV_VAR} points at a missing binary: {candidate}")

    platform_dir = _platform_dir_name()
    binary_name = _binary_filename()
    tools_root = _bundled_tools_root()
    bundled = sorted(tools_root.glob(f"v*/{platform_dir}/{binary_name}"), key=lambda path: _version_key(path.parents[1]))
    for candidate in reversed(bundled):
        if candidate.is_file():
            return candidate

    from_path = shutil.which(binary_name.removesuffix(".exe")) or shutil.which(binary_name)
    if from_path:
        return Path(from_path)

    raise WhisperServerUnavailable(
        f"whisper-server was not found. Expected a bundle at {tools_root}/v*/{platform_dir}/{binary_name} "
        f"(run tools/whisper-native/update.sh to download it), or set {BINARY_ENV_VAR} to a whisper-server binary."
    )


def default_model_directory() -> Path:
    override = os.environ.get(MODEL_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return user_data_path("recipe-server", appauthor=False) / "models"


def ensure_model(model: str | None = None) -> Path:
    """Return the path to the ggml weights, downloading them on first use."""
    model_name = normalize_model_name(model)
    directory = default_model_directory()
    target = directory / MODEL_FILENAME_TEMPLATE.format(model=model_name)

    if target.is_file() and target.stat().st_size > 0:
        return target

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WhisperServerUnavailable(f"Unable to create the Whisper model directory {directory}: {exc}") from exc

    url = MODEL_URL_TEMPLATE.format(model=model_name)
    partial = target.with_name(target.name + ".download")
    logger.info(f"Downloading the Whisper model '{model_name}' from {url} (one-time download)")

    try:
        with urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with partial.open("wb") as file:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    if total and downloaded % (16 * DOWNLOAD_CHUNK_BYTES) < DOWNLOAD_CHUNK_BYTES:
                        logger.info(f"Whisper model download: {downloaded / (1024 * 1024):.0f} of {total / (1024 * 1024):.0f} MiB")
        partial.replace(target)
    except (URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise WhisperServerUnavailable(
            f"Unable to download the Whisper model '{model_name}' from {url}: {exc}. " f"Download it manually and place it at {target}."
        ) from exc

    logger.info(f"Whisper model saved to {target}")
    return target


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def _read_stream(stream, tail: deque) -> None:
    """Drain a process stream into *tail* (and the log) until EOF."""
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            logger.debug(f"whisper-server: {line}")
    except ValueError, OSError:
        # The stream closed while the server was shutting down.
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


class WhisperServer:
    """Start, health-check, and stop the whisper-server subprocess."""

    def __init__(
        self,
        model: str | None = None,
        binary: Path | str | None = None,
        port: int | None = None,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ):
        self.model = normalize_model_name(model or os.environ.get(MODEL_NAME_ENV_VAR))
        self.binary = Path(binary) if binary is not None else None
        self.port = port
        self.startup_timeout = startup_timeout
        self._process: subprocess.Popen | None = None
        self._tail: deque[str] = deque(maxlen=32)
        self._lock = RLock()
        self._reader = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise WhisperServerUnavailable("whisper-server is not running")
        return f"http://{HOST}:{self.port}"

    def _output_tail(self) -> str:
        text = "\n".join(self._tail)
        return text[-OUTPUT_TAIL_BYTES:]

    def _spawn(self, binary: Path, model_path: Path, port: int) -> subprocess.Popen:
        command = [str(binary), "-m", str(model_path), "--host", HOST, "--port", str(port), "-nt"]
        logger.info(f"Starting whisper-server (model '{self.model}') on {HOST}:{port}")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise WhisperServerUnavailable(f"Unable to start whisper-server at {binary}: {exc}") from exc

        self._tail.clear()
        self._reader = Thread(target=_read_stream, args=(process.stdout, self._tail), name="whisper-server-output", daemon=True)
        self._reader.start()
        return process

    def _wait_until_ready(self, process: subprocess.Popen, port: int) -> None:
        deadline = time.monotonic() + self.startup_timeout
        url = f"http://{HOST}:{port}/"
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                tail = self._output_tail()
                message = f"whisper-server exited with code {returncode} during startup"
                if tail:
                    message += f": {tail}"
                raise WhisperServerUnavailable(message)
            try:
                with urlopen(url, timeout=1):
                    # Any HTTP response means the model finished loading.
                    return
            except URLError, OSError:
                time.sleep(POLL_INTERVAL_SECONDS)
        self.stop()
        raise WhisperServerUnavailable(f"whisper-server did not become ready within {self.startup_timeout:.0f} seconds")

    def ensure_running(self) -> "WhisperServer":
        """Start the server if it is not running and wait until it answers."""
        with self._lock:
            if self.is_running:
                return self

            binary = resolve_whisper_server_binary(self.binary)
            model_path = ensure_model(self.model)
            port = self.port or _free_port()
            self._process = self._spawn(binary, model_path, port)
            try:
                self._wait_until_ready(self._process, port)
            except BaseException:
                self.stop()
                raise
            self.port = port
            logger.info(f"whisper-server is ready on {self.base_url}")
            return self

    def stop(self) -> None:
        """Stop the server, escalating to a kill if it ignores terminate."""
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            if process.poll() is None:
                logger.info("Stopping whisper-server")
                try:
                    process.terminate()
                    process.wait(timeout=STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    logger.warning("whisper-server did not stop in time; killing it")
                    process.kill()
                    try:
                        process.wait(timeout=STOP_TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired:
                        logger.error("whisper-server did not exit after being killed")
                except OSError as exc:
                    logger.warning(f"Unable to stop whisper-server: {exc}")
            if self._reader is not None:
                self._reader.join(timeout=1)
                self._reader = None
