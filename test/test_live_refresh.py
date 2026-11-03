import os
import shutil
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from recipeserver.core import Core
from recipeserver.file_watcher import ChangeKind, FileChange


def write_png(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (8, 8), color).save(path)


def write_recipe(path: Path, title: str, *, meal: str = "Dinner") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nmeals:\n  - {meal}\n---\n# {title}\n\n![{title}](image.png)\n",
        encoding="utf-8",
    )


def make_core(tmp_path: Path, monkeypatch) -> tuple[Core, Path, Path]:
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    source.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        Core,
        "copy_assets",
        staticmethod(lambda site_directory: None),
    )
    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    return core, source, site


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_external_changes_add_update_and_remove_recipes(tmp_path: Path, monkeypatch):
    core, source, site = make_core(tmp_path, monkeypatch)

    dinner = source / "dinner" / "recipe.md"
    write_recipe(dinner, "Braised Greens")

    core.regen()
    initial_revision = core.revision

    index = read(site / "index.html")
    assert "Braised Greens" in index

    dessert = source / "dessert" / "recipe.md"
    write_recipe(dessert, "Peach Cobbler", meal="Dessert")

    core.handle_file_changes([FileChange(ChangeKind.CREATED, dessert)])

    assert (site / "dessert" / "recipe.html").is_file()
    assert "Peach Cobbler" in read(site / "index.html")
    assert core.revision == initial_revision + 1

    write_recipe(dinner, "Braised Greens Deluxe")
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, dinner)])

    recipe_html = read(site / "dinner" / "recipe.html")
    assert "Braised Greens Deluxe" in recipe_html
    assert "Braised Greens Deluxe" in read(site / "index.html")
    assert core.revision == initial_revision + 2

    dessert.unlink()
    core.handle_file_changes([FileChange(ChangeKind.DELETED, dessert)])

    assert not (site / "dessert" / "recipe.html").exists()
    assert not (site / "dessert").exists()
    assert "Peach Cobbler" not in read(site / "index.html")
    assert core.revision == initial_revision + 3


def test_image_changes_update_the_hero_and_prune_stale_output(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    write_png(source / "dinner" / "z-hero.png", (180, 40, 40))

    core.regen()
    assert "/dinner/z-hero.png" in read(site / "index.html")

    added = source / "dinner" / "a-hero.png"
    write_png(added, (40, 40, 180))
    core.handle_file_changes([FileChange(ChangeKind.CREATED, added)])

    assert (site / "dinner" / "a-hero.png").is_file()
    assert "/dinner/a-hero.png" in read(site / "index.html")

    added.unlink()
    core.handle_file_changes([FileChange(ChangeKind.DELETED, added)])

    assert not (site / "dinner" / "a-hero.png").exists()
    assert "/dinner/z-hero.png" in read(site / "index.html")


def test_own_save_event_does_not_refresh_twice(tmp_path: Path, monkeypatch):
    core, source, _ = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()

    core.on_markdown_save(recipe)
    revision = core.revision

    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, recipe)])

    assert core.revision == revision


def test_moving_a_recipe_removes_the_old_page_and_builds_the_new_one(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    old_recipe = source / "old" / "recipe.md"
    write_recipe(old_recipe, "Moving Recipe")
    core.regen()

    new_recipe = source / "new" / "recipe.md"
    new_recipe.parent.mkdir()
    old_recipe.rename(new_recipe)

    core.handle_file_changes(
        [
            FileChange(
                ChangeKind.MOVED,
                new_recipe,
                old_path=old_recipe,
            )
        ]
    )

    assert not (site / "old" / "recipe.html").exists()
    assert not (site / "old").exists()
    assert (site / "new" / "recipe.html").is_file()

    index = read(site / "index.html")
    assert "Moving Recipe" in index
    assert "/new/recipe.html" in index
    assert "/old/recipe.html" not in index


def test_directory_change_falls_back_to_a_full_rebuild(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    existing = source / "dinner" / "recipe.md"
    write_recipe(existing, "Braised Greens")
    core.regen()
    revision = core.revision

    added = source / "lunch" / "recipe.md"
    write_recipe(added, "Lunch Salad", meal="Lunch")

    core.handle_file_changes(
        [
            FileChange(
                ChangeKind.CREATED,
                added.parent,
                is_directory=True,
            )
        ]
    )

    assert (site / "lunch" / "recipe.html").is_file()
    assert "Lunch Salad" in read(site / "index.html")
    assert core.revision == revision + 1


def test_refresh_all_rebuilds_and_increments_the_revision(tmp_path: Path, monkeypatch):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    write_recipe(recipe, "Braised Greens Refreshed")
    core.refresh_all()

    assert "Braised Greens Refreshed" in read(site / "index.html")
    assert core.revision == revision + 1


def test_failed_refresh_keeps_the_last_good_page(tmp_path: Path, monkeypatch):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision
    good_page = read(site / "dinner" / "recipe.html")

    original_convert = Core.convert_recipe

    def convert_or_fail(core_instance: Core, markdown: Path):
        if markdown == recipe.resolve():
            raise ValueError("broken recipe")
        return original_convert(core_instance, markdown)

    monkeypatch.setattr(Core, "convert_recipe", convert_or_fail)

    write_recipe(recipe, "Broken Greens")
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, recipe)])

    # A transient conversion failure (locked file, half-written save, invalid
    # YAML) must not erase the last page that rendered successfully.
    assert read(site / "dinner" / "recipe.html") == good_page
    assert "Braised Greens" in read(site / "index.html")
    assert "Broken Greens" not in read(site / "index.html")
    assert core.revision == revision

    # The stored signature still points at the old content, so the next event
    # retries the conversion and recovers without a restart.
    monkeypatch.setattr(Core, "convert_recipe", original_convert)
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, recipe)])

    assert "Broken Greens" in read(site / "dinner" / "recipe.html")
    assert "Broken Greens" in read(site / "index.html")
    assert core.revision == revision + 1


