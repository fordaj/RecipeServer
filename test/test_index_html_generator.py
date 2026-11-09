from pathlib import Path
from types import SimpleNamespace
import json

from bs4 import BeautifulSoup

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.metadata_linter import lint_recipe_metadata
from recipeserver.markdown_to_html import MarkdownToHTMLConverter


def test_lint_recipe_metadata_reports_missing_required_values():
    warnings = lint_recipe_metadata(
        {
            "contributor": " ",
            "meals": [],
            "categories": ["Dinner"],
            "makes": None,
            "difficulty": 4,
            "cuisine": [],
            "tags": [],
            "source": [],
            "ratings": [],
            "comments": [],
            "createdOn": "",
        }
    )

    assert warnings == [
        {
            "field": "ratings",
            "label": "Ratings",
            "severity": "warning",
            "message": "Missing ratings",
        },
        {
            "field": "contributor",
            "label": "Contributor",
            "severity": "warning",
            "message": "Missing contributor",
        },
        {
            "field": "createdOn",
            "label": "Contribution date",
            "severity": "warning",
            "message": "Missing contribution date",
        },
        {
            "field": "meals",
            "label": "Meals",
            "severity": "warning",
            "message": "Missing meals",
        },
        {
            "field": "makes",
            "label": "Makes",
            "severity": "warning",
            "message": "Missing makes",
        },
    ]


def test_lint_recipe_metadata_accepts_legacy_singular_category():
    warnings = lint_recipe_metadata(
        {
            "ratings": [{"rating": 8}],
            "contributor": "Avery",
            "createdOn": "2024-06-15T12:30:00Z",
            "meals": ["Dinner"],
            "category": ["Baking"],
            "makes": 12,
            "difficulty": 4,
        }
    )

    assert warnings == []


def test_index_contains_recipe_details_filters_and_sort_options(tmp_path: Path):
    recipe_path = tmp_path / "cinnamon-rolls" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text(
        '<main><h1>Cinnamon "Rolls"</h1><h1>Other heading</h1></main>',
        encoding="UTF-8",
    )
    (recipe_path.parent / "image.webp").write_bytes(b"recipe image")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(
        Recipe(
            {
                "title": "Metadata title should not override the page heading",
                "ratings": [{"rating": 8}, {"rating": 9}],
                "makes": 12,
                "difficulty": 4,
                "meals": ["Breakfast"],
                "cuisine": ["American"],
                "categories": ["Baking"],
                "tags": ["Cinnamon"],
                "contributor": "Avery",
                "createdOn": "2024-06-15T12:30:00Z",
                "source": [
                    {
                        "format": "website",
                        "title": "Family Baking",
                        "url": "https://example.com/recipe",
                    },
                    {"format": "book", "title": "The Baking Book"},
                ],
            },
            recipe_path,
        )
    )

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    assert 'src="/cinnamon-rolls/image.webp"' in page
    soup = BeautifulSoup(page, "html.parser")
    recipe = soup.select_one("#recipe-list .recipe")
    assert recipe is not None
    recipe_link = recipe.select_one(".recipe-card__link")
    assert recipe_link is not None
    assert recipe_link["href"] == "/cinnamon-rolls/index.html"
    assert recipe.select_one(".recipe-card__image img") is not None
    assert len(recipe_link.find_all("a")) == 0
    assert recipe_link.get_text(strip=True) == 'Cinnamon "Rolls"'
    assert recipe.select_one(".recipe-card__heading .recipe-rating") is None
    assert recipe.select_one(".recipe-card__details .recipe-rating") is not None
    assert recipe.select_one(".recipe-detail--contributor").get_text(strip=True) == "Avery"
    assert recipe.select_one(".recipe-detail--contribution-date").get_text(strip=True) == "2024"
    source_link = recipe.select_one('.recipe-detail--source a[href="https://example.com/recipe"]')
    assert source_link is not None
    assert source_link.get_text(strip=True) == "Family Baking"
    assert "The Baking Book" in recipe.select_one(".recipe-card__details").get_text()
    assert recipe.select_one(".recipe-card__details a a") is None
    assert recipe.select_one(".recipe-warning-chip") is None
    metadata_toggle = soup.select_one("#metadata-status")
    assert metadata_toggle is not None
    assert metadata_toggle.get("checked") is None
    assert "Metadata Status" in soup.select_one(".metadata-status-toggle").get_text()
    assert 'class="recipe-icon"' in page and "currentColor" in page
    assert 'aria-label="Rated 8.5 out of 10 from 2 ratings"' in page
    assert "8.5/10" in page
    assert 'aria-label="Makes: x12"' in page
    assert 'aria-label="Difficulty: 4/10"' in page
    assert "recipe-detail__label" not in page
    assert "Breakfast" in page
    assert 'recipe-chip">Breakfast</span>' in page
    assert "American" in page
    assert "Cinnamon" in page
    assert 'id="filter-cuisine"' in page
    assert 'id="filter-meal"' in page
    assert 'id="filter-tag"' in page
    assert 'id="filter-contributor"' in page
    assert 'id="filter-source-title"' in page
    assert 'value="avery"' in page
    assert 'value="family baking"' in page
    assert 'value="the baking book"' in page
    assert 'value="rating:desc"' in page
    assert 'value="makes:desc"' in page
    assert 'value="difficulty:asc"' in page
    assert 'value="date:desc"' in page
    assert 'value="date:asc"' in page
    assert 'data-view="cards"' in page and 'data-view="list"' in page
    assert 'src="/assets/index.js?v=' in page
    stylesheets = [link["href"] for link in soup.select('link[rel="stylesheet"]')]
    assert stylesheets[0].startswith("/assets/definitions.css?v=")
    assert stylesheets.index(next(url for url in stylesheets if url.startswith("/assets/index.css?v="))) > 0
    assert '<link rel="stylesheet" href="/assets/recipe-editor/recipe-editor.css?v=' in page
    assert '<script src="/assets/recipe-editor/recipe-editor.js?v=' in page
    assert 'id="create-recipe"' in page
    assert 'stroke="currentColor"' in page
    index_script = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js").read_text(encoding="UTF-8")
    assert 'list.classList.toggle("card-view", isCards)' in index_script
    assert "setView(loadRecipeView())" in index_script
    assert 'filterControls.forEach(([, control]) => (control.value = ""))' in index_script
    assert 'id="clear-filters" type="button" hidden' in page
    assert 'data-title="Cinnamon &quot;Rolls&quot;"' in page
    assert 'data-date="2024-06-15"' in page


