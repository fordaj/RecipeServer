from pathlib import Path
from datetime import date, datetime, time
from html import escape
from functools import lru_cache
from .pallette import Pallette
from .config import Configuration
from .image_handler import ImageToColorConverter, get_first_image_in_dir
import json, math, markdown, re, frontmatter
from textwrap import dedent
from bs4 import BeautifulSoup, Tag
from fractions import Fraction
from ._logger import logger
from coloraide import Color
from importlib.metadata import version

VERSION = version("recipeserver")

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
GAUGE_SVG = FILE_PATH.parent / "assets" / "gauge.svg"
CHEF_HAT_SVG = FILE_PATH.parent / "assets" / "chef-hat.svg"
POT_SVG = FILE_PATH.parent / "assets" / "cooking-pot.svg"
TAG_SVG = FILE_PATH.parent / "assets" / "tag.svg"
QUILL_SVG = FILE_PATH.parent / "assets" / "quill.svg"
UTENSILS_SVG = FILE_PATH.parent / "assets" / "utensils.svg"
PIN_SVG = FILE_PATH.parent / "assets" / "pin.svg"
BOOK_SVG = FILE_PATH.parent / "assets" / "book.svg"
AI_SVG = FILE_PATH.parent / "assets" / "ai.svg"
USER_SVG = FILE_PATH.parent / "assets" / "user.svg"
LINK_SVG = FILE_PATH.parent / "assets" / "link.svg"

CSS_PATH = "/assets/style.css"
THEME_CSS_PATH = "/assets/theme.css"
RECIPE_JS = "/assets/recipe.js"
RECIPE_SCALER_CSS = "/assets/recipe-scaler.css"
RECIPE_EDITOR_JS = "/assets/recipe-editor.js"
RECIPE_EDITOR_CSS = "/assets/recipe-editor.css"
RECIPE_SCALER_JS = "/assets/recipe-scaler.js"
COMMENTS_CSS = "/assets/comments.css"
COMMENTS_JS = "/assets/comments.js"
RATINGS_CSS = "/assets/ratings.css"
RATINGS_JS = "/assets/ratings.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

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


