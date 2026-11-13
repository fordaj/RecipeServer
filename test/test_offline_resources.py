"""Guard the app against gaining runtime dependencies on the network.

Issue #142 requires that the whole app works on a LAN during internet
outages: fonts, SVGs, styles, scripts, and any other resources the pages
load must be vendored into the repo (or generated into the site directory)
rather than fetched from the internet at runtime. The only intentional
network access is the AI "From URL" recipe generation, which is explicit
user input and is covered separately in test_ai_recipe.py.

These tests fail when a stylesheet, script, page fragment, or generated
page references an external resource. User content (a recipe's source link)
is not a resource and may remain external; it is only navigated to when the
user clicks it.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from recipeserver.core import Core
from test.helpers import write_png

ASSETS_DIRECTORY = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
FIRST_PARTY_SUFFIXES = {".css", ".js", ".html", ".svg"}
# Vendored third-party snapshots the app serves as-is (KaTeX). They ship no
# runtime network calls, but they are not maintained in this repo, so the
# first-party checks exempt them; their completeness is asserted separately.
VENDORED_DIRECTORIES = {"katex"}

RESOURCE_ATTRIBUTES = ("src", "href", "srcset", "action", "poster", "xlink:href")
CSS_URL_PATTERN = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<target>[^'\")]+)(?P=quote)\s*\)", re.IGNORECASE)
CSS_IMPORT_PATTERN = re.compile(r"@import\s*(?:url\()?\s*(?P<quote>['\"]?)(?P<target>[^'\")\s;]+)(?P=quote)\s*\)?", re.IGNORECASE)
JS_URL_PATTERN = re.compile(r"(?:https?:)?//[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*")
SCHEME_PATTERN = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*):", re.IGNORECASE)

RECIPE_MARKDOWN = """---
ratings:
  - name: Avery
    rating: 8
    id: rating-1
    created: "2024-06-15T12:30:00Z"
    updated: "2024-06-15T12:30:00Z"
contributor: Avery
createdOn: "2024-06-15T12:30:00Z"
updatedOn: "2024-06-20T12:30:00Z"
meals:
  - Dinner
categories:
  - Mains
makes: 4
difficulty: 3
source:
  - format: website
    title: Example Source
    url: https://example.com/recipe
---
# Offline Audit Soup

Combine `1 cup` water with `2 tbsp` salt.