def test_index_review_filter_is_populated_and_sorted_by_review_count(tmp_path: Path):
    recipe_ratings = {
        "alpha": [{"name": "Avery", "rating": 8}, {"name": "Blair", "rating": 7}],
        "beta": [{"name": "Avery", "rating": 9}, {"name": "Casey", "rating": 6}],
        "gamma": [
            {"name": "Avery", "rating": 10},
            {"name": "Blair", "rating": 8},
            {"name": "Dana", "rating": 5},
        ],
    }
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    for slug, ratings in recipe_ratings.items():
        recipe_path = tmp_path / slug / "index.html"
        recipe_path.parent.mkdir()
        recipe_path.write_text(f"<h1>{slug.title()}</h1>", encoding="UTF-8")
        generator.add(Recipe({"ratings": ratings}, recipe_path))

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")
    review_filter = soup.select_one("#review-filter")
    assert review_filter is not None
    assert "Filter Reviews" in review_filter.select_one("summary").get_text(" ", strip=True)
    assert "Filter Reviews: All" in page
    advanced = soup.select_one(".recipe-advanced__content")
    assert advanced is not None
    assert advanced.select_one("#review-filter") is not None
    assert soup.select_one(".recipe-filters #review-filter") is None

    all_reviews = soup.select_one("#filter-reviews-all")
    assert all_reviews is not None
    assert all_reviews.has_attr("checked")

    options = soup.select("#review-filter .filter-reviews")
    assert [option["value"] for option in options] == ["avery", "blair", "casey", "dana"]
    assert [option.parent.select_one(".review-filter__count").get_text(strip=True) for option in options] == ["3", "2", "1", "1"]
    assert [option.parent.select_one("span").get_text(strip=True) for option in options] == [
        "Avery",
        "Blair",
        "Casey",
        "Dana",
    ]

    alpha = soup.select_one('#recipe-list .recipe[data-title="Alpha"]')
    assert alpha is not None
    assert json.loads(alpha["data-ratings"]) == [
        {"name": "avery", "rating": 8},
        {"name": "blair", "rating": 7},
    ]


