"""Optional HTTPS front-end for RecipeServer, built on Caddy and mkcert.

RecipeServer is a local desktop app with no accounts and no authentication,
but some browser features (dictation, for one) need a secure context, and
plain ``http://`` over the network is easy to snoop on anyway. HTTPS stays
opt-in: enable it with the **HTTPS** checkbox in the Configuration dialog (or
``https_enabled = true`` in ``recipe-server-cfg.toml``), and the same
configured server port starts serving HTTPS.

How it works:

- the embedded server binds an ephemeral loopback port instead of the public
  one, so the machine serving the site is reachable only through Caddy;
- [Caddy](https://github.com/caddyserver/caddy) (bundled under
  ``tools/caddy/``, refreshed by ``tools/caddy/update.sh``) listens on the
  configured port on all interfaces and reverse-proxies to the embedded
  server, setting ``X-Forwarded-Proto: https`` so the app can tell the page
  came over HTTPS;
- [mkcert](https://github.com/FiloSottile/mkcert) (bundled under
  ``tools/mkcert/``, refreshed by ``tools/mkcert/update.sh``) generates a
  certificate covering names and addresses that can reach this machine:
  ``localhost``/``127.0.0.1``/``::1``, the machine's host name and
  ``.local`` name, every local IPv4/IPv6 address, the machine's Tailscale
  name and addresses when ``tailscale`` is on ``PATH``, plus any extra names
  from the ``https_extra_names`` configuration key;
- the first time HTTPS is enabled, the mkcert local CA is installed into the
  system (and Firefox, when its trust tooling is present). That is the only
  step that asks for anything: it is a one-time prompt (``sudo`` on macOS,
  administrator rights on Windows), after which enabling HTTPS on any device
  is silent;
- the mkcert public root CA is exported to ``rootCA.pem`` in the site
  directory so other devices can install it (Settings → Wi-Fi/VPN → install
  profile on iOS, then enable full trust; Settings → Encryption on Android;
  the system store on another computer). Never share ``rootCA-key.pem``: it
  is the private key of the CA, not part of the site.

The certificate is regenerated whenever the list of names changes (for
example after a new network connection hands out a new LAN address), so
serving HTTPS from all of the machine's addresses keeps working without a
configuration change. Files live in ``<user-data>/recipe-server/https/``;
tests point ``RECIPE_SERVER_HTTPS_DIR`` at a temporary directory instead, and
``CADDY_BIN``/``MKCERT_BIN`` override the bundled binaries.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import calendar
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from platformdirs import user_data_path
from threading import RLock, Thread
from urllib.error import URLError
from urllib.request import urlopen

from ._logger import logger

# Environment variables that override binary discovery. They win over the
# bundled repository tools and PATH.
CADDY_BIN_ENV_VAR = "CADDY_BIN"
MKCERT_BIN_ENV_VAR = "MKCERT_BIN"

# Environment variable that overrides the directory Caddy, certificates and
# markers live in. Defaults to <user-data>/recipe-server/https. Mostly
# useful in tests.
HTTPS_DIR_ENV_VAR = "RECIPE_SERVER_HTTPS_DIR"

# The release bundles live at these relative paths under the repository root
# (see tools/<name>/update.sh).
BUNDLED_TOOLS_DIR = Path("tools")

HTTPS_DIR_NAME = "https"
CERT_FILENAME = "recipe-server-cert.pem"
KEY_FILENAME = "recipe-server-key.pem"
SAN_SIGNATURE_FILENAME = "recipe-server-sans.txt"
CA_MARKER_FILENAME = "mkcert-ca-installed"
CADDYFILE_FILENAME = "Caddyfile"
ROOT_CA_SITE_FILENAME = "rootCA.pem"

# How long to wait for Caddy to answer HTTPS after it is started. The app is
# already serving the backend, so Caddy only spends time binding its ports;
# the first connection is the expensive one.
STARTUP_TIMEOUT_SECONDS = 20.0
POLL_INTERVAL_SECONDS = 0.2

# How long to wait for Caddy to exit after it is asked to stop.
STOP_TIMEOUT_SECONDS = 5.0

# How long to wait for the `tailscale status` subprocess. Dictation and
# startup must not hang when the tailscale daemon is wedged.
TAILSCALE_TIMEOUT_SECONDS = 5.0

# How long to wait for `mkcert -CAROOT` and for certificate generation.
MKCERT_TIMEOUT_SECONDS = 60.0

# mkcert issues leaf certificates valid for two years and three months. The
# certificate is reissued this far ahead of expiry so devices keep a valid
# cert without user intervention.
CERT_RENEWAL_THRESHOLD_DAYS = 30

# How many bytes of Caddy's output to keep for error messages.
OUTPUT_TAIL_BYTES = 4096

_HOST_PATTERN = re.compile(r"(?i)^(\*\.)?[0-9a-z_-]([0-9a-z._-]*[0-9a-z_-])?$")


class HttpsSetupError(RuntimeError):
    """Raised when HTTPS cannot be set up or started."""


@dataclass(frozen=True)
class HttpsCertificate:
    """Paths and names baked into the generated certificate."""

    cert_file: Path
    key_file: Path
    sans: tuple[str, ...]
    root_ca_file: Path | None


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


def _binary_filename(name: str) -> str:
    return f"{name}.exe" if _platform_dir_name().startswith("windows-") else name


def _version_key(version_dir: Path) -> tuple[int, ...]:
    parts = version_dir.name.lstrip("v").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return ()


def _bundled_tools_root() -> Path:
    """Repository root-anchored path to the bundled tools directory."""
    return Path(__file__).resolve().parents[2] / BUNDLED_TOOLS_DIR


def _resolve_binary(kind: str, binary: Path | str | None = None) -> Path:
    """Locate the named tool, with an actionable error when it is missing.

    Order: the explicit argument, the ``<KIND>_BIN`` environment variable,
    the bundled repository tools (newest version directory wins), then a
    ``<kind>`` on ``PATH``.
    """
    binary_name = _binary_filename(kind)
    env_var = f"{kind.upper()}_BIN"
    if binary is not None:
        candidate = Path(binary)
        if candidate.is_file():
            return candidate
        raise HttpsSetupError(f"{kind} not found: {candidate}")

    env_binary = os.environ.get(env_var, "").strip()
    if env_binary:
        candidate = Path(env_binary)
        if candidate.is_file():
            return candidate
        raise HttpsSetupError(f"{env_var} points at a missing binary: {candidate}")

    platform_dir = _platform_dir_name()
    tools_root = _bundled_tools_root() / kind
    bundled = sorted(tools_root.glob(f"v*/{platform_dir}/{binary_name}"), key=lambda path: _version_key(path.parents[1]))
    for candidate in reversed(bundled):
        if candidate.is_file():
            return candidate

    from_path = shutil.which(kind) or shutil.which(binary_name)
    if from_path:
        return Path(from_path)

    raise HttpsSetupError(
        f"{kind} was not found. Expected a bundle at {tools_root}/v*/{platform_dir}/{binary_name} "
        f"(run tools/{kind}/update.sh to refresh it), or set {env_var} to a {kind} binary."
    )


def resolve_caddy_binary(binary: Path | str | None = None) -> Path:
    """Locate the caddy binary (see :func:`_resolve_binary`)."""
    return _resolve_binary("caddy", binary)


def resolve_mkcert_binary(binary: Path | str | None = None) -> Path:
    """Locate the mkcert binary (see :func:`_resolve_binary`)."""
    return _resolve_binary("mkcert", binary)


def https_directory() -> Path:
    override = os.environ.get(HTTPS_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return user_data_path("recipe-server", appauthor=False) / HTTPS_DIR_NAME


def _usable_ip(address: str) -> bool:
    """Keep addresses a dial would actually reach; drop noise."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # Loopback is always in the SAN list; link-local and multicast
    # addresses are not dialable destinations for other devices.
    return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified)


