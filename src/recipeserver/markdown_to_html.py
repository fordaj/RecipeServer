from pathlib import Path
from datetime import date
from html import escape
from .pallette import Pallette
from .config import Configuration
from .image_handler import ImageToColorConverter, get_first_image_in_dir
import markdown, re, frontmatter
from textwrap import dedent
from dataclasses import dataclass
from slugify import slugify
from enum import Enum, auto
from bs4 import BeautifulSoup, Tag
from fractions import Fraction
from ._logger import logger
import re, json
from coloraide import Color

# TODO: Move to definitions.py
_UNIT_ALIASES = {
    "tablespoons": "tbsp",
    "tablespoon": "tbsp",
    "teaspoons": "tsp",
    "teaspoon": "tsp",
    "cups": "cup",
    "milliliters": "mL",
    "milliliter": "mL",
    "ml": "mL",
    "l": "L",
    "lbs": "lb",
    "ounces": "oz",
    "ounce": "oz",
    "grams": "g",
    "gram": "g",
}

FILE_PATH = Path(__file__)
RECIPE_SCALER_HTML = FILE_PATH.parent / "assets" / "recipe-scaler.html"
# RECIPE_SCALER_CSS = FILE_PATH.parent / "assets" / "recipe-scaler.css"
# RECIPE_SCALER_JS = FILE_PATH.parent / "assets" / "recipe-scaler.js"
# RECIPE_JS = FILE_PATH.parent / "assets" / "recipe.js"
# CSS_PATH = FILE_PATH.parent / "assets" / "style.css"
# PULL_DOWN_PAGE_REFRESH_JS = FILE_PATH.parent / "assets" / "pull-down-page-refresh.js"
GAUGE_SVG = FILE_PATH.parent / "assets" / "gauge.svg"
CHEF_HAT_SVG = FILE_PATH.parent / "assets" / "chef-hat.svg"
POT_SVG = FILE_PATH.parent / "assets" / "cooking-pot.svg"
TAG_SVG = FILE_PATH.parent / "assets" / "tag.svg"
UTENSILS_SVG = FILE_PATH.parent / "assets" / "utensils.svg"

CSS_PATH = "/assets/style.css"
THEME_CSS_PATH = "/assets/theme.css"
RECIPE_JS = "/assets/recipe.js"
RECIPE_SCALER_CSS = "/assets/recipe-scaler.css"
RECIPE_EDITOR_JS = "/assets/recipe-editor.js"
RECIPE_EDITOR_CSS = "/assets/recipe-editor.css"
RECIPE_SCALER_JS = "/assets/recipe-scaler.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
BOOK_SVG = "/assets/book.svg"
LOGO_SVG = "/assets/logo.svg"
PENCIL_SVG = "/assets/pencil.svg"
# GAUGE_SVG = "/assets/gauge.svg"

MATHJAX = """
<script>
  window.MathJax = {
    tex: {
      inlineMath: [["$", "$"]]
    },
    options: {
      enableMenu: false,
      enableEnrichment: false,
      enableExplorer: false,
      enableExplorerHelp: false
    }
  };
</script>

<script defer src="/assets/mathjax/tex-chtml.js"></script>
"""

HOME_PAGE_ICON_HTML = """
<a href="/index.html" class="recipe-home">
    <svg class="recipe-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 6h4"/><path d="M2 10h4"/><path d="M2 14h4"/><path d="M2 18h4"/><rect width="16" height="20" x="4" y="2" rx="2"/><path d="M16 2v20"/>
    </svg>
</a>
"""

EDIT_RECIPE_HTML = f"""
<button id="edit-recipe"class="recipe-home" type="button" aria-label="Edit recipe" title="Edit recipe">
    <svg class="recipe-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>
    </svg>
</button>
"""