def test_index_review_filter_keeps_only_the_top_30_reviewers(tmp_path: Path):
    recipe_path = tmp_path / "many-reviews" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Many Reviews</h1>", encoding="UTF-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(
        Recipe(
            {"ratings": [{"name": f"Reviewer {index:02d}", "rating": 5} for index in range(1, 32)]},
            recipe_path,
        )
    )

    generator.convert()

    soup = BeautifulSoup(
        (tmp_path / "index.html").read_text(encoding="UTF-8"),
        "html.parser",
    )
    options = soup.select("#review-filter .filter-reviews")
    assert len(options) == 30
    assert options[0]["value"] == "reviewer 01"
    assert options[-1]["value"] == "reviewer 30"
    assert all(option["value"] != "reviewer 31" for option in options)


def test_unrated_recipes_remain_sortable(tmp_path: Path):
    recipe_path = tmp_path / "plain-pasta" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Plain Pasta</h1>", encoding="UTF-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"title": "Plain Pasta", "ratings": []}, recipe_path))

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    assert BeautifulSoup(page, "html.parser").select_one(".recipe-rating") is None
    assert 'data-rating=""' in page
    assert 'data-makes=""' in page
    assert 'data-difficulty=""' in page
    recipe = BeautifulSoup(page, "html.parser").select_one("#recipe-list .recipe")
    assert recipe is not None
    warning_details = recipe.select(".recipe-detail--warning")
    assert len(warning_details) == 7
    assert all(detail.has_attr("hidden") for detail in warning_details)
    assert [chip.get_text(" ", strip=True) for chip in recipe.select(".recipe-warning-chip")] == [
        "Ratings",
        "Makes",
        "Difficulty",
        "Meals",
        "Categories",
        "Contributor",
        "Contribution date",
    ]


def test_metadata_warnings_refresh_when_index_is_regenerated(tmp_path: Path):
    recipe_path = tmp_path / "cinnamon-rolls" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Cinnamon Rolls</h1>", encoding="UTF-8")
    metadata = {}
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe(metadata, recipe_path))

    generator.convert()
    first_page = BeautifulSoup(
        (tmp_path / "index.html").read_text(encoding="UTF-8"),
        "html.parser",
    )
    # Should have warnings for the 7 required fields
    assert len(first_page.select(".recipe-warning-chip")) == 7

    # Update metadata to include all required fields with valid values
    metadata.update(
        {
            "ratings": [{"rating": 8, "author": "Avery"}],
            "contributor": "Avery",
            "createdOn": "2024-06-15T12:30:00Z",
            "meals": ["Dessert"],
            "categories": ["Baking"],
            "makes": 12,
            "difficulty": 4,
        }
    )
    generator.convert()

    updated_page = BeautifulSoup(
        (tmp_path / "index.html").read_text(encoding="UTF-8"),
        "html.parser",
    )
    # All warnings should be gone now
    assert updated_page.select_one(".recipe-warning-chip") is None


def test_recipe_overview_shows_cuisine_before_categories_and_tags():
    converter = MarkdownToHTMLConverter(SimpleNamespace())
    overview = converter._build_recipe_overview(
        {
            "cuisine": ["Thai"],
            "categories": ["Soup"],
            "tags": ["Spicy"],
        },
        BeautifulSoup("", "html.parser"),
    )

    assert overview is not None
    secondary = overview.select_one(".recipe-overview__secondary")
    assert secondary is not None
    groups = secondary.find_all("span", recursive=False)
    assert [group["class"][0] for group in groups] == [
        "recipe-overview__cuisine",
        "recipe-overview__categories",
        "recipe-overview__tags",
    ]
    assert "lucide-pin" in str(groups[0])


def test_recipe_overview_accepts_legacy_singular_category():
    converter = MarkdownToHTMLConverter(SimpleNamespace())
    overview = converter._build_recipe_overview(
        {"category": ["Soup"]},
        BeautifulSoup("", "html.parser"),
    )

    assert overview is not None
    categories = overview.select_one(".recipe-overview__categories")
    assert categories is not None
    assert categories.get_text(" ", strip=True) == "Soup"