def _json_default(value: object) -> str:
    """Serialize YAML dates that JSON does not understand."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _parse_datetime(value: object) -> datetime | None:
    """Parse metadata timestamps without letting bad data break a build."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _as_list(value: object) -> list:
    """Return metadata values as a list, accepting scalar strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


@lru_cache(maxsize=None)
def _read_svg(asset_path: Path) -> str:
    return asset_path.read_text(encoding="utf-8")


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self.metadata: dict[str, object] = {}
        self.metadata_json: str = ""
        self.heading_color: str = Pallette.DEFAULT_TITLE
        self.title: str = ""

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

    @staticmethod
    def _get_title_from_markdown_content(content: list[str]) -> str | None:
        """Return the first level-one heading, ignoring fenced code blocks."""
        in_fence = False

        for line in content:
            stripped = line.lstrip()

            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue

            if in_fence:
                continue

            match = re.match(r"^ {0,3}#\s+(.*?)\s*#*\s*$", line)
            if match and match.group(1).strip():
                return match.group(1).strip()

        return None

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

    def _mathjaxify_inline_code_blocks(self, soup: BeautifulSoup) -> None:
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

    def _enable_checkbox_inputs(self, soup: BeautifulSoup) -> None:
        # Remove the "disabled" attribute from <input checkbox> elements
        for checkbox in soup.select('input[type="checkbox"]'):
            checkbox.attrs.pop("disabled", None)

    def _append_svg_icon(
        self,
        parent: Tag,
        path: Path,
    ) -> None:
        svg = BeautifulSoup(_read_svg(path), "html.parser").find("svg")

        if svg is None:
            raise ValueError(f"No SVG element found in {path}")

        svg["aria-hidden"] = "true"
        svg["focusable"] = "false"

        parent.append(svg)

    def _build_recipe_overview(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        overview = soup.new_tag("div", attrs={"class": "recipe-overview"})

        # First row: ratings, meals, difficulty
        primary = soup.new_tag("div", attrs={"class": "recipe-overview__primary"})

        ratings = metadata.get("ratings")
        rating_scores = [
            score
            for rating in _as_list(ratings)
            if isinstance(rating, dict)
            and isinstance((score := rating.get("rating")), (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
        ]

        if rating_scores:
            average = sum(rating_scores) / len(rating_scores)

            rating = soup.new_tag(
                "span",
                attrs={"class": "recipe-overview__rating"},
            )
            rating.string = f"★ {average:.1f}/10"
            primary.append(rating)

        makes = metadata.get("makes")

        if isinstance(makes, list):
            makes = makes[0] if makes else None

        if makes is not None and makes != "":
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

        if isinstance(difficulty, list):
            difficulty = difficulty[0] if difficulty else None

        if difficulty is not None and difficulty != "":
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

        meals = _as_list(metadata.get("meals"))
        if meals:
            meal = soup.new_tag("span", attrs={"class": "recipe-overview__meals"})
            self._append_svg_icon(
                meal,
                UTENSILS_SVG,
            )
            meal.append(", ".join(str(value) for value in meals))
            primary.append(meal)

        if primary.contents:
            overview.append(primary)

        # Second row: cuisine, categories, and tags
        secondary = soup.new_tag("div", attrs={"class": "recipe-overview__secondary"})

        icons = {
            "cuisine": PIN_SVG,
            "categories": POT_SVG,
            "tags": TAG_SVG,
        }

        for key in ("cuisine", "categories", "tags"):
            values = _as_list(metadata.get(key))
            if key == "categories" and not values:
                values = _as_list(metadata.get("category"))
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

    def _inject_recipe_overview(self, soup: BeautifulSoup) -> None:
        title = soup.find("h1")
        if title is None:
            return

        hero = title.find_next("img")
        if hero is None:
            return

        overview = self._build_recipe_overview(self.metadata, soup)
        if overview:
            hero.parent.insert_before(overview)

    def _build_recipe_contributor(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        contributor = metadata.get("contributor", "")

        if isinstance(contributor, (list, tuple)):
            contributor = ", ".join(str(value) for value in contributor if value)

        if not isinstance(contributor, str):
            contributor = str(contributor or "")

        contributor = contributor.strip()

        if not contributor:
            return None

        created_on = _parse_datetime(metadata.get("createdOn"))

        item = soup.new_tag(
            "div",
            attrs={"class": "recipe-contributor"},
        )

        self._append_svg_icon(item, QUILL_SVG)

        label = soup.new_tag("span")
        label.string = f"by {contributor}"

        if created_on:
            separator = soup.new_tag(
                "span",
                attrs={"class": "recipe-meta__separator"},
            )
            separator.string = "·"
            label.append(separator)

            time = soup.new_tag("time", datetime=created_on.date().isoformat())
            time.string = f"{created_on:%b} {created_on.day}"
            if datetime.now().year != created_on.year:
                time.string += f", {created_on.year}"
            label.append(time)

        item.append(label)

        return item

    def _inject_recipe_contributor(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        contributor = self._build_recipe_contributor(self.metadata, soup)
        if contributor:
            main.append(contributor)

    def _build_recipe_sources(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        sources = metadata.get("source")

        if isinstance(sources, dict):
            sources = [sources]
        elif not isinstance(sources, list):
            sources = []

        container = soup.new_tag(
            "div",
            attrs={"class": "recipe-sources"},
        )

        for source in sources:
            if not isinstance(source, dict):
                continue

            source_format = str(source.get("format") or "").lower()
            title = str(source.get("title") or "").strip()
            author = str(source.get("author") or "").strip()
            url = str(source.get("url") or "").strip()

            if source_format == "website":
                title = title or str(source.get("company") or "").strip()
                icon = LINK_SVG
            elif source_format == "book":
                icon = BOOK_SVG
            elif source_format == "ai":
                icon = AI_SVG
            else:
                icon = USER_SVG

            if not title:
                continue

            item = soup.new_tag(
                "span",
                attrs={"class": "recipe-sources__item"},
            )

            self._append_svg_icon(item, icon)

            if source_format == "website" and url:
                label = soup.new_tag(
                    "a",
                    href=url,
                    attrs={
                        "target": "_blank",
                        "rel": "noopener noreferrer",
                    },
                )
            else:
                label = soup.new_tag("span")

            label.string = title
            item.append(label)

            if author:
                author_group = soup.new_tag(
                    "span",
                    attrs={"class": "recipe-sources__author"},
                )

                self._append_svg_icon(author_group, USER_SVG)

                label = soup.new_tag("span")
                label.string = author
                author_group.append(label)

                item.append(author_group)

            container.append(item)

        return container if container.contents else None

    def _inject_recipe_sources(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        sources = self._build_recipe_sources(self.metadata, soup)
        if sources:
            main.append(sources)

    def _build_recipe_version(self, metadata: dict, soup: BeautifulSoup) -> Tag:
        version = soup.new_tag(
            "div",
            attrs={"class": "recipe-version"},
        )

        self._append_svg_icon(version, TAG_SVG)

        label = soup.new_tag("span")

        updated_on = _parse_datetime(metadata.get("updatedOn"))
        label.append(f"v{VERSION}")

        if updated_on:
            separator = soup.new_tag(
                "span",
                attrs={"class": "recipe-meta__separator"},
            )
            separator.string = "·"
            label.append(separator)

            time = soup.new_tag("time", datetime=updated_on.date().isoformat())
            time.string = f"Edited {updated_on:%b} {updated_on.day}"
            if datetime.now().year != updated_on.year:
                time.string += f", {updated_on.year}"
            label.append(time)

        version.append(label)

        return version

    def _inject_recipe_version(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        version = self._build_recipe_version(self.metadata, soup)
        main.append(version)

    def _postprocess(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        self._mathjaxify_inline_code_blocks(soup)
        self._enable_checkbox_inputs(soup)
        self._inject_recipe_overview(soup)
        self._inject_recipe_contributor(soup)
        self._inject_recipe_sources(soup)
        self._inject_recipe_version(soup)

        heading = soup.find("h1")
        if heading is not None:
            rendered_title = heading.get_text(" ", strip=True)
            if rendered_title:
                self.title = rendered_title

        return str(soup)

    def _get_comments_html(self) -> str:
        return dedent(f"""
            <section class="recipe-comments" id="recipe-comments">
                <h2 class="recipe-comments__heading">
                    <span>Comments</span>
                    <button class="recipe-comments__add" type="button" aria-label="Add a comment" aria-expanded="false">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M12 5v14M5 12h14"/>
                    </svg>
                    </button>
                </h2>
                <form id="recipe-comment-form" class="recipe-comment-form" hidden>
                <div class="recipe-comment__avatar recipe-comment-form__avatar" aria-hidden="true">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 21a8 8 0 0 0-16 0" />
                    <circle cx="12" cy="8" r="4" />
                    </svg>
                </div>

                <div class="recipe-comment__content">
                    <div class="recipe-comment__meta">
                    <input id="comment-author" class="recipe-comment__author-input" type="text" placeholder="Your name" aria-label="Your name" required/>
                    <span class="recipe-comment__date">Posting today</span>
                    </div>

                    <textarea id="comment-text" class="recipe-comment__text-input" placeholder="Write a comment..." aria-label="Comment" rows="3" required ></textarea>

                    <div class="recipe-comment__actions recipe-comment-form__actions">
                    <button id="cancel-comment" type="button">Cancel</button>
                    <button id="save-comment" type="submit">Post comment</button>
                    </div>

                    <p id="comment-status" role="status" aria-live="polite"></p>
                </div>
                </form>
                <div class="recipe-comments__list" id="comment-list"></div>
            </section>
        """).strip()

    def _get_ratings_html(self) -> str:
        return dedent("""
            <section class="recipe-ratings" id="recipe-ratings">
                <h2 class="recipe-ratings__heading">
                    <span>Ratings</span>
                    <button class="recipe-ratings__add" type="button" aria-label="Add a rating" aria-expanded="false">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M12 5v14M5 12h14"/>
                    </svg>
                    </button>
                </h2>
                <form id="recipe-rating-form" class="recipe-rating-form" hidden>
                    <div class="recipe-rating__avatar recipe-rating-form__avatar" aria-hidden="true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M20 21a8 8 0 0 0-16 0" />
                            <circle cx="12" cy="8" r="4" />
                        </svg>
                    </div>
                    <div class="recipe-rating-form__content">
                        <div class="recipe-rating-form__meta">
                            <input id="rating-author" type="text" placeholder="Your name" aria-label="Your name" maxlength="100" required />
                        </div>
                        <div class="recipe-rating__meter recipe-rating-form__meter">
                            <input id="rating-score" type="text" inputmode="decimal" maxlength="16" value="5" aria-label="Rating out of 10" required />
                            <span class="recipe-rating__stars" role="img" aria-label="5 out of 10">★★★★★</span>
                            <output id="rating-score-value" class="recipe-rating__score">5/10</output>
                        </div>
                        <div class="recipe-rating__actions recipe-rating-form__actions">
                            <button id="cancel-rating" type="button">Cancel</button>
                            <button id="save-rating" type="submit">Post rating</button>
                        </div>
                        <p id="rating-status" role="status" aria-live="polite"></p>
                    </div>
                </form>
                <div class="recipe-ratings__list" id="rating-list"></div>
            </section>
        """).strip()

    @staticmethod
    def _deslugify(slug: str) -> str:
        return slug.replace("-", " ").replace("_", " ").title()

    def convert(self, markdown_file: Path, html_file: Path):
        logger.file(f"Converting {markdown_file.relative_to(self.cfg.source_directory)}")

        markdown_content = markdown_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        self._preprocess(markdown_content)

        content = "\n".join(markdown_content)
        post = frontmatter.loads(content)
        self.metadata = post.metadata

        title = (
            self._get_title_from_markdown_content(post.content.splitlines())
            or str(post.metadata.get("title") or "").strip()
            or self._deslugify(markdown_file.parent.name)
        )
        self.title = title

        # Set heading color
        image = get_first_image_in_dir(markdown_file.parent)
        if image:
            logger.file(f"Found image: {image}")
            try:
                self.heading_color = ImageToColorConverter().get_hex_color_from_image(image)
            except (OSError, ValueError) as exc:
                logger.warning(f'Could not derive an accent color from "{image}": {exc}')

        self._lint_metadata(markdown_file)
        self.metadata_json = json.dumps(self.metadata, default=_json_default).replace(
            "<", "\\u003c"
        )  # sanitize input so it is not executable

        comments_html = self._get_comments_html()
        ratings_html = self._get_ratings_html()

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
            <title>{escape(title)}</title>
            <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
            <link rel="stylesheet" href="{THEME_CSS_PATH}">
            <link rel="stylesheet" href="{CSS_PATH}">
            <link rel="stylesheet" href="{RECIPE_SCALER_CSS}">
            <link rel="stylesheet" href="{RECIPE_EDITOR_CSS}">
            <link rel="stylesheet" href="{COMMENTS_CSS}">
            <link rel="stylesheet" href="{RATINGS_CSS}">
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
                {ratings_html}
                {comments_html}
            </main>
            <script defer src="{RECIPE_JS}"></script>
            <script defer src="{RECIPE_SCALER_JS}"></script>
            <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            <script defer src="{COMMENTS_JS}"></script>
            <script defer src="{RATINGS_JS}"></script>
            <script defer src="{RECIPE_EDITOR_JS}"></script>
        </body>
        </html>
        """)

        # Postprocess
        html = self._postprocess(html)

        # Write to file
        html_file.write_text(html, encoding="UTF-8", newline="\n")
        logger.debug(f'Created "{html_file}"')  # TODO get_pretty_path_str

        self.lint_html(html, html_file)

    def _lint_metadata(self, markdown_file: Path):
        has_meal_or_cuisine = "meals" in self.metadata or "cuisine" in self.metadata
        if not has_meal_or_cuisine:
            logger.warning(f'[MetadataWarning]{markdown_file}: Missing key "meals:" or "cuisine:"')

    def lint_html(self, html: str, html_file: Path):
        for i, line in enumerate(html.splitlines()):
            if "<code>" in line and "</code>" in line:
                logger.warning(f'Unprocessed quantity in "{html_file}:{i+1}"\n{line}')
