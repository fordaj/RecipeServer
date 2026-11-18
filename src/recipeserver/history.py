"""Recipe revision history: immutable snapshots kept outside the source tree.

This is a lightweight, application-managed revision history for recipes,
not a backup system. Snapshots live in the OS-specific application data
directory (``user_data_path("recipe-server") / "history"``), never inside the
user's recipe directory, and are organized by the recipe's stable
``recipe_id`` so renames and moves keep their history:

.. code-block:: text

    history/
    └── recipes/
        └── <recipe-uuid>/
            ├── <snapshot-id>.md
            └── <snapshot-id>.md

A snapshot identifier looks like ``20261117T123045123456Z-a1b2c3d4``: a UTC
microsecond timestamp followed by a random suffix, so identifiers are unique
without relying on the clock alone and directories sort chronologically.
Each snapshot is the exact Markdown of the recipe before it was replaced,
including front matter, comments, and whitespace. There is no database;
the directory itself is the index.

Consecutive duplicate versions are skipped by comparing the SHA-256 of the
snapshot that would be created against the newest stored snapshot. History
is retained indefinitely; the layout leaves room for a future configurable
retention policy.

Tests point ``RECIPE_SERVER_HISTORY_DIR`` at a temporary directory instead of
the real user-data directory, mirroring ``RECIPE_SERVER_HTTPS_DIR``.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_path

from .recipe_utils import canonical_recipe_id, is_valid_recipe_id

HISTORY_DIR_ENV_VAR = "RECIPE_SERVER_HISTORY_DIR"
HISTORY_DIR_NAME = "history"
RECIPES_DIR_NAME = "recipes"
SNAPSHOT_SUFFIX = ".md"

_SNAPSHOT_ID_RE = re.compile(r"^(?P<stamp>\d{8}T\d{12}Z)-(?P<random>[0-9a-f]{8})$")
_CREATE_ATTEMPTS = 5


class HistoryError(RuntimeError):
    """Raised when a snapshot cannot be stored safely."""


@dataclass(frozen=True)
class SnapshotInfo:
    """Metadata about one stored snapshot (the content is read on demand)."""

    id: str
    created: datetime
    size: int


def history_directory() -> Path:
    """Return the root history directory, honoring the test override."""
    override = os.environ.get(HISTORY_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return user_data_path("recipe-server", appauthor=False) / HISTORY_DIR_NAME


def recipe_history_directory(recipe_id: str) -> Path:
    """Return the directory holding the snapshots of *recipe_id*."""
    if not is_valid_recipe_id(recipe_id):
        raise HistoryError(f"Not a valid recipe_id: {recipe_id!r}")
    return history_directory() / RECIPES_DIR_NAME / canonical_recipe_id(recipe_id)


def sha256_text(content: str) -> str:
    """Return the hex SHA-256 digest of *content* encoded as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_snapshot_id(now: datetime | None = None) -> str:
    """Return a new snapshot identifier embedding *now* (UTC) and randomness."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S") + f"{moment.microsecond:06d}Z"
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def is_valid_snapshot_id(snapshot_id: object) -> bool:
    """Return True when *snapshot_id* matches the snapshot format."""
    if not isinstance(snapshot_id, str) or _SNAPSHOT_ID_RE.fullmatch(snapshot_id) is None:
        return False
    try:
        parse_snapshot_id(snapshot_id)
    except HistoryError:
        return False
    return True


def parse_snapshot_id(snapshot_id: str) -> datetime:
    """Return the UTC creation time embedded in *snapshot_id*."""
    match = _SNAPSHOT_ID_RE.fullmatch(snapshot_id)
    if match is None:
        raise HistoryError(f"Not a valid snapshot id: {snapshot_id!r}")
    stamp = match.group("stamp")
    try:
        moment = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
    except ValueError as exc:
        raise HistoryError(f"Not a valid snapshot id: {snapshot_id!r}") from exc
    micros = int(stamp[15:21])
    return moment.replace(microsecond=micros, tzinfo=timezone.utc)


def _snapshot_path(directory: Path, snapshot_id: str) -> Path:
    if not is_valid_snapshot_id(snapshot_id):
        raise HistoryError(f"Not a valid snapshot id: {snapshot_id!r}")
    path = directory / f"{snapshot_id}{SNAPSHOT_SUFFIX}"
    # Defense in depth: the suffix check above already forbids path separators.
    if path.parent != directory:
        raise HistoryError(f"Snapshot id escapes the recipe history directory: {snapshot_id!r}")
    return path


def write_file_atomic(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (temp file in the same directory + rename)."""
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_snapshot(recipe_id: str, content: str) -> Path | None:
    """Store *content* as the newest snapshot of *recipe_id*.

    Returns the snapshot path, or ``None`` when the exact content is already
    the newest snapshot (no duplicate consecutive versions). Raises
    :class:`HistoryError` when the snapshot cannot be written; callers that
    snapshot before a save must treat that as a reason to abort the save so
    the previous version is never lost silently.
    """
    if not is_valid_recipe_id(recipe_id):
        raise HistoryError(f"Not a valid recipe_id: {recipe_id!r}")
    directory = recipe_history_directory(recipe_id)

    digest = sha256_text(content)
    latest = latest_snapshot(recipe_id)
    if latest is not None:
        try:
            latest_digest = sha256_text(latest.read_text(encoding="utf-8"))
        except OSError:
            latest_digest = None
        if latest_digest == digest:
            return None

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HistoryError(f"Unable to create history directory {directory}: {exc}") from exc

    for _ in range(_CREATE_ATTEMPTS):
        snapshot_id = make_snapshot_id()
        path = _snapshot_path(directory, snapshot_id)
        if path.exists():
            continue
        try:
            write_file_atomic(path, content)
        except OSError as exc:
            raise HistoryError(f"Unable to write snapshot {path}: {exc}") from exc
        return path

    raise HistoryError(f"Unable to allocate a unique snapshot id in {directory}")