def dark_mode_color(hex_color):
    color = Color(hex_color).convert("oklch")
    L, C, H = color.coords()

    # Map lightness into a brighter range for dark backgrounds.
    new_L = 0.65 + (1.0 - L) * 0.20

    result = Color("oklch", [new_L, C, H])
    result = result.convert("srgb").fit()

    return result.to_string(hex=True)


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self.metadata: dict[str, object] = {}
        self.metadata_json: str = ""
        self.heading_color: str = Pallette.DEFAULT_TITLE

    def get_doc_specific_overrides(self) -> str:
        return dedent(f"""
            <style>
                :root {{
                    --food-color: {self.heading_color};
                }}
                @media (prefers-color-scheme: dark) {{
                    :root {{
                        --food-color: {dark_mode_color(self.heading_color)};
                    }}
                }}

                .recipe-icon {{
                    color: var(--food-color);
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: var(--food-color);
                }}
            </style>
        """)

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

    @staticmethod
    def _get_sanitized_unit(unit: str) -> str:
        normalized = unit.strip().lower()
        return _UNIT_ALIASES.get(normalized, unit.strip())

    def _mathjaxify_inline_code_blocks(self, content: str) -> str:
        def parse_quantity(
            value: str,
        ) -> tuple[float, str, float | None] | None:
            value = value.strip()
            if not value:
                return None

            number = r"(?:\d+/\d+|\d+(?:\.\d+)?)"
            mixed_number = rf"(?:\d+\s+\d+/\d+|{number})"

            # Range: "1-2 tbsp", "1/2-3/4 tsp",
            #        "1 1/2 - 2 1/2 tbsp", "1 1/2-2 1/2 tbsp"
            ranged = re.fullmatch(
                rf"({mixed_number})\s*[-–—]\s*({mixed_number})\s*(.*)",
                value,
            )
            if ranged:
                start, end, unit = ranged.groups()

                def to_float(amount: str) -> float:
                    parts = amount.split()
                    if len(parts) == 2:
                        return float(Fraction(parts[0])) + float(Fraction(parts[1]))
                    return float(Fraction(amount))

                return to_float(start), unit.strip(), to_float(end)

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

            unit = self._get_sanitized_unit(unit)

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

    def _append_svg_icon(
        self,
        parent: Tag,
        path: Path,
    ) -> None:
        svg = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").find("svg")

        if svg is None:
            raise ValueError(f"No SVG element found in {path}")

        svg["aria-hidden"] = "true"
        svg["focusable"] = "false"

        parent.append(svg)

    def _build_recipe_overview(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        overview = soup.new_tag("div", attrs={"class": "recipe-overview"})

        # First row: ratings, meals, difficulty
        primary = soup.new_tag("div", attrs={"class": "recipe-overview__primary"})

        ratings = metadata.get("ratings", [])

        if ratings:
            average = sum(item["rating"] for item in ratings) / len(ratings)

            rating = soup.new_tag(
                "span",
                attrs={"class": "recipe-overview__rating"},
            )
            rating.string = f"★ {average:.1f}/10"
            primary.append(rating)

        makes = metadata.get("makes", [])

        if makes:
            item = soup.new_tag(
                "span",
                attrs={"class": "recipe-overview__difficulty"},
            )
            self._append_svg_icon(
                item,
                CHEF_HAT_SVG,
            )
            item.append(f"x{makes}")

            primary.append(item)

        difficulty = metadata.get("difficulty")
        if difficulty is not None:
            item = soup.new_tag(
                "span",
                attrs={"class": "recipe-overview__difficulty"},
            )
            self._append_svg_icon(
                item,
                GAUGE_SVG,
            )
            item.append(f"{difficulty}/10")

            primary.append(item)

        meals = metadata.get("meals", [])
        if meals:
            meal = soup.new_tag("span", attrs={"class": "recipe-overview__meals"})
            self._append_svg_icon(
                meal,
                UTENSILS_SVG,
            )
            meal.append(", ".join(meals))
            primary.append(meal)

        if primary.contents:
            overview.append(primary)

        # Second row: categories and tags
        secondary = soup.new_tag("div", attrs={"class": "recipe-overview__secondary"})

        icons = {
            "categories": POT_SVG,
            "tags": TAG_SVG,
        }

        for key in ("categories", "tags"):
            values = metadata.get(key, [])
            if not values:
                continue

            group = soup.new_tag(
                "span",
                attrs={"class": f"recipe-overview__{key}"},
            )

            self._append_svg_icon(group, icons[key])

            for index, value in enumerate(values):
                if index:
                    group.append(", ")

                label = soup.new_tag("span")
                label.string = str(value)
                group.append(label)

            secondary.append(group)

        if secondary.contents:
            overview.append(secondary)

        return overview if overview.contents else None

    def _inject_recipe_overview(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")

        title = soup.find("h1")
        if title is None:
            return str(soup)

        # Find the hero image and its containing paragraph.
        hero = title.find_next("img")
        if hero is None:
            return str(soup)

        overview = soup.new_tag("div", attrs={"class": "recipe-overview"})

        # Build and append the metadata rows here.
        overview = self._build_recipe_overview(self.metadata, soup)
        if overview:
            hero.parent.insert_before(overview)

        # Insert the overview between the title and hero image.
        hero_parent = hero.parent
        hero_parent.insert_before(overview)

        return str(soup)

    def _postprocess(self, content: str) -> str:
        new_content = content
        new_content = self._mathjaxify_inline_code_blocks(new_content)
        new_content = self._enable_checkbox_inputs(new_content)
        new_content = self._inject_recipe_overview(new_content)
        return new_content

    def convert(self, markdown_file: Path, html_file: Path):
        # markdown_hash_file = markdown_file.with_suffix(".md.hash")
        # if markdown_hash_file.exists():
        #     # TODO: Check image hash(es)
        #     old_hash = markdown_file.read_text(encoding="UTF-8", newline="\n")
        #     if old_hash == self._get_file_hash(markdown_file):
        #         logger.debug(f"Skipping {markdown_file}, hashes match")

        logger.file(f"Converting {markdown_file.relative_to(self.cfg.source_directory)}")

        markdown_content = markdown_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        self._preprocess(markdown_content)
        title = self._get_title_from_markdown_content(markdown_content)

        # Set heading color
        dir = markdown_file.parent
        image = get_first_image_in_dir(dir)
        if image:
            logger.file(f"Found image: {image}")
            self.heading_color = ImageToColorConverter().get_hex_color_from_image(image)

        content = "\n".join(markdown_content)

        post = frontmatter.loads(content)

        self.metadata = post.metadata
        self._lint_metadata(markdown_file)
        self.metadata_json = json.dumps(self.metadata).replace("<", "\\u003c")  # sanitize input so it is not executable

        comments_html = ""
        if self.metadata.get("comments"):
            comments = []

            for comment in self.metadata["comments"]:
                author = comment.get("author", "Anonymous").strip() or "Anonymous"
                initials = "".join(part[0].upper() for part in author.split() if part)

                created = date.fromisoformat(comment["created"])
                text = escape(comment["text"])
                author = escape(author)
                initials = escape(initials)

                comments.append(dedent(f"""
                    <article class="recipe-comment">
                        <div class="recipe-comment__avatar" aria-hidden="true">{initials}</div>

                        <div class="recipe-comment__content">
                            <header class="recipe-comment__meta">
                                <span class="recipe-comment__author">{author}</span>
                                <time class="recipe-comment__date" datetime="{created.isoformat()}">
                                    {created.strftime("%B")} {created.day}, {created.year}
                                </time>
                            </header>

                            <p class="recipe-comment__text">{text}</p>
                        </div>
                    </article>
                """).strip())

            comments_html = dedent(f"""
                <section class="recipe-comments">
                <h2>Comments</h2>
                    {"".join(comments)}
                </section>
            """).strip()

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
            <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
            <link rel="stylesheet" href="{THEME_CSS_PATH}">
            <link rel="stylesheet" href="{CSS_PATH}">
            <link rel="stylesheet" href="{RECIPE_SCALER_CSS}">
            <link rel="stylesheet" href="{RECIPE_EDITOR_CSS}">
            {self.get_doc_specific_overrides()}
            {MATHJAX}
        </head>
        <body>
            <script id="recipe-metadata" type="application/json">{self.metadata_json}</script>
            <main class="recipe">
                <header class="recipe-header">
                    {HOME_PAGE_ICON_HTML}
                    {RECIPE_SCALER_HTML.read_text(encoding="UTF-8", newline="\n")}
                    {EDIT_RECIPE_HTML}
                </header>
                {body}
                {comments_html}
            </main>
            <script defer src="{RECIPE_JS}"></script>
            <script defer src="{RECIPE_SCALER_JS}"></script>
            <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            <script defer src="{RECIPE_EDITOR_JS}"></script>
        </body>
        </html>
        """)

        # Postprocess
        html = self._postprocess(html)

        # Write to file
        html_file.write_text(html, encoding="UTF-8", newline="\n")
        logger.debug(f'Created "{html_file}"')  # TODO get_pretty_path_str

        self.lint_html(html_file)

    def _lint_metadata(self, markdown_file: Path):
        has_meal_or_cuisine = "meals" in self.metadata or "cuisine" in self.metadata
        if not has_meal_or_cuisine:
            logger.warning(f'[MetadataWarning]{markdown_file}: Missing key "meals:" or "cuisine:"')

    def lint_html(self, html_file: Path):
        content = html_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        for i, line in enumerate(content):
            if "<code>" in line and "</code>" in line:
                logger.warning(f'Unprocessed quantity in "{html_file}:{i+1}"\n{line}')