def local_interface_addresses() -> list[str]:
    """IPv4/IPv6 addresses assigned to this machine's network interfaces.

    Tailscale assigns its own address to an interface (usually
    ``tailscale0``); it is intentionally included here, in addition to the
    name from the tailscale CLI, so the certificate covers it even when the
    CLI is not on PATH.
    """
    addresses: list[str] = []
    try:
        import psutil
    except ImportError:
        logger.warning("psutil is not available; HTTPS certificate will not cover this machine's interface addresses")
        try:
            for _family, _kind, _proto, _canonname, sockaddr in socket.getaddrinfo(socket.gethostname(), None):
                address = sockaddr[0].split("%", 1)[0] if sockaddr else ""
                if _usable_ip(address):
                    addresses.append(address)
        except OSError:
            logger.debug("Could not enumerate interface addresses via getaddrinfo")
        return sorted(set(addresses))

    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        logger.debug("Could not enumerate network interfaces")
        return []

    for _name, snics in interfaces.items():
        for snic in snics:
            if snic.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            address = str(snic.address).split("%", 1)[0]
            if _usable_ip(address):
                addresses.append(address)
    return sorted(set(addresses))


def tailscale_status() -> dict:
    """Return ``tailscale status --json`` on this machine, or ``{}``.

    Best effort by design: Tailscale redistributes its machinery across a
    CLI, a daemon and a login, and any of them may be missing or wedged.
    HTTPS setup must never fail because of it, so every failure mode logs
    at debug level and yields ``{}``.
    """
    exe = shutil.which("tailscale")
    if exe is None:
        return {}
    try:
        result = subprocess.run(
            [exe, "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TAILSCALE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug(f"Could not run tailscale status: {exc}")
        return {}
    if result.returncode != 0:
        logger.debug(f"tailscale status exited with code {result.returncode}")
        return {}
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.debug("tailscale status did not produce JSON")
        return {}
    return status if isinstance(status, dict) else {}


def tailscale_names() -> tuple[list[str], list[str]]:
    """Return ``(dns_names, ip_addresses)`` from ``tailscale status --json``."""
    status = tailscale_status()
    names: list[str] = []
    ips: list[str] = []
    self_node = status.get("Self") if status else None
    if not isinstance(self_node, dict):
        return names, ips
    dns_name = str(self_node.get("DNSName") or "").rstrip(".").strip()
    if dns_name:
        names.append(dns_name)
    for raw in self_node.get("TailscaleIPs") or []:
        address = str(raw).split("%", 1)[0].strip()
        if _usable_ip(address):
            ips.append(address)
    return names, ips


def parse_extra_names(value: str | None) -> list[str]:
    """Parse the ``https_extra_names`` value into certificate entries.

    Accepts host names and IP addresses separated by commas, whitespace or
    new lines. Raises ``ValueError`` with a user-facing message when an
    entry is neither; callers that collect certificate names treat extra
    names as validated input, and the configuration validators use this to
    reject bad input in the dialog.
    """
    names: list[str] = []
    for token in re.split(r"[,\s]+", value or ""):
        token = token.strip()
        if not token:
            continue
        try:
            ip = ipaddress.ip_address(token.split("%", 1)[0])
        except ValueError:
            ip = None
        if ip is not None:
            names.append(str(ip))
            continue
        if _HOST_PATTERN.match(token):
            names.append(token.lower())
            continue
        raise ValueError(
            f"Invalid host name or IP address in extra certificate names: {token!r} (use names like recipes.example.com or addresses like 192.168.1.25)"
        )
    return list(dict.fromkeys(names))


def collect_san_names(extra_names: str | None = None) -> list[str]:
    """Return the de-duplicated list of names the certificate must cover."""
    names: list[str] = ["localhost", "127.0.0.1", "::1"]

    hostname = socket.gethostname().strip()
    if hostname:
        names.append(hostname)
        if "." not in hostname:
            # The mDNS form peers use when this machine registers itself,
            # which is what <hostname>.local resolves to.
            names.append(f"{hostname}.local")

    names.extend(local_interface_addresses())

    ts_names, ts_ips = tailscale_names()
    names.extend(ts_names)
    names.extend(ts_ips)

    try:
        names.extend(parse_extra_names(extra_names))
    except ValueError:
        # The configuration validators reject bad extra names at save time;
        # a hand-edited TOML with an invalid entry must not take the site
        # down, so it is dropped with a warning instead.
        logger.warning("Ignoring invalid https_extra_names value; the certificate will not cover it")

    return list(dict.fromkeys(names))


def san_signature(sans: Sequence[str]) -> str:
    """Stable signature of a SAN list, used to detect when to re-issue."""
    digest = hashlib.sha256("\n".join(sans).encode("utf-8")).hexdigest()
    return f"v1 {digest}"


def _read_signature_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _cert_needs_renewal(cert_file: Path) -> bool:
    """Whether the certificate cannot be used for another threshold period.

    An unreadable certificate also counts as needing renewal — the failure
    mode of regenerating is harmless when the existing file works.
    """
    try:
        from _ssl import _test_decode_cert

        info = _test_decode_cert(str(cert_file))
    except Exception:
        logger.warning(f"Unable to read the certificate {cert_file}; it will be regenerated")
        return True
    not_after = info.get("notAfter") if isinstance(info, dict) else None
    if not not_after:
        return True
    try:
        expires = calendar.timegm(time.strptime(not_after, "%b %d %H:%M:%S %Y %Z"))
    except ValueError, OverflowError, OSError:
        # Unknown format: keep using the certificate; the SAN signature
        # logic still governs issuance.
        return False
    return expires - time.time() < CERT_RENEWAL_THRESHOLD_DAYS * 24 * 3600


def _run_caroot(mkcert: Path) -> Path | None:
    """Ask mkcert where its CA lives. ``None`` when it cannot be told."""
    try:
        result = subprocess.run(
            [str(mkcert), "-CAROOT"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MKCERT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(f"Could not run {mkcert} -CAROOT: {exc}")
        return None
    path = result.stdout.strip()
    return Path(path) if path else None


def ensure_ca_installed(mkcert: Path | str | None = None) -> Path | None:
    """Make sure the mkcert local CA exists and is trusted by this machine.

    The first call runs ``mkcert -install``, which is the one step of HTTPS
    setup that asks for anything (the user's password, via ``sudo`` on
    macOS; administrator rights on Windows). Later calls are silent: a
    marker file in the HTTPS directory remembers that the CA was installed,
    and the CA certificate is checked to still exist.

    Returns the mkcert CA directory when it can be determined, else ``None``.
    Raises :class:`HttpsSetupError` when the CA cannot be installed.
    """
    mkcert_path = Path(mkcert) if mkcert is not None else resolve_mkcert_binary()

    directory = https_directory()
    marker = directory / CA_MARKER_FILENAME
    root_ca = None
    caroot = _run_caroot(mkcert_path)
    if caroot is not None:
        root_ca = caroot / "rootCA.pem"
    if marker.is_file() and root_ca is not None and root_ca.is_file():
        return caroot

    logger.info("Installing the mkcert local CA (one time; you may be asked for your password)")
    try:
        result = subprocess.run([str(mkcert_path), "-install"])
    except OSError as exc:
        raise HttpsSetupError(f"Unable to run {mkcert_path} -install: {exc}") from exc
    if result.returncode != 0:
        raise HttpsSetupError(
            f"Unable to install the mkcert local CA (mkcert -install exited with code {result.returncode}). "
            "Run 'mkcert -install' manually (with sudo on macOS, as Administrator on Windows), then try again."
        )
    try:
        directory.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"installed\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"Unable to write the mkcert CA marker {marker}: {exc}")

    if caroot is None:
        caroot = _run_caroot(mkcert_path)
    return caroot


def ensure_certificate(cfg) -> HttpsCertificate:
    """Return a certificate covering every name this machine answers to.

    A fresh certificate is generated only when the name list changed since
    the last generation, so restarts do not churn the files (or require the
    CA) more than needed.
    """
    sans = collect_san_names(getattr(cfg, "https_extra_names", "") or "")
    mkcert_path = resolve_mkcert_binary()

    directory = https_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HttpsSetupError(f"Unable to create the HTTPS directory {directory}: {exc}") from exc

    cert_file = directory / CERT_FILENAME
    key_file = directory / KEY_FILENAME
    signature_file = directory / SAN_SIGNATURE_FILENAME
    wanted = san_signature(sans)
    if cert_file.is_file() and key_file.is_file() and _read_signature_file(signature_file) == wanted and not _cert_needs_renewal(cert_file):
        root_ca_file = _root_ca_file(mkcert_path)
        return HttpsCertificate(cert_file, key_file, tuple(sans), root_ca_file)

    caroot = ensure_ca_installed(mkcert_path)
    logger.info(f"Generating a local HTTPS certificate for: {', '.join(sans)}")
    try:
        result = subprocess.run(
            [str(mkcert_path), "-cert-file", str(cert_file), "-key-file", str(key_file), *sans],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MKCERT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _remove_quietly(cert_file, key_file)
        raise HttpsSetupError(f"Unable to run {mkcert_path}: {exc}") from exc
    if result.returncode != 0:
        _remove_quietly(cert_file, key_file)
        detail = (result.stderr or result.stdout or "").strip()[-OUTPUT_TAIL_BYTES:]
        raise HttpsSetupError(f"mkcert could not generate the certificate (exit code {result.returncode}): {detail}")
    try:
        signature_file.write_text(wanted + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"Unable to write the certificate signature marker {signature_file}: {exc}")

    logger.info(f"Certificate saved to {cert_file}")
    root_ca_file = None
    if caroot is not None:
        root_ca_file = _root_ca_file(mkcert_path)
    return HttpsCertificate(cert_file, key_file, tuple(sans), root_ca_file)


def _remove_quietly(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _root_ca_file(mkcert: Path | None = None) -> Path | None:
    if mkcert is None:
        try:
            mkcert = resolve_mkcert_binary()
        except HttpsSetupError:
            return None
    caroot = _run_caroot(mkcert)
    if caroot is None:
        return None
    root_ca = caroot / "rootCA.pem"
    return root_ca if root_ca.is_file() else None


def export_root_ca(site_directory: Path, mkcert: Path | str | None = None) -> Path | None:
    """Copy the mkcert public root CA into the site directory.

    Devices that connect to this machine over HTTPS need the root CA to
    trust the site. Publishing the *public* certificate at
    ``/rootCA.pem`` lets those devices install it with a tap (on iOS, open
    the URL and install the profile, then enable full trust). The file is
    the public CA certificate only — the private key (``rootCA-key.pem``)
    is never exported.
    """
    mkcert_path = Path(mkcert) if mkcert is not None else None
    try:
        root_ca = _root_ca_file(mkcert_path)
    except OSError, HttpsSetupError:
        root_ca = None
    if root_ca is None:
        logger.warning("Unable to locate the mkcert root CA; other devices will not be able to install it from this site")
        return None
    destination = Path(site_directory) / ROOT_CA_SITE_FILENAME
    try:
        shutil.copy2(root_ca, destination)
    except OSError:
        logger.exception(f"Unable to copy the mkcert root CA to {destination}")
        return None
    logger.debug(f"Exported the mkcert root CA to {destination}")
    return destination


def _caddyfile_quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)


def build_caddyfile(public_port: int, internal_port: int, cert_file: Path, key_file: Path, storage_dir: Path | None = None) -> str:
    """Render the Caddyfile that fronts the embedded server with TLS."""
    storage_block = ""
    if storage_dir is not None:
        # Keep Caddy's state (certificates it was told to load, locks) next
        # to the rest of the HTTPS files instead of the platform default.
        storage_block = f"\tstorage file_system {{\n\t\troot {_caddyfile_quote(str(storage_dir))}\n\t}}\n"
    return f"""# Generated by RecipeServer — do not edit; rewritten on every start.
{{
	admin off
	auto_https off
	persist_config off
{storage_block}}}

# Serve the site over HTTPS for every address this machine has, and proxy
# to the embedded server on the loopback interface. Caddy sets
# X-Forwarded-Proto to https on the proxied request.
https://:{public_port} {{
	tls {_caddyfile_quote(str(cert_file))} {_caddyfile_quote(str(key_file))}
	reverse_proxy http://127.0.0.1:{internal_port}
}}
"""


def write_caddyfile(https_directory_path: Path, public_port: int, internal_port: int, cert_file: Path, key_file: Path) -> Path:
    caddyfile = Path(https_directory_path) / CADDYFILE_FILENAME
    try:
        caddyfile.parent.mkdir(parents=True, exist_ok=True)
        caddyfile.write_text(
            build_caddyfile(public_port, internal_port, cert_file, key_file, storage_dir=Path(https_directory_path) / "caddy-storage"),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HttpsSetupError(f"Unable to write the Caddyfile {caddyfile}: {exc}") from exc
    logger.debug(f"Wrote the Caddyfile {caddyfile} (public port {public_port}, internal port {internal_port})")
    return caddyfile


def start_https(cfg, internal_port: int) -> "CaddyServer":
    """Issue (when needed) the certificate and start Caddy."""
    certificate = ensure_certificate(cfg)
    directory = https_directory()
    caddyfile = write_caddyfile(directory, int(getattr(cfg, "server_port", 8000)), internal_port, certificate.cert_file, certificate.key_file)
    caddy = CaddyServer(caddyfile, int(getattr(cfg, "server_port", 8000)))
    caddy.ensure_running()
    return caddy


def _read_stream(stream, tail: deque) -> None:
    """Drain a process stream into *tail* (and the log) until EOF."""
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            logger.debug(f"caddy: {line}")
    except ValueError, OSError:
        # The stream closed while Caddy was shutting down.
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


class CaddyServer:
    """Start, health-check, and stop the caddy subprocess."""

    def __init__(
        self,
        config_path: Path | str,
        port: int,
        host: str = "127.0.0.1",
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ):
        self.config_path = Path(config_path)
        self.port = port
        self.host = host
        self.startup_timeout = startup_timeout
        self._process: subprocess.Popen | None = None
        self._tail: deque[str] = deque(maxlen=32)
        self._lock = RLock()
        self._reader = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _output_tail(self) -> str:
        text = "\n".join(self._tail)
        return text[-OUTPUT_TAIL_BYTES:]

    def _spawn(self, caddy: Path) -> subprocess.Popen:
        command = [str(caddy), "run", "--config", str(self.config_path), "--adapter", "caddyfile"]
        logger.info(f"Starting caddy on all interfaces port {self.port} (proxying to the embedded server)")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise HttpsSetupError(f"Unable to start caddy at {caddy}: {exc}") from exc

        self._tail.clear()
        self._reader = Thread(target=_read_stream, args=(process.stdout, self._tail), name="caddy-output", daemon=True)
        self._reader.start()
        return process

    def _wait_until_ready(self, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + self.startup_timeout
        url = f"https://{self.host}:{self.port}/health"
        # Python's ssl does not trust the mkcert CA, so verify nothing;
        # readiness only needs an HTTP response from the app behind Caddy.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                tail = self._output_tail()
                message = f"caddy exited with code {returncode} during startup"
                if tail:
                    message += f": {tail}"
                raise HttpsSetupError(message)
            try:
                with urlopen(url, timeout=1, context=context):
                    return
            except URLError, OSError:
                time.sleep(POLL_INTERVAL_SECONDS)
        self.stop()
        raise HttpsSetupError(f"caddy did not become ready within {self.startup_timeout:.0f} seconds")

    def ensure_running(self) -> "CaddyServer":
        """Start caddy if it is not running and wait until it answers."""
        with self._lock:
            if self.is_running:
                return self

            caddy = resolve_caddy_binary()
            self._process = self._spawn(caddy)
            try:
                self._wait_until_ready(self._process)
            except BaseException:
                self.stop()
                raise
            return self

    def stop(self) -> None:
        """Stop caddy, escalating to a kill if it ignores terminate."""
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            if process.poll() is None:
                logger.info("Stopping caddy")
                try:
                    process.terminate()
                    process.wait(timeout=STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    logger.warning("caddy did not stop in time; killing it")
                    process.kill()
                    try:
                        process.wait(timeout=STOP_TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired:
                        logger.error("caddy did not exit after being killed")
                except OSError as exc:
                    logger.warning(f"Unable to stop caddy: {exc}")
            if self._reader is not None:
                self._reader.join(timeout=1)
                self._reader = None