def test_index_accepts_legacy_singular_category(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"category": ["Baking"]}, recipe_path))

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    recipe = BeautifulSoup(page, "html.parser").select_one("#recipe-list .recipe")
    assert recipe is not None
    assert recipe["data-categories"] == '["Baking"]'
    assert recipe.select_one(".recipe-detail--categories").get_text(" ", strip=True) == "Baking"


def test_index_uses_converter_title_without_reading_the_recipe_page(tmp_path: Path):
    recipe_path = tmp_path / "ghost" / "recipe.html"
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"meals": ["Dinner"]}, recipe_path, "Ghost Recipe"))

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    recipe = BeautifulSoup(page, "html.parser").select_one("#recipe-list .recipe")
    assert recipe is not None
    assert recipe["data-title"] == "Ghost Recipe"
    assert recipe.select_one(".recipe-card__link").get_text(strip=True) == "Ghost Recipe"


def test_average_rating_ignores_booleans_and_invalid_scores():
    average, count = IndexHTMLGenerator._average_rating(
        {
            "ratings": [
                {"rating": 8},
                {"rating": True},
                {"rating": "9"},
                {"rating": 10},
            ]
        }
    )

    assert average == 9
    assert count == 2


def test_recipe_editor_includes_local_model_source_inputs():
    base = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
    script = (base / "recipe-editor.js").read_text(encoding="UTF-8")
    ai = (base / "ai.html").read_text(encoding="UTF-8")
    markup = script + ai

    assert "From text" in markup
    assert "From URL" in markup
    assert "From Image" in markup
    assert "Generate from text" in markup
    assert "Generate from image" in markup
    assert 'class="recipe-editor__section recipe-editor__ai"' in markup
    assert "Cancel generation" in markup
    assert "AbortController" in script
    assert "/api/ai-status" in script
    assert "/api/ai-recipe" in script
    assert "The configured local model is unavailable" in script


def test_recipe_editor_only_shows_ai_section_when_creating():
    base = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
    script = (base / "recipe-editor.js").read_text(encoding="UTF-8")
    ai = (base / "ai.html").read_text(encoding="UTF-8")

    assert 'class="recipe-editor__details recipe-editor__ai-details"' in ai
    assert "aiDetails.hidden = !configured || !isCreating" in script
    assert "aiDetails.open = false" in script
    assert 'createdOn: get("createdOn") || null' in script


def test_recipe_editor_css_keeps_files_and_ai_sections_single_column():
    css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor" / "recipe-editor.css").read_text(encoding="UTF-8")

    assert ".recipe-editor__ai-details[hidden]" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert '.recipe-editor__metadata input[type="date"]' in css
    assert "max-width: 100%" in css
    assert "var(--danger-color)" in css


def test_definitions_css_centralizes_theme_values():
    css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "definitions.css").read_text(encoding="UTF-8")

    for token in (
        "--food-color",
        "--page-bg",
        "--text-color",
        "--border-color",
        "--font-body",
        "--font-heading",
        "--warning-border-color",
        "--danger-color",
        "--print-bg",
    ):
        assert token in css

    for asset in ("style.css", "index.css", "recipe-editor/recipe-editor.css", "comments.css", "ratings.css"):
        component = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / asset).read_text(encoding="UTF-8")
        assert "@font-face" not in component
        assert ":root {" not in component


def test_index_uses_configured_recipe_server_name(tmp_path: Path):
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path, recipe_server_name="Custom <Name>"))
    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")
    assert soup.select_one("header.recipes-header h1").get_text(strip=True) == "Custom <Name>"
    assert soup.title.string == "Custom <Name>"
    assert "Custom &lt;Name&gt;" in page
    assert "<h1>Custom <Name></h1>" not in page


def test_index_defaults_recipe_server_name(tmp_path: Path):
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.convert()

    soup = BeautifulSoup(
        (tmp_path / "index.html").read_text(encoding="UTF-8"),
        "html.parser",
    )
    assert soup.select_one("header.recipes-header h1").get_text(strip=True) == "My Recipe Server"
    assert soup.title.string == "My Recipe Server"


def test_review_filter_shares_filter_control_select_styling():
    css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.css").read_text(encoding="UTF-8")

    assert ".recipe-toolbar .filter-control select,\n.review-filter summary" in css
    assert ".recipe-advanced > summary" in css
    assert ".recipe-advanced summary" not in css
    # The review filter behaves like the other filter controls.
    assert ".review-filter {\n  display: flex;" in css
    assert "transform: translateY(-50%)" in css
    assert ".filter-control svg" in css


