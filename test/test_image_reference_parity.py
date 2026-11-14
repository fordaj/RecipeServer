"""Contract tests keeping the browser's image helpers in sync with the server.

recipe-editor.js mirrors image_handler.IMAGE_EXTENSIONS and the server's
image-reference regexes (_MARKDOWN_IMAGE_RE / _HTML_IMG_RE and
_first_image_reference) because the browser cannot import the Python
originals. These tests fail loudly when either side drifts.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from recipeserver.image_handler import IMAGE_EXTENSIONS
from recipeserver.server import _first_image_reference, _basename_of_src, _is_external_src

BASE = Path(__file__).parents[1] / "src" / "recipeserver"
EDITOR_JS = BASE / "assets" / "recipe-editor" / "recipe-editor.js"


def _editor_image_section() -> str:
    source = EDITOR_JS.read_text(encoding="utf-8")
    start = source.index("  // ----- Existing images and main image ----- //")
    end = source.index("  // ----- Initialize: DOM refs and state ----- //")
    return "\n".join(line[2:] for line in source[start:end].splitlines())


def _editor_extension_set() -> set[str]:
    source = EDITOR_JS.read_text(encoding="utf-8")
    block = source.split("const CLIENT_IMAGE_EXTENSIONS = new Set([", 1)[1].split("]);", 1)[0]
    return {line.strip().strip('",') for line in block.splitlines() if line.strip()}


def test_client_image_extensions_match_server():
    assert _editor_extension_set() == set(IMAGE_EXTENSIONS)


# Fixtures exercised on both sides. Each entry is (id, content).
FIXTURES = [
    ("markdown", "# Soup\n\n![Hero](soup.png)\n"),
    ("html_img", '<p><img src="soup.jpg" alt="Soup"></p>\n'),
    ("markdown_query_fragment", "![x](soup.png?w=100#frag)\n"),
    ("angle_brackets", "![x](<my img.png>)\n"),
    ("angle_brackets_title", '![x](<my img.png> "A title")\n'),
    ("markdown_title", '![x](soup.png "A title")\n'),
    ("markdown_first_wins", '![md](markdown.png)\n\n<img src="html.jpg">\n'),
    ("html_first_wins", '<img src="html.jpg">\n\n![md](markdown.png)\n'),
    ("html_encoded_entity", '<img src="soup.png?x=1&amp;y=2">\n'),
    ("markdown_external", "![x](https://example.com/hero.png)\n"),
    ("html_external", '<img src="https://example.com/hero.png">\n'),
    ("markdown_none", "# No images here\n"),
    ("markdown_html_mixed", 'Text\n\n![md](<m d.png> "cap")\n\nafter\n'),
    ("html_case_insensitive_tag", '<IMG SRC="soup.gif">\n'),
]


def _js_first_image_references() -> list[dict | None]:
    script = f"""
const fs = require("fs");
{_editor_image_section()}
const fixtures = {json.dumps([content for _, content in FIXTURES])};
const results = fixtures.map((content) => {{
  const first = findFirstImageReference(content);
  if (!first) return null;
  return {{
    kind: first.kind,
    src: first.src,
    basename: basenameOf(first.src),
    external: isExternalSrc(first.src),
  }};
}});
process.stdout.write(JSON.stringify(results));
"""
    result = subprocess.run(
        [shutil.which("node"), "-"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _python_first_image_references() -> list[dict | None]:
    results = []
    for _, content in FIXTURES:
        first = _first_image_reference(content)
        if first is None:
            results.append(None)
            continue
        results.append(
            {
                "kind": first["kind"],
                "src": first["src"],
                "basename": _basename_of_src(first["src"]),
                "external": _is_external_src(first["src"]),
            }
        )
    return results


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_first_image_reference_parity_between_server_and_editor():
    expected = _python_first_image_references()
    actual = _js_first_image_references()
    for (name, _), py, js in zip(FIXTURES, expected, actual):
        assert js == py, f"fixture {name!r} drifted between server and editor"
