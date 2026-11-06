from pathlib import Path
from types import SimpleNamespace
import json

from bs4 import BeautifulSoup
from PIL import Image

from recipeserver.markdown_to_html import VERSION, MarkdownToHTMLConverter


def write_png(path: Path, color: tuple[int, int, int] = (200, 70, 30)) -> None:
    Image.new("RGB", (8, 8), color).save(path)


def convert_recipe(
    tmp_path: Path,
    content: str,
    files: dict[str, bytes] | None = None,
) -> tuple[MarkdownToHTMLConverter, Path]:
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "recipe"
    recipe_directory.mkdir(parents=True)

    for name, data in (files or {}).items():
        (recipe_directory / name).write_bytes(data)

    recipe = recipe_directory / "recipe.md"
    recipe.write_text(content, encoding="utf-8")

    html_file = site / "recipe" / "recipe.html"
    html_file.parent.mkdir(parents=True)

    converter = MarkdownToHTMLConverter(
        SimpleNamespace(source_directory=source, site_directory=site)
    )
    converter.convert(recipe, html_file)

    return converter, html_file


def test_conversion_renders_recipe_page_from_markdown_and_metadata(tmp_path: Path):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "thai-curry"
    recipe_directory.mkdir(parents=True)
    write_png(recipe_directory / "image.png")

    recipe = recipe_directory / "recipe.md"
    recipe.write_text(
        """---
title: Metadata title
tags:
  - "<script>alert(1)</script>"
  - Quick
cuisine:
  - Thai
categories:
  - Dinner
meals:
  - Dinner
makes: 4
difficulty: 3
contributor: Avery
createdOn: "2024-06-15T12:30:00Z"
updatedOn: "2024-07-20T12:30:00Z"
ratings:
  - rating: 8
  - rating: 9
source:
  - format: website
    title: Family Baking
    url: https://example.com/recipe
  - format: book
    title: The Baking Book
    author: Avery
---
# Thai Curry

![Curry](image.png)

## Ingredients

- [ ] `1 1/2 tablespoons` curry paste
- [ ] `1-2 tbsp` fish sauce
- [ ] `2 eggs`

## Method

Mix everything.
""",
        encoding="utf-8",
    )

    html_file = site / "thai-curry" / "recipe.html"
    html_file.parent.mkdir(parents=True)
    converter = MarkdownToHTMLConverter(
        SimpleNamespace(source_directory=source, site_directory=site)
    )
    converter.convert(recipe, html_file)

    raw_html = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw_html, "html.parser")

    assert soup.title.string == "Thai Curry"
    assert soup.select_one("main.recipe h1").get_text(strip=True) == "Thai Curry"
    assert soup.select_one("main.recipe h2").get_text(strip=True) == "Ingredients"
    assert "Mix everything." in soup.select_one("main.recipe").get_text()

    metadata_script = soup.select_one('script#recipe-metadata[type="application/json"]')
    assert metadata_script is not None
    metadata = json.loads(metadata_script.string)
    assert metadata["tags"] == ["<script>alert(1)</script>", "Quick"]
    assert metadata["categories"] == ["Dinner"]
    assert "\\u003cscript>" in raw_html
    assert "<script>alert(1)</script>" not in raw_html

    header = soup.select_one("header.recipe-header")
    assert header.select_one("a.recipe-home[href='/index.html']") is not None
    scaler = header.select_one(".recipe-scaler")
    assert scaler is not None
    assert "recipe-scaler--loading" in scaler["class"]
    assert scaler.select_one("select#recipe-scale-select") is not None
    custom_scale = scaler.select_one("input#recipe-scale-custom")
    assert custom_scale is not None
    assert custom_scale.has_attr("hidden")
    assert header.select_one("button#edit-recipe") is not None

    overview = soup.select_one(".recipe-overview")
    assert overview is not None
    assert overview.select_one(".recipe-overview__rating").get_text(strip=True) == "★ 8.5/10"
    assert [span.get_text(strip=True) for span in overview.select(".recipe-overview__difficulty")] == [
        "x4",
        "3/10",
    ]
    assert overview.select_one(".recipe-overview__meals").get_text(" ", strip=True) == "Dinner"
    assert overview.select_one(".recipe-overview__cuisine").get_text(" ", strip=True) == "Thai"
    assert overview.select_one(".recipe-overview__categories").get_text(" ", strip=True) == "Dinner"
    assert [span.get_text() for span in overview.select_one(".recipe-overview__tags").find_all("span")] == [
        "<script>alert(1)</script>",
        "Quick",
    ]

    contributor = soup.select_one(".recipe-contributor")
    assert contributor is not None
    assert "by Avery" in contributor.get_text(" ", strip=True)
    created = contributor.select_one("time")
    assert created["datetime"] == "2024-06-15T12:30:00+00:00"
    assert created["data-local-time"] == "true"
    assert "Jun 15" in created.get_text()

    sources = soup.select(".recipe-sources__item")
    assert len(sources) == 2
    website_link = sources[0].select_one("a[href='https://example.com/recipe']")
    assert website_link is not None
    assert website_link["target"] == "_blank"
    assert website_link["rel"] == ["noopener", "noreferrer"]
    assert website_link.get_text(strip=True) == "Family Baking"
    assert "The Baking Book" in sources[1].get_text()
    assert "Avery" in sources[1].get_text()

    version = soup.select_one(".recipe-version")
    assert version is not None
    assert f"v{VERSION}" in version.get_text()
    edited = version.select_one("time")
    assert edited["datetime"] == "2024-07-20T12:30:00+00:00"
    assert edited["data-local-time"] == "true"
    assert edited["data-time-prefix"] == "Edited "
    assert "Edited Jul 20" in version.get_text(" ", strip=True)

    stylesheets = [link["href"] for link in soup.select('link[rel="stylesheet"]')]
    assert stylesheets[0] == "/assets/definitions.css"
    assert "/assets/style.css" in stylesheets
    assert soup.select_one('script[src="/assets/time.js"]') is not None

    assert soup.select_one("#recipe-ratings .recipe-ratings__add") is not None
    assert soup.select_one("#recipe-comments .recipe-comments__add") is not None
    assert soup.select_one("#recipe-comment-form[hidden]") is not None
    assert soup.select_one('script[src="/assets/recipe-scaler.js"]') is not None
    assert soup.select_one('script[src="/assets/comments.js"]') is not None
    assert soup.select_one('script[src="/assets/ratings.js"]') is not None

    quantities = soup.select("span.quantity")
    assert [
        (
            quantity["data-quantity"],
            quantity["data-unit"],
            quantity.get("data-quantity-end"),
            quantity.get_text(),
        )
        for quantity in quantities
    ] == [
        ("1.5", "tbsp", None, ""),
        ("1.0", "tbsp", "2.0", ""),
        ("2.0", "eggs", None, ""),
    ]

    checkbox = soup.select_one('input[type="checkbox"]')
    assert checkbox is not None
    assert not checkbox.has_attr("disabled")


