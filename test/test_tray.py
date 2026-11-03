from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from recipeserver import core as core_module
from recipeserver import tray as tray_module


class FakeServer:
    def __init__(self, running: bool = False):
        self.is_running = running
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.is_running = True

    def stop(self):
        self.stop_calls += 1
        self.is_running = False


class FakeIcon:
    def __init__(self, name, image, title, menu=None):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.run_calls = 0
        self.run_detached_calls = 0
        self.stop_calls = 0
        self.update_menu_calls = 0

    def run(self):
        self.run_calls += 1

    def run_detached(self):
        self.run_detached_calls += 1

    def stop(self):
        self.stop_calls += 1

    def update_menu(self):
        self.update_menu_calls += 1


@pytest.fixture
def tray_factory(monkeypatch):
    created_icons: list[FakeIcon] = []

    class RecordingIcon(FakeIcon):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created_icons.append(self)

    monkeypatch.setattr(tray_module.pystray, "Icon", RecordingIcon)

    def create(running: bool = False):
        server = FakeServer(running)
        quit_calls: list[bool] = []
        tray = tray_module.Tray(server, on_quit=lambda: quit_calls.append(True))
        return tray, server, created_icons[-1], quit_calls

    return create


def get_menu_item(tray, text: str):
    for item in tray.icon.menu.items:
        if item.text == text:
            return item

    labels = [item.text for item in tray.icon.menu.items]
    raise AssertionError(f"No menu item named {text!r}; menu contains {labels!r}")


def test_tray_uses_the_bundled_logo_image(tray_factory):
    tray, _, icon, _ = tray_factory()

    assert tray_module.LOGO_PNG.is_file(), f"Missing tray logo: {tray_module.LOGO_PNG}"

    with Image.open(tray_module.LOGO_PNG) as source:
        assert icon.image.mode == "RGBA"
        assert icon.image.size == source.size

    assert icon.name == "RecipeServer"
    assert icon.title == "RecipeServer"


def test_tray_fails_when_the_logo_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(tray_module, "LOGO_PNG", tmp_path / "missing-logo.png")
    monkeypatch.setattr(
        tray_module.pystray,
        "Icon",
        lambda *args, **kwargs: pytest.fail("Icon must not be created without a logo"),
    )

    with pytest.raises(FileNotFoundError):
        tray_module.Tray(FakeServer(), on_quit=lambda: None)


def test_tray_fails_when_the_logo_cannot_be_read(monkeypatch, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"this is not a PNG")
    monkeypatch.setattr(tray_module, "LOGO_PNG", logo)

    with pytest.raises(UnidentifiedImageError):
        tray_module.Tray(FakeServer(), on_quit=lambda: None)


def test_tray_run_starts_the_icon(tray_factory):
    tray, _, icon, _ = tray_factory()

    tray.run()

    assert icon.run_calls == 1


def test_tray_run_propagates_startup_failures(tray_factory):
    tray, _, icon, _ = tray_factory()

    def fail():
        raise RuntimeError("tray backend unavailable")

    icon.run = fail

    with pytest.raises(RuntimeError, match="tray backend unavailable"):
        tray.run()


def test_tray_run_detached_starts_the_icon(tray_factory):
    tray, _, icon, _ = tray_factory()

    tray.run_detached()

    assert icon.run_detached_calls == 1


def test_tray_stop_stops_the_icon(tray_factory):
    tray, _, icon, _ = tray_factory()

    tray.stop()

    assert icon.stop_calls == 1


def test_tray_menu_contains_the_expected_actions(tray_factory):
    tray, _, icon, _ = tray_factory()

    labels = [item.text for item in icon.menu.items if not item.text.startswith("-")]

    assert labels == [
        "Open Recipes",
        "Server: Stopped",
        "Start Server",
        "Stop Server",
        "Quit",
    ]
    assert get_menu_item(tray, "Open Recipes").default is True
    assert get_menu_item(tray, "Server: Stopped").enabled is False


