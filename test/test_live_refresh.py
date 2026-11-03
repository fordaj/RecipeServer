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


def test_failed_refresh_removes_the_stale_page_and_updates_the_index(
    tmp_path: Path, monkeypatch
):
    core, source, site = make_core(tmp_path, monkeypatch)

    recipe = source / "dinner" / "recipe.md"
    write_recipe(recipe, "Braised Greens")
    core.regen()

    original_convert = Core.convert_recipe

    def convert_or_fail(core_instance: Core, markdown: Path):
        if markdown == recipe.resolve():
            raise ValueError("broken recipe")
        return original_convert(core_instance, markdown)

    monkeypatch.setattr(Core, "convert_recipe", convert_or_fail)

    write_recipe(recipe, "Broken Greens")
    core.handle_file_changes([FileChange(ChangeKind.MODIFIED, recipe)])

    assert not (site / "dinner" / "recipe.html").exists()
    assert "Braised Greens" not in read(site / "index.html")


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