def latest_snapshot(recipe_id: str) -> Path | None:
    """Return the newest snapshot of *recipe_id*, or ``None``."""
    try:
        directory = recipe_history_directory(recipe_id)
    except HistoryError:
        return None
    if not directory.is_dir():
        return None
    candidates = [path for path in directory.glob(f"*{SNAPSHOT_SUFFIX}") if is_valid_snapshot_id(path.stem)]
    if not candidates:
        return None
    # The timestamp prefix is fixed-width, so lexical order is chronological.
    return max(candidates, key=lambda path: path.stem)


def list_snapshots(recipe_id: str) -> list[SnapshotInfo]:
    """Return the snapshots of *recipe_id*, newest first."""
    try:
        directory = recipe_history_directory(recipe_id)
    except HistoryError:
        return []
    if not directory.is_dir():
        return []

    snapshots: list[SnapshotInfo] = []
    for path in directory.glob(f"*{SNAPSHOT_SUFFIX}"):
        if not is_valid_snapshot_id(path.stem):
            continue
        try:
            stat = path.stat()
            created = parse_snapshot_id(path.stem)
        except OSError, HistoryError:
            continue
        snapshots.append(SnapshotInfo(id=path.stem, created=created, size=stat.st_size))

    snapshots.sort(key=lambda snapshot: snapshot.id, reverse=True)
    return snapshots


def read_snapshot(recipe_id: str, snapshot_id: str) -> str:
    """Return the exact Markdown stored in *snapshot_id*.

    Raises :class:`HistoryError` when the recipe or snapshot id is invalid
    and :class:`FileNotFoundError` when the snapshot does not exist.
    """
    directory = recipe_history_directory(recipe_id)
    path = _snapshot_path(directory, snapshot_id)
    return path.read_text(encoding="utf-8")


def snapshot_exists(recipe_id: str, snapshot_id: str) -> bool:
    """Return True when *snapshot_id* names a stored snapshot."""
    try:
        directory = recipe_history_directory(recipe_id)
        path = _snapshot_path(directory, snapshot_id)
    except HistoryError:
        return False
    return path.is_file()