def test_tray_menu_opens_the_recipes_page(tray_factory, monkeypatch):
    tray, _, icon, _ = tray_factory()
    opened_urls: list[str] = []
    monkeypatch.setattr(tray_module.webbrowser, "open", opened_urls.append)

    get_menu_item(tray, "Open Recipes")(icon)

    assert opened_urls == ["http://localhost:8000"]


def test_tray_menu_reports_server_status(tray_factory):
    tray, server, _, _ = tray_factory()
    assert get_menu_item(tray, "Server: Stopped").text == "Server: Stopped"

    server.is_running = True

    assert get_menu_item(tray, "Server: Running").text == "Server: Running"


def test_tray_menu_starts_and_stops_the_server(tray_factory):
    tray, server, icon, _ = tray_factory()

    start_item = get_menu_item(tray, "Start Server")
    stop_item = get_menu_item(tray, "Stop Server")
    assert start_item.visible is True
    assert stop_item.visible is False

    start_item(icon)

    assert server.start_calls == 1
    assert icon.update_menu_calls == 1
    assert get_menu_item(tray, "Start Server").visible is False
    assert get_menu_item(tray, "Stop Server").visible is True
    assert get_menu_item(tray, "Server: Running").text == "Server: Running"

    get_menu_item(tray, "Stop Server")(icon)

    assert server.stop_calls == 1
    assert icon.update_menu_calls == 2
    assert get_menu_item(tray, "Start Server").visible is True
    assert get_menu_item(tray, "Stop Server").visible is False
    assert get_menu_item(tray, "Server: Stopped").text == "Server: Stopped"


def test_tray_menu_start_failure_keeps_the_menu_usable(tray_factory):
    tray, server, icon, _ = tray_factory()

    def fail_start():
        raise OSError("port 8000 is already in use")

    server.start = fail_start

    get_menu_item(tray, "Start Server")(icon)

    assert icon.update_menu_calls == 1
    assert get_menu_item(tray, "Start Server").visible is True


def test_tray_menu_quit_calls_the_shutdown_callback(tray_factory):
    tray, _, icon, quit_calls = tray_factory()

    get_menu_item(tray, "Quit")(icon)

    assert quit_calls == [True]


def test_tray_menu_is_built_from_the_module_logo():
    """The tray image must come from the bundled asset, not a placeholder."""
    path = Path(tray_module.LOGO_PNG)

    assert path == Path(tray_module.__file__).parent / "assets" / "logo.png"
    assert path.is_file()


def run_main_with_platform(monkeypatch, platform: str) -> list[str]:
    events: list[str] = []

    class FakeCore:
        def __init__(self, cfg):
            self.cfg = cfg

        def regen(self):
            events.append("regen")

        def on_markdown_save(self, markdown):
            events.append("markdown-save")

    class FakeServer:
        def __init__(self, cfg, on_markdown_saved=None):
            self.cfg = cfg
            self.on_markdown_saved = on_markdown_saved

        def start(self):
            events.append("server-start")

        def stop(self):
            events.append("server-stop")

    class FakeTray:
        def __init__(self, server, on_quit):
            self.server = server
            self.on_quit = on_quit
            events.append("tray-init")

        def run(self):
            events.append("tray-run")
            self.on_quit()

        def run_detached(self):
            events.append("tray-run-detached")
            self.on_quit()

        def stop(self):
            events.append("tray-stop")

    monkeypatch.setattr(core_module, "Core", FakeCore)
    monkeypatch.setattr(core_module, "Server", FakeServer)
    monkeypatch.setattr(core_module, "Tray", FakeTray)
    monkeypatch.setattr(core_module.sys, "platform", platform)

    core_module.main(object())

    return events


def test_main_starts_the_tray_on_macos(monkeypatch):
    events = run_main_with_platform(monkeypatch, "darwin")

    assert events == [
        "regen",
        "server-start",
        "tray-init",
        "tray-run",
        "tray-stop",
        "server-stop",
    ]


def test_main_starts_the_tray_detached_elsewhere(monkeypatch):
    events = run_main_with_platform(monkeypatch, "win32")

    assert events == [
        "regen",
        "server-start",
        "tray-init",
        "tray-run-detached",
        "tray-stop",
        "server-stop",
    ]