def test_generated_pages_include_live_refresh_assets(tmp_path: Path, monkeypatch):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()

    index = read(site / "index.html")
    recipe_html = read(site / "dinner" / "recipe.html")

    assert 'src="/assets/live-refresh.js"' in index
    assert 'href="/assets/live-refresh.css"' in index
    assert 'src="/assets/live-refresh.js"' in recipe_html
    assert 'href="/assets/live-refresh.css"' in recipe_html


def test_image_changes_outside_a_recipe_directory_are_ignored(
    tmp_path: Path, monkeypatch
):
    core, source, _ = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    stray_image = source / "images" / "unused.png"
    stray_image.parent.mkdir()
    write_png(stray_image, (10, 20, 30))

    core.handle_file_changes([FileChange(ChangeKind.CREATED, stray_image)])

    assert core.revision == revision


def test_metadata_only_image_event_does_not_trigger_a_reload(
    tmp_path: Path, monkeypatch
):
    core, source, _ = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    image = source / "dinner" / "hero.png"
    write_png(image, (180, 40, 40))

    core.regen()
    revision = core.revision

    # Filesystems and editors can emit MODIFIED events without touching the
    # bytes. Those must not bump the revision, or every open tab reloads.
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, image)])

    assert core.revision == revision

    write_png(image, (40, 40, 180))
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, image)])

    assert core.revision == revision + 1


def test_touch_only_recipe_event_does_not_trigger_a_reload(
    tmp_path: Path, monkeypatch
):
    core, source, _ = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    later = recipe.stat().st_mtime_ns + 1_000_000_000
    os.utime(recipe, ns=(later, later))

    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, recipe)])

    assert core.revision == revision


def test_unrelated_directory_delete_does_not_rebuild(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    scratch = source / "dinner" / "cache"
    scratch.mkdir()
    (scratch / "notes.txt").write_text("temporary", encoding="utf-8")
    shutil.rmtree(scratch)

    core.handle_file_changes(
        [FileChange(ChangeKind.DELETED, scratch, is_directory=True)]
    )

    assert core.revision == revision
    assert (site / "dinner" / "recipe.html").is_file()


def test_directory_delete_that_removes_a_recipe_rebuilds(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    directory = source / "dinner"
    shutil.rmtree(directory)

    core.handle_file_changes(
        [FileChange(ChangeKind.DELETED, directory, is_directory=True)]
    )

    assert not (site / "dinner" / "recipe.html").exists()
    assert core.revision == revision + 1


def test_atomic_save_reappearing_after_delete_refreshes_instead_of_removing(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()
    revision = core.revision

    # Some editors delete and immediately rewrite a file. By the time the
    # debounced batch is handled, the new file is already in place.
    write_recipe(recipe, "Braised Greens Atomic")
    core.handle_file_changes([FileChange(ChangeKind.DELETED, recipe)])

    assert (site / "dinner" / "recipe.html").is_file()
    assert "Braised Greens Atomic" in read(site / "dinner" / "recipe.html")
    assert "Braised Greens Atomic" in read(site / "index.html")
    assert core.revision == revision + 1


def test_hidden_images_are_neither_copied_nor_used_as_the_hero(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")

    # macOS creates "._name" AppleDouble files when copying to some volumes.
    # They sort before real files and used to win hero selection.
    write_png(source / "dinner" / "._aaa.png", (255, 0, 255))
    write_png(source / "dinner" / "z-hero.png", (180, 40, 40))

    core.regen()

    assert not (site / "dinner" / "._aaa.png").exists()
    assert "/dinner/z-hero.png" in read(site / "index.html")
    assert "._aaa.png" not in read(site / "index.html")


def test_refreshing_a_recipe_keeps_nested_recipe_signatures_intact(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    outer = source / "dinner" / "recipe.md"
    nested = source / "dinner" / "sides" / "recipe.md"
    write_recipe(outer, "Braised Greens")
    write_recipe(nested, "Roasted Potatoes", meal="Side")
    core.regen()

    write_recipe(outer, "Braised Greens Deluxe")
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, outer)])
    revision = core.revision

    assert "Braised Greens Deluxe" in read(site / "dinner" / "recipe.html")

    # A no-op event for the nested recipe must not look changed just because
    # the parent recipe was refreshed and pruned its own signatures.
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, nested)])

    assert core.revision == revision
    assert "Roasted Potatoes" in read(site / "dinner" / "sides" / "recipe.html")