def test_conversion_serializes_unquoted_yaml_dates(tmp_path: Path):
    _, html_file = convert_recipe(
        tmp_path,
        """---
meals:
  - Dinner
contributor: Avery
createdOn: 2024-06-15
updatedOn: 2024-07-20
---
# Dated Recipe
""",
    )

    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    metadata = json.loads(soup.select_one("script#recipe-metadata").string)
    assert metadata["createdOn"] == "2024-06-15"
    assert metadata["updatedOn"] == "2024-07-20"

    contributor = soup.select_one(".recipe-contributor")
    assert contributor is not None
    created = contributor.select_one("time")
    assert created["datetime"] == "2024-06-15"
    assert not created.has_attr("data-local-time")

    version = soup.select_one(".recipe-version")
    assert version is not None
    edited = version.select_one("time")
    assert edited["datetime"] == "2024-07-20"
    assert not edited.has_attr("data-local-time")


def test_conversion_normalizes_timestamps_to_utc_for_browser_localization(tmp_path: Path):
    _, html_file = convert_recipe(
        tmp_path,
        """---
meals:
  - Dinner
contributor: Avery
createdOn: "2024-06-15T02:30:00+05:30"
updatedOn: "2024-07-19T23:30:00-07:00"
---
# Zoned Recipe
""",
    )

    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    created = soup.select_one(".recipe-contributor time")
    assert created["datetime"] == "2024-06-14T21:00:00+00:00"
    assert created["data-local-time"] == "true"

    edited = soup.select_one(".recipe-version time")
    assert edited["datetime"] == "2024-07-20T06:30:00+00:00"
    assert edited["data-local-time"] == "true"
    assert edited["data-time-prefix"] == "Edited "


