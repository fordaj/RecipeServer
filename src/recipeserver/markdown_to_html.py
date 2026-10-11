from pathlib import Path
from .pallette import Pallette
from .image_handler import ImageToColorConverter, get_first_image_in_dir
import markdown, re, frontmatter
from textwrap import dedent
from dataclasses import dataclass
from slugify import slugify
from enum import Enum, auto
from bs4 import BeautifulSoup
from fractions import Fraction
from ._logger import logger
import re, json

FILE_PATH = Path(__file__)
CSS_PATH = FILE_PATH.parent / "assets" / "style.css"
SCRIPT_JS_PATH = FILE_PATH.parent / "assets" / "script.js"
PULL_DOWN_PAGE_REFRESH_JS = FILE_PATH.parent / "assets" / "pull-down-page-refresh.js"
BOOK_SVG = FILE_PATH.parent / "assets" / "book.svg"

MATHJAX = """
<script>
  window.MathJax = {
    tex: {
      inlineMath: [["$", "$"]]
    }
  };
</script>

<script defer src="https://cdn.jsdelivr.net/npm/mathjax@4/tex-mml-chtml.js"></script>
"""
RECIPE_SCALAR_HTML = """
<style>
#recipe-scale {
    color: var(--food-color);
    font-size: 32px;
    font-family: inherit;
    font-weight: 500;

    background: transparent;
    border: none;
    outline: none;

    width: 4ch;
    padding: 0;
    margin: 0;

    text-align: right;
    appearance: textfield;
}

#recipe-scale::-webkit-inner-spin-button,
#recipe-scale::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
}

.recipe-scaler {
    display: inline-flex;
    align-items: baseline;
    color: var(--food-color);
    font-size: 32px;
}

.recipe-scaler span {
    font-size: 32px;
}

/* Larger screens */
@media (min-width: 768px) {
    #recipe-scale {
        font-size: 40px;
    }

    .recipe-scaler,
    .recipe-scaler span {
        font-size: 40px;
    }
}
</style>
<div class="recipe-scaler">
    <input id="recipe-scale" min="0.125" step="0.125" type="number" value="1.0">
    <span>×</span>
</div>
"""

HOME_PAGE_ICON_HTML = """
<a href="/index.html" class="recipe-home">
    <svg class="recipe-icon" viewBox="0 0 24 24" aria-hidden="true" stroke-width="1.5" stroke="currentColor" fill="none">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
    </svg>
</a>
"""


@dataclass
class Configuration:
    heading_color: str = Pallette.DEFAULT_TITLE

    def get_doc_specific_overrides(self) -> str:
        return dedent(f"""
            <style>
                :root {{
                    --food-color: {self.heading_color};
                }}

                .recipe-icon {{
                    color: var(--food-color);
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: var(--food-color);
                }}
            </style>
        """)


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration = Configuration()):
        self.cfg = cfg
        self.metadata: dict[str, object] = {}
        self.metadata_json: str = ""

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

        def parse_quantity(
            value: str,
        ) -> tuple[float, str, float | None] | None:
            value = value.strip()
            if not value:
                return None

            number = r"(?:\d+/\d+|\d+(?:\.\d+)?)"

            # Mixed number: "1 1/2 tbsp"
            mixed = re.fullmatch(
                rf"(\d+)\s+(\d+/\d+)\s*(.*)",
                value,
            )
            if mixed:
                whole, fraction, unit = mixed.groups()
                return (
                    float(Fraction(whole)) + float(Fraction(fraction)),
                    unit.strip(),
                    None,
                )

            # Range: "2-3 pizzas", "1/2-3/4 tsp"
            ranged = re.fullmatch(
                rf"({number})\s*[-–—]\s*({number})\s*(.*)",
                value,
            )
            if ranged:
                start, end, unit = ranged.groups()
                return float(Fraction(start)), unit.strip(), float(Fraction(end))

            # Single number/fraction with optional attached or spaced unit
            single = re.fullmatch(rf"({number})\s*(.*)", value)
            if single:
                amount, unit = single.groups()
                return float(Fraction(amount)), unit.strip(), None

            return None

        soup = BeautifulSoup(content, "html.parser")

        for code in soup.find_all("code"):
            parsed = parse_quantity(code.get_text(strip=True))

            if parsed is None:
                continue

            quantity, unit, quantity_end = parsed

            span = soup.new_tag("span")
            span["class"] = "quantity"
            span["data-quantity"] = str(quantity)
            span["data-unit"] = unit

            if quantity_end is not None:
                span["data-quantity-end"] = str(quantity_end)

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
        # markdown_hash_file = markdown_file.with_suffix(".md.hash")
        # if markdown_hash_file.exists():
        #     # TODO: Check image hash(es)
        #     old_hash = markdown_file.read_text(encoding="UTF-8", newline="\n")
        #     if old_hash == self._get_file_hash(markdown_file):
        #         logger.debug(f"Skipping {markdown_file}, hashes match")

        logger.file(f"Converting {markdown_file.relative_to(Path.cwd())}")

        markdown_content = markdown_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        self._preprocess(markdown_content)
        title = self._get_title_from_markdown_content(markdown_content)

        # Set heading color
        dir = markdown_file.parent
        image = get_first_image_in_dir(dir)
        if image:
            logger.file(f"Found image: {image}")
            self.cfg.heading_color = ImageToColorConverter().get_hex_color_from_image(image)

        content = "\n".join(markdown_content)

        post = frontmatter.loads(content)

        self.metadata = post.metadata
        self.metadata_json = json.dumps(self.metadata).replace("<", "\\u003c")  # sanitize input so it is not executable

        markdown_body = post.content

        md = markdown.Markdown(
            extensions=[
                "pymdownx.extra",
                "pymdownx.blocks.html",
                "pymdownx.tasklist",
                "pymdownx.arithmatex",
            ]
        )

        body = md.convert(markdown_body)

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
            <script id="recipe-metadata" type="application/json">
                {self.metadata_json}
            </script>
            <main class="recipe">
                <header class="recipe-header">
                    {HOME_PAGE_ICON_HTML}
                    {RECIPE_SCALAR_HTML}
                </header>
                {body}
            </main>
            <script defer>
            {SCRIPT_JS_PATH.read_text(encoding="UTF-8", newline="\n")}
            </script>
            <script defer>
            {PULL_DOWN_PAGE_REFRESH_JS.read_text(encoding="UTF-8", newline="\n")}
            </script>
        </body>
        </html>
        """)

        # Postprocess
        html = self._postprocess(html)

        # Write to file
        html_file.write_text(html, encoding="UTF-8", newline="\n")
        logger.info(f"Created {html_file.relative_to(Path.cwd())}")

        self.lint_html(html_file)

    def lint_html(self, html_file: Path):
        content = html_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        for i, line in enumerate(content):
            if "<code>" in line and "</code>" in line:
                logger.warning(f'Unprocessed quantity in "{html_file}:{i+1}"\n{line}')
