"""Debounced filesystem monitoring for the recipe source tree.

watchdog emits low-level events, often several per save. This module normalizes
them into :class:`FileChange` records, filters out files the app does not care
about, and batches bursts so that the server refreshes each affected recipe once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileSystemMovedEvent,
)
from watchdog.observers import Observer

from ._logger import logger
from .image_handler import IMAGE_EXTENSIONS

RECIPE_FILENAME = "recipe.md"

# Directories that never contain recipe source we should react to.
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
    }
)

IGNORED_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})

# Editor swap files, partial downloads, and backup files.
IGNORED_SUFFIXES = frozenset(
    {
        ".bak",
        ".crdownload",
        ".orig",
        ".part",
        ".partial",
        ".rej",
        ".swo",
        ".swp",
        ".swx",
        ".temp",
        ".tmp",
    }
)


class ChangeKind(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass(frozen=True)
class FileChange:
    """A relevant source-tree change, independent of watchdog's event classes."""

    kind: ChangeKind
    path: Path
    old_path: Path | None = None
    is_directory: bool = False

    @property
    def paths(self) -> tuple[Path, ...]:
        if self.old_path is None:
            return (self.path,)
        return (self.old_path, self.path)


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


class LibraryWatcher:
    """Watch a recipe source directory and call back with batched changes."""

    def __init__(
        self,
        source_directory: Path,
        on_changes: Callable[[Sequence[FileChange]], None],
        *,
        site_directory: Path | None = None,
        debounce_seconds: float = 0.35,
    ):
        self.source_directory = Path(source_directory).resolve()
        self.site_directory = Path(site_directory).resolve() if site_directory else None
        self.on_changes = on_changes
        self.debounce_seconds = max(0.0, debounce_seconds)

        self._handler = _LibraryEventHandler(self)
        self._observer: Observer | None = None
        self._worker: Thread | None = None
        self._pending: dict[tuple[str, str, bool], FileChange] = {}
        self._pending_lock = Lock()
        self._wake = Event()
        self._stopping = Event()
        self._last_event_at = 0.0
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> bool:
        """Start the observer and the debounce worker. Safe to call twice."""
        if self._started:
            return True

        if not self.source_directory.is_dir():
            logger.warning(f'Not watching "{self.source_directory}": not a directory')
            return False

        self._stopping.clear()
        observer = Observer()

        try:
            observer.schedule(
                self._handler,
                str(self.source_directory),
                recursive=True,
            )
            observer.start()
        except Exception:
            # A missing platform backend, permission problem, or exhausted
            # watch limit should not prevent the app from serving recipes.
            logger.exception(
                f'Unable to watch "{self.source_directory}"; live updates are disabled'
            )
            try:
                if observer.is_alive():
                    observer.stop()
                    observer.join(timeout=1)
            except Exception:
                pass
            return False

        worker = Thread(
            target=self._flush_loop,
            name="RecipeLibraryWatcher",
            daemon=True,
        )

        try:
            worker.start()
        except Exception:
            logger.exception("Unable to start the recipe watcher worker")
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception:
                pass
            return False

        self._observer = observer
        self._worker = worker
        self._started = True
        logger.info(f'Watching "{self.source_directory}" for recipe changes')
        return True

    def stop(self) -> None:
        """Stop the observer and drain the worker thread."""
        was_running = self._started

        if was_running:
            self._stopping.set()
            self._wake.set()

            observer = self._observer
            worker = self._worker
            self._observer = None
            self._worker = None
            self._started = False

            if observer is not None:
                observer.stop()
                observer.join(timeout=5)

            if worker is not None and worker is not current_thread():
                worker.join(timeout=5)

        with self._pending_lock:
            self._pending.clear()

        if was_running:
            logger.info("Stopped watching the recipe library")

    def record_event(self, event: FileSystemEvent) -> FileChange | None:
        """Normalize a watchdog event and queue it for the next batch."""
        if event.event_type == "moved" and isinstance(event, FileSystemMovedEvent):
            return self._record_move(event)

        kind = {
            "created": ChangeKind.CREATED,
            "modified": ChangeKind.MODIFIED,
            "deleted": ChangeKind.DELETED,
        }.get(event.event_type)

        if kind is None:
            return None

        path = Path(event.src_path).resolve()
        is_directory = bool(event.is_directory)

        if is_directory and kind is not ChangeKind.DELETED:
            # Files created inside a new directory arrive as their own events.
            # Directory deletes are the only directory event we cannot observe
            # through child files.
            return None

        if not self._is_relevant(path, is_directory):
            return None

        change = FileChange(kind, path, is_directory=is_directory)
        self._queue(change)
        return change

    def flush(self) -> bool:
        """Deliver queued changes immediately. Returns True when any were sent."""
        with self._pending_lock:
            if not self._pending:
                return False

            batch = tuple(self._pending.values())
            self._pending.clear()

        self.on_changes(batch)
        return True

    def _record_move(self, event: FileSystemMovedEvent) -> FileChange | None:
        old_path = Path(event.src_path).resolve()
        new_path = Path(event.dest_path).resolve()
        is_directory = bool(event.is_directory)

        if is_directory:
            if self._is_ignored(old_path) and self._is_ignored(new_path):
                return None
            change = FileChange(
                ChangeKind.MOVED,
                new_path,
                old_path=old_path,
                is_directory=True,
            )
            self._queue(change)
            return change

        old_relevant = self._is_relevant(old_path, False)
        new_relevant = self._is_relevant(new_path, False)

        if old_relevant and new_relevant:
            change = FileChange(ChangeKind.MOVED, new_path, old_path=old_path)
        elif new_relevant:
            change = FileChange(ChangeKind.CREATED, new_path)
        elif old_relevant:
            change = FileChange(ChangeKind.DELETED, old_path)
        else:
            return None

        self._queue(change)
        return change

    def _is_relevant(self, path: Path, is_directory: bool) -> bool:
        if self._is_ignored(path):
            return False

        if is_directory:
            return True

        return path.name == RECIPE_FILENAME or _is_image(path)

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.source_directory)
        except ValueError:
            return True

        if self.site_directory is not None and path.is_relative_to(self.site_directory):
            return True

        if not relative.parts:
            return True

        if any(part.startswith(".") for part in relative.parts):
            return True

        if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts):
            return True

        name = path.name
        if name in IGNORED_FILE_NAMES:
            return True
        if name.endswith("~") or name.startswith("~$"):
            return True
        return path.suffix.lower() in IGNORED_SUFFIXES

    def _queue(self, change: FileChange) -> None:
        old_path = str(change.old_path) if change.old_path is not None else ""
        key = (str(change.path), old_path, change.is_directory)

        with self._pending_lock:
            self._pending[key] = change
            self._last_event_at = monotonic()

        self._wake.set()

    def _take_batch(self) -> tuple[FileChange, ...] | None:
        """Return a ready batch, or None when more time is needed."""
        with self._pending_lock:
            if not self._pending:
                return None

            remaining = self.debounce_seconds - (monotonic() - self._last_event_at)
            if remaining > 0:
                return None

            batch = tuple(self._pending.values())
            self._pending.clear()

        return batch

    def _flush_loop(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait(0.1)
            self._wake.clear()

            while not self._stopping.is_set():
                batch = self._take_batch()

                if batch is not None:
                    try:
                        self.on_changes(batch)
                    except Exception:
                        logger.exception("Failed to apply watched library changes")
                    continue

                with self._pending_lock:
                    if not self._pending:
                        break
                    remaining = self.debounce_seconds - (
                        monotonic() - self._last_event_at
                    )

                if self._stopping.wait(max(remaining, 0.01)):
                    break


class _LibraryEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: LibraryWatcher):
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self.watcher.record_event(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self.watcher.record_event(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self.watcher.record_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self.watcher.record_event(event)
