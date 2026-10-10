from pathlib import Path
from .pallette import Pallette
from .image_handler import ImageToColorConverter, get_first_image_in_dir
import markdown, re
from textwrap import dedent
from dataclasses import dataclass
from slugify import slugify
from enum import Enum, auto
from bs4 import BeautifulSoup
from fractions import Fraction
import re

FILE_PATH = Path(__file__)
CSS_PATH = FILE_PATH.parent / "assets" / "style.css"
SCRIPT_JS_PATH = FILE_PATH.parent / "assets" / "script.js"
MATHJAX = """
<script>
    window.MathJax = {
        tex: {
            inlineMath: [
                ["$", "$"]
            ]
        }
    };
</script>

<script
    async
    src="https://cdn.jsdelivr.net/npm/mathjax@4/tex-mml-chtml.js">
</script>
"""
RECIPE_SCALAR_HTML = """
<div class="recipe-scaler">
    <label for="recipe-scale">Scale</label>
    <input id="recipe-scale" type="number" min="0.125" step="0.125" value="1" />
</div>
"""


@dataclass
class Configuration:
    heading_color: str = Pallette.DEFAULT_TITLE

    def get_doc_specific_overrides(self) -> str:
        return dedent(f"""
            <style>
                h1, h2, h3, h4, h5, h6 {{
                    color: {self.heading_color};
                }}
            </style>
        """)


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration = Configuration()):
        self.cfg = cfg

    def _get_title_from_markdown_content(self, content: list[str]) -> str:

        for line in content:
            if line.startswith("# "):
                return line.replace("# ", "")

    def _break_up_div_comments(self, markdown: list[str]) -> None:
        for i, line in enumerate(markdown):
            if (":::" in line or "///" in line) and ("<!--" in line):
                # Add a newline before the comment
                markdown[i] = line.replace("<!--", "\n<!--")

    def _preprocess(self, content: list[str]) -> None:
        self._break_up_div_comments(content)

    def _mathjaxify_inline_code_blocks(self, content: str) -> str:
        def parse_quantity(value: str) -> tuple[float, str] | None:
            parts = value.strip().split()

            if not parts:
                return None

            # The first token must be a number.
            try:
                number = float(Fraction(parts[0]))
            except ValueError:
                return None

            # Support mixed numbers such as "1 1/2".
            unit_start = 1

            if len(parts) > 1:
                try:
                    number += float(Fraction(parts[1]))
                    unit_start = 2
                except ValueError:
                    pass

            # There must be something after the quantity.
            if unit_start >= len(parts):
                return None

            unit = " ".join(parts[unit_start:])

            return number, unit

        soup = BeautifulSoup(content, "html.parser")

        for code in soup.find_all("code"):
            parsed = parse_quantity(code.get_text(strip=True))

            if parsed is None:
                continue

            quantity, unit = parsed

            span = soup.new_tag("span")
            span["class"] = "quantity"
            span["data-quantity"] = str(quantity)
            span["data-unit"] = unit

            code.replace_with(span)

        return str(soup)

    def _enable_checkbox_inputs(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        # Remove the "disabled" attribute from <input checkbox> elements
        for checkbox in soup.select('input[type="checkbox"]'):
            checkbox.attrs.pop("disabled", None)

        return str(soup)

    def _postprocess(self, content: str) -> str:
        new_content = content
        new_content = self._mathjaxify_inline_code_blocks(new_content)
        new_content = self._enable_checkbox_inputs(new_content)
        return new_content

    def convert(self, markdown_file: Path, html_file: Path):
        print(
            f"Converting {markdown_file.relative_to(Path.cwd())} to {html_file.relative_to(Path.cwd())}"
        )
        markdown_content = markdown_file.read_text(
            encoding="UTF-8", newline="\n"
        ).splitlines()
        self._preprocess(markdown_content)
        title = self._get_title_from_markdown_content(markdown_content)

        # Set heading color
        dir = markdown_file.parent
        image = get_first_image_in_dir(dir)
        if image:
            print(f"Found image: {image}")
            self.cfg.heading_color = ImageToColorConverter().get_hex_color_from_image(
                image
            )

        md = markdown.Markdown(
            extensions=[
                "pymdownx.extra",
                "pymdownx.blocks.html",
                "pymdownx.tasklist",
                "pymdownx.arithmatex",
            ]
        )
        body = md.convert("\n".join(markdown_content))

        # Build HTML
        html = dedent(f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
            {CSS_PATH.read_text(encoding="UTF-8", newline="\n")}
            </style>
            {self.cfg.get_doc_specific_overrides()}
            {MATHJAX}
        </head>
        <body>
            <a href="../../index.html">Back to Home</a>
            <main class="recipe">
                {RECIPE_SCALAR_HTML}
                {body}
            </main>
            <script>
            {SCRIPT_JS_PATH.read_text(encoding="UTF-8", newline="\n")}
            </script>
        </body>
        </html>
        """)

        # Postprocess
        html = self._postprocess(html)

        # Write to file
        html_file.write_text(html, encoding="UTF-8", newline="\n")
