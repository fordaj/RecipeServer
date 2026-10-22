from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from threading import Event


from collections.abc import Callable
from pathlib import Path
from queue import Queue
from threading import Event, Thread, Lock
from time import monotonic

from watchdog.events import FileSystemEvent, FileSystemEventHandler


class DirectoryWatcher(FileSystemEventHandler):
    def __init__(
        self,
        callback: Callable[[Path], None],
        debounce_seconds: float = 0.5,
    ):
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.events: Queue[Path] = Queue()
        self.paused = Event()
        self._shutdown = Event()
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()
        self._lock = Lock()
        self._last_signature: dict[Path, tuple[int, int]] = {}

    def pause(self) -> None:
        self.paused.set()

    def resume(self) -> None:
        self.paused.clear()

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or self.paused.is_set():
            return

        path = Path(event.src_path).resolve()

        if path.name == "recipe.html" or path.name == "index.html":
            return

        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return

        with self._lock:
            if self._last_signature.get(path) == signature:
                return

            self._last_signature[path] = signature

        self.events.put(path)

    def _run(self) -> None:
        pending: dict[Path, float] = {}

        while not self._shutdown.is_set():
            try:
                path = self.events.get(timeout=0.1)
                pending[path] = monotonic()
            except Exception:
                pass

            now = monotonic()
            ready = [path for path, timestamp in pending.items() if now - timestamp >= self.debounce_seconds]

            for path in ready:
                del pending[path]

                if not self.paused.is_set():
                    self.callback(path)

    def close(self) -> None:
        self._shutdown.set()
        self._worker.join()


class FileObserver:
    def __init__(self) -> None:
        self.observer = Observer()

    def setup(
        self,
        directories: list[Path],
        on_file_changed: Callable[[Path], None],
    ) -> None:
        handler = DirectoryWatcher(on_file_changed)

        for directory in directories:
            self.observer.schedule(
                handler,
                str(directory.resolve()),
                recursive=True,
            )

    def start(self) -> None:
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join()
