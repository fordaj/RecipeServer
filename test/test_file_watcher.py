from pathlib import Path
from threading import Event

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from recipeserver.file_watcher import ChangeKind, FileChange, LibraryWatcher


def make_watcher(source: Path, *, site: Path | None = None):
    batches: list[tuple[FileChange, ...]] = []
    watcher = LibraryWatcher(
        source,
        batches.append,
        site_directory=site,
        debounce_seconds=0,
    )
    return watcher, batches


def test_modified_recipe_is_normalized_and_batched_once(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = source / "dinner" / "recipe.md"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("# Dinner\n", encoding="utf-8")

    watcher, batches = make_watcher(source)

    first = watcher.record_event(FileModifiedEvent(str(recipe)))
    second = watcher.record_event(FileModifiedEvent(str(recipe)))

    assert first == FileChange(ChangeKind.MODIFIED, recipe.resolve())
    assert second == first
    assert watcher.flush() is True
    assert batches == [(first,)]
    assert watcher.flush() is False


def test_recipe_and_image_events_are_relevant(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = source / "dinner" / "recipe.md"
    image = source / "dinner" / "hero.PNG"
    recipe.parent.mkdir(parents=True)

    watcher, _ = make_watcher(source)

    assert watcher.record_event(FileCreatedEvent(str(recipe))) == FileChange(
        ChangeKind.CREATED, recipe.resolve()
    )
    assert watcher.record_event(FileCreatedEvent(str(image))) == FileChange(
        ChangeKind.CREATED, image.resolve()
    )


def test_irrelevant_files_are_ignored(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe_dir = source / "dinner"
    recipe_dir.mkdir(parents=True)

    watcher, batches = make_watcher(source)

    ignored = [
        recipe_dir / "notes.md",
        recipe_dir / "notes.txt",
        recipe_dir / "recipe.md.swp",
        recipe_dir / "recipe.md~",
        recipe_dir / "~$recipe.md",
        recipe_dir / ".hidden.png",
        source / ".git" / "recipe.md",
        source / "__pycache__" / "recipe.md",
        source / "recipe.md.tmp",
    ]

    for path in ignored:
        assert watcher.record_event(FileModifiedEvent(str(path))) is None, path

    assert watcher.flush() is False
    assert batches == []


def test_directory_creation_is_ignored_but_deletion_is_reported(tmp_path: Path):
    source = tmp_path / "recipes"
    directory = source / "dinner"
    directory.mkdir(parents=True)

    watcher, _ = make_watcher(source)

    assert watcher.record_event(DirCreatedEvent(str(directory))) is None

    change = watcher.record_event(DirDeletedEvent(str(directory)))
    assert change == FileChange(
        ChangeKind.DELETED,
        directory.resolve(),
        is_directory=True,
    )


def test_file_moves_inside_the_tree_keep_both_paths(tmp_path: Path):
    source = tmp_path / "recipes"
    old_path = source / "old" / "recipe.md"
    new_path = source / "new" / "recipe.md"
    old_path.parent.mkdir(parents=True)
    new_path.parent.mkdir(parents=True)

    watcher, _ = make_watcher(source)

    change = watcher.record_event(
        FileMovedEvent(str(old_path), str(new_path))
    )

    assert change == FileChange(
        ChangeKind.MOVED,
        new_path.resolve(),
        old_path=old_path.resolve(),
    )


def test_moves_into_and_out_of_the_source_tree_become_create_and_delete(
    tmp_path: Path,
):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "dinner" / "recipe.md"
    recipe.parent.mkdir()
    outside = tmp_path / "outside" / "recipe.md"
    outside.parent.mkdir()

    watcher, _ = make_watcher(source)

    moving_in = watcher.record_event(FileMovedEvent(str(outside), str(recipe)))
    assert moving_in == FileChange(ChangeKind.CREATED, recipe.resolve())

    moving_out = watcher.record_event(FileMovedEvent(str(recipe), str(outside)))
    assert moving_out == FileChange(ChangeKind.DELETED, recipe.resolve())


def test_directory_moves_are_reported_for_a_full_rebuild(tmp_path: Path):
    source = tmp_path / "recipes"
    old_path = source / "old"
    new_path = source / "new"
    old_path.mkdir(parents=True)

    watcher, _ = make_watcher(source)

    change = watcher.record_event(DirMovedEvent(str(old_path), str(new_path)))

    assert change == FileChange(
        ChangeKind.MOVED,
        new_path.resolve(),
        old_path=old_path.resolve(),
        is_directory=True,
    )


def test_generated_site_and_hidden_paths_are_ignored(tmp_path: Path):
    source = tmp_path / "recipes"
    site = source / ".generated"
    site.mkdir(parents=True)
    recipe = source / "dinner" / "recipe.md"
    recipe.parent.mkdir()

    watcher, _ = make_watcher(source, site=site)

    assert watcher.record_event(FileModifiedEvent(str(site / "recipe.md"))) is None
    assert watcher.record_event(FileModifiedEvent(str(recipe))) is not None


def test_stop_clears_pending_changes(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = source / "dinner" / "recipe.md"
    recipe.parent.mkdir(parents=True)

    watcher, batches = make_watcher(source)
    watcher.record_event(FileModifiedEvent(str(recipe)))

    watcher.stop()

    assert watcher.is_running is False
    assert watcher.flush() is False
    assert batches == []


def test_real_observer_reports_source_changes(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe = source / "dinner" / "recipe.md"
    recipe.parent.mkdir(parents=True)

    received: list[FileChange] = []
    received_event = Event()

    def on_changes(changes):
        received.extend(changes)
        received_event.set()

    watcher = LibraryWatcher(source, on_changes, debounce_seconds=0.05)
    watcher.start()

    try:
        recipe.write_text("---\nmeals:\n  - Dinner\n---\n# Dinner\n", encoding="utf-8")
        assert received_event.wait(5), "watcher did not report the new recipe"
    finally:
        watcher.stop()

    assert any(
        change.path == recipe.resolve()
        and change.kind in (ChangeKind.CREATED, ChangeKind.MODIFIED)
        for change in received
    )


def test_start_with_a_missing_directory_is_not_fatal(tmp_path: Path):
    watcher, batches = make_watcher(tmp_path / "missing")

    assert watcher.start() is False
    assert watcher.is_running is False

    watcher.stop()
    assert batches == []


def test_observer_start_failure_is_not_fatal(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()

    class BrokenObserver:
        def schedule(self, *args, **kwargs):
            raise OSError("watch limit reached")

        def is_alive(self):
            return False

    monkeypatch.setattr("recipeserver.file_watcher.Observer", BrokenObserver)

    watcher, batches = make_watcher(source)

    # A missing backend or exhausted watch limit must not stop the server; it
    # should simply run without live updates.
    assert watcher.start() is False
    assert watcher.is_running is False

    watcher.stop()
    assert batches == []