def test_index_normalizes_updated_timestamp_to_utc(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "index.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="UTF-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(
        Recipe(
            {
                "meals": ["Dinner"],
                "updatedOn": "2024-07-19T23:30:00-07:00",
            },
            recipe_path,
        )
    )

    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    recipe = BeautifulSoup(page, "html.parser").select_one("#recipe-list .recipe")
    assert recipe is not None
    assert recipe["data-edited"] == "2024-07-20T06:30:00+00:00"


def test_index_includes_card_zoom_slider_control(tmp_path: Path):
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.convert()

    page = (tmp_path / "index.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(page, "html.parser")
    control = soup.select_one("#card-zoom-control")
    assert control is not None
    # Size applies to both List and Cards views, so it is always visible.
    assert not control.has_attr("hidden")
    assert control["title"] == "Smaller shows more"
    label = control.select_one(".card-zoom__label")
    assert label is not None
    assert label.get_text(strip=True) == "Size"
    assert "Card size" not in control.get_text()
    hint = control.select_one("#card-zoom-hint")
    assert hint is not None
    assert hint.get_text(strip=True) == "Smaller shows more"
    assert "visually-hidden" in hint["class"]
    slider = soup.select_one("#card-zoom")
    assert slider is not None
    assert slider["type"] == "range"
    assert slider["min"] == "180"
    assert slider["max"] == "440"
    assert slider["step"] == "20"
    assert slider["value"] == "280"
    assert slider["aria-label"] == "Size"
    assert slider["title"] == "Smaller shows more"
    assert slider["aria-describedby"] == "card-zoom-hint"
    assert soup.select_one(".results-controls .view-switcher") is not None
    assert soup.select_one(".results-controls .card-zoom") is not None

    css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.css").read_text(encoding="UTF-8")
    assert "--card-min-width" in css
    assert "--list-thumb-size" in css
    assert "#recipe-list.card-view" in css
    assert "auto-fill" in css
    assert ".card-zoom {" in css
    # The zoom field is unboxed: no background or outline.
    assert ".card-zoom[hidden]" not in css
    zoom_rule = css.split(".card-zoom {", 1)[1].split("}", 1)[0]
    assert "background" not in zoom_rule
    assert "border" not in zoom_rule
    assert ".card-zoom__hint {" not in css
    assert ".results-controls" in css
    # List view: image size (and therefore row height) follows the slider.
    list_card_rule = css.split("#recipe-list.list-view .recipe-card {", 1)[1].split("}", 1)[0]
    assert "var(--list-thumb-size" in list_card_rule
    list_image_rule = css.split("#recipe-list.list-view .recipe-card__image {", 1)[1].split("}", 1)[0]
    assert "var(--list-thumb-size" in list_image_rule
    # Fixed card column breakpoints are replaced by the zoom-driven grid.
    assert "repeat(2, minmax(0, 1fr));\n  }\n}\n\n@media (min-width: 750px)" not in css.replace("  ", "")
    assert "#recipe-list.card-view {\n    grid-template-columns: repeat(2" not in css
    assert "#recipe-list.card-view {\n    grid-template-columns: repeat(3" not in css
    assert "#recipe-list.card-view {\n    grid-template-columns: repeat(4" not in css

    script = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js").read_text(encoding="UTF-8")
    assert "recipe-card-min-width" in script
    assert "recipe-view" in script
    assert "loadRecipeView" in script
    assert "saveRecipeView" in script
    assert "localStorage" in script
    assert "cardZoomControl" not in script
    assert "cardZoomControl.hidden" not in script


def test_card_zoom_css_remains_responsive(tmp_path: Path):
    css = (Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.css").read_text(encoding="UTF-8")
    # The grid must not overflow narrow viewports at large card widths.
    assert "min(var(--card-min-width, 280px), 100%)" in css
    # List thumbnails scale proportionally: 280px card width -> 4rem thumb.
    assert "calc(var(--card-min-width) * 0.2286)" in css
    # Mobile layout keeps the zoom control usable.
    assert "@media (max-width: 499px)" in css
    assert ".card-zoom__slider" in css