![Hero](hero.png)
"""


def is_local_reference(value: str) -> bool:
    """A reference is local when it carries no scheme and is not protocol-relative."""
    reference = value.strip()
    if not reference or reference.startswith("#") or reference.startswith("data:"):
        return True
    scheme = SCHEME_PATTERN.match(reference)
    if scheme is not None:
        # mailto/tel links do not load a resource over the network.
        return scheme.group("scheme").lower() in {"mailto", "tel"}
    return not reference.startswith("//")


def looks_external(value: str) -> bool:
    return not is_local_reference(value)


def first_party_files():
    for path in sorted(ASSETS_DIRECTORY.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in FIRST_PARTY_SUFFIXES:
            continue
        relative = path.relative_to(ASSETS_DIRECTORY)
        if relative.parts[0] in VENDORED_DIRECTORIES:
            continue
        yield path


def resource_attribute_failures(path: Path, text: str) -> list[str]:
    failures = []
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(True):
        for attribute, value in tag.attrs.items():
            if attribute not in RESOURCE_ATTRIBUTES:
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                candidates = [item] if attribute != "srcset" else [entry.split()[0] for entry in item.split(",") if entry.split()]
                for candidate in candidates:
                    if looks_external(candidate):
                        failures.append(f'{path.name}: <{tag.name} {attribute}="{candidate}">')
    return failures


def css_url_failures(path: Path, text: str) -> list[str]:
    failures = []
    for pattern, label in ((CSS_URL_PATTERN, "url()"), (CSS_IMPORT_PATTERN, "@import")):
        for match in pattern.finditer(text):
            target = match.group("target")
            if looks_external(target):
                failures.append(f"{path.name}: {label} {target}")
    return failures


def js_url_failures(path: Path, text: str) -> list[str]:
    # First-party scripts must not name an absolute URL; anything that needs
    # the network (the AI From-URL fetch) lives in server-side ai_recipe.py,
    # not in the browser bundle.
    return [f"{path.name}: {match.group(0)}" for match in JS_URL_PATTERN.finditer(text)]


def test_first_party_assets_load_no_external_resources():
    failures = []
    for path in first_party_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        suffix = path.suffix.lower()
        if suffix in {".html", ".svg"}:
            failures.extend(resource_attribute_failures(path, text))
        elif suffix == ".css":
            failures.extend(css_url_failures(path, text))
        elif suffix == ".js":
            failures.extend(js_url_failures(path, text))
    assert not failures, "first-party assets reference external resources:\n" + "\n".join(failures)


def test_vendored_katex_is_complete_and_self_contained():
    dist = ASSETS_DIRECTORY / "katex" / "dist"
    for required in ("katex.min.css", "katex.min.js", "contrib/auto-render.min.js"):
        assert (dist / required).is_file(), f"vendored KaTeX is missing {required}"

    failures = []
    for css in dist.rglob("*.css"):
        for match in CSS_URL_PATTERN.finditer(css.read_text(encoding="utf-8", errors="ignore")):
            target = match.group("target")
            if looks_external(target):
                failures.append(f"{css.name}: url({target})")
            elif target.startswith("data:") or target.startswith("#"):
                continue
            else:
                resolved = (css.parent / urlsplit(target).path).resolve()
                if not resolved.is_file():
                    failures.append(f"{css.name}: missing {target}")
    assert not failures, "vendored KaTeX references missing or external files:\n" + "\n".join(failures)


@pytest.fixture()
def generated_site(tmp_path: Path) -> Path:
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "dinner"
    recipe_directory.mkdir(parents=True)
    (recipe_directory / "recipe.md").write_text(RECIPE_MARKDOWN, encoding="utf-8")
    write_png(recipe_directory / "hero.png")

    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()
    return site


def test_generated_pages_load_no_external_resources(generated_site: Path):
    failures = []
    for path in sorted(generated_site.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup.find_all(True):
            for attribute, value in tag.attrs.items():
                if attribute not in RESOURCE_ATTRIBUTES:
                    continue
                if attribute == "href" and tag.name == "a":
                    # Recipe source links are user content; they are only
                    # fetched when the user clicks them.
                    continue
                values = value if isinstance(value, list) else [value]
                for item in values:
                    candidates = [item] if attribute != "srcset" else [entry.split()[0] for entry in item.split(",") if entry.split()]
                    for candidate in candidates:
                        if looks_external(candidate):
                            failures.append(f'{path.relative_to(generated_site)}: <{tag.name} {attribute}="{candidate}">')
        for match in CSS_URL_PATTERN.finditer(text):
            if looks_external(match.group("target")):
                failures.append(f"{path.relative_to(generated_site)}: url({match.group('target')})")
    assert not failures, "generated pages load external resources:\n" + "\n".join(failures)


def test_generated_site_references_only_existing_local_assets(generated_site: Path):
    failures = []
    for path in sorted(generated_site.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"/assets/[^\s\"'`)<>?#]+", text):
            referenced = (generated_site / match.group(0).lstrip("/")).resolve()
            if not referenced.is_file() and not referenced.is_dir():
                failures.append(f"{path.relative_to(generated_site)}: {match.group(0)}")
        if path.suffix.lower() == ".css":
            for match in CSS_URL_PATTERN.finditer(text):
                target = match.group("target")
                if looks_external(target) or target.startswith(("data:", "#")):
                    continue
                if target.startswith("/"):
                    resolved = (generated_site / urlsplit(target).path.lstrip("/")).resolve()
                else:
                    resolved = (path.parent / urlsplit(target).path).resolve()
                if not resolved.is_file():
                    failures.append(f"{path.relative_to(generated_site)}: {target}")
    assert not failures, "generated site references missing local assets:\n" + "\n".join(failures)


def test_generated_recipe_page_keeps_user_source_link_as_plain_navigation(generated_site: Path):
    page = BeautifulSoup((generated_site / "dinner" / "recipe.html").read_text(encoding="utf-8"), "html.parser")
    source_link = page.select_one('a[href="https://example.com/recipe"]')
    assert source_link is not None, "the recipe source link should render as a plain anchor"
    # It must not be pulled in as a resource (img/link/script).
    assert page.select_one('img[src="https://example.com/recipe"]') is None
    assert page.select_one('link[href="https://example.com/recipe"]') is None
    assert page.select_one('script[src="https://example.com/recipe"]') is None


def test_is_local_reference_boundaries():
    assert is_local_reference("")
    assert is_local_reference("#section")
    assert is_local_reference("data:image/png;base64,AAAA")
    assert is_local_reference("mailto:someone@example.com")
    assert is_local_reference("/assets/index.css")
    assert is_local_reference("fonts/KaTeX_Main-Regular.woff2")
    assert not is_local_reference("https://example.com/")
    assert not is_local_reference("//example.com/")
    assert not is_local_reference("javascript:alert(1)")