def test_conversion_falls_back_when_hero_image_cannot_be_opened(tmp_path: Path):
    _, html_file = convert_recipe(
        tmp_path,
        """---
meals:
  - Dinner
---
# Vector Recipe

![Hero](image.svg)
""",
        {"image.svg": b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'},
    )

    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    assert soup.title.string == "Vector Recipe"
    assert soup.select_one(".quantity") is None


def test_conversion_tolerates_malformed_metadata(tmp_path: Path):
    _, html_file = convert_recipe(
        tmp_path,
        """---
ratings:
  - name: Missing score
  - rating: not a number
makes: []
difficulty: {}
source: not a source
contributor:
  - Avery
  - 3
createdOn: not-a-date
updatedOn: not-a-date
---
# Recovered Recipe
""",
    )

    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    assert soup.title.string == "Recovered Recipe"
    assert soup.select_one(".recipe-overview__rating") is None
    assert soup.select_one(".recipe-sources") is None
    assert soup.select_one(".recipe-contributor").get_text(" ", strip=True) == "by Avery, 3"
    assert soup.select_one(".recipe-version time") is None


def test_front_matter_comment_is_not_used_as_page_title(tmp_path: Path):
    _, html_file = convert_recipe(
        tmp_path,
        """---
# This is a YAML comment, not the recipe heading.
meals:
  - Dinner
---
# Real Title ###

Body.
""",
    )

    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    assert soup.title.string == "Real Title"
    assert soup.select_one("main.recipe h1").get_text(strip=True) == "Real Title"


def test_title_extraction_ignores_fenced_code_blocks():
    title = MarkdownToHTMLConverter._get_title_from_markdown_content(
        ["```markdown", "# Not the title", "```", "", "# Actual Title ###"]
    )

    assert title == "Actual Title"


def test_page_title_escapes_html_from_the_heading(tmp_path: Path):
    converter, html_file = convert_recipe(
        tmp_path,
        """---
meals:
  - Dinner
---
# Tomatoes & <em>Basil</em>
""",
    )

    raw_html = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw_html, "html.parser")
    assert soup.title.string == "Tomatoes & <em>Basil</em>"
    assert "<title>Tomatoes &amp; &lt;em&gt;Basil&lt;/em&gt;</title>" in raw_html
    assert converter.title == "Tomatoes & Basil"


def test_recipe_scaler_is_centered_sized_dynamically_and_revealed_when_ready():
    assets = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"

    markup = BeautifulSoup(
        (assets / "recipe-scaler.html").read_text(encoding="utf-8"),
        "html.parser",
    )
    scaler = markup.select_one(".recipe-scaler")
    assert scaler is not None
    assert "recipe-scaler--loading" in scaler["class"]
    assert scaler.select_one("input#recipe-scale-custom").has_attr("hidden")

    css = (assets / "recipe-scaler.css").read_text(encoding="utf-8")
    assert ".recipe-scaler--loading" in css
    assert ".recipe-scaler--ready" in css
    assert "var(--scale-control-width" in css

    script = (assets / "recipe-scaler.js").read_text(encoding="utf-8")
    assert "selectedScaleText" in script
    assert "syncControlWidth" in script
    assert "markReady" in script
    assert "recipe-scaler--ready" in script

    style = (assets / "style.css").read_text(encoding="utf-8")
    assert "scrollbar-gutter: stable" in style
    assert "grid-template-columns: 1fr auto 1fr" in style
    assert ".recipe-header > .recipe-scaler" in style
