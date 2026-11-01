from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.markdown_to_html import MarkdownToHTMLConverter


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
    assert 'class="recipe-icon"' in page and "currentColor" in page
    assert 'aria-label="Rated 8.5 out of 10 from 2 ratings"' in page
    assert "8.5/10" in page
    assert 'aria-label="Makes: x12"' in page
    assert 'aria-label="Difficulty: 4/10"' in page
    assert "recipe-detail__label" not in page
    assert "Breakfast" in page
    assert "recipe-chip\">Breakfast</span>" in page
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
    assert '<script src="/assets/index.js" defer></script>' in page
    index_script = (
        Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "index.js"
    ).read_text(encoding="UTF-8")
    assert 'list.classList.toggle("card-view", view === "cards")' in index_script
    assert 'filters.forEach(([, control]) => (control.value = ""))' in index_script
    assert 'id="clear-filters" type="button" hidden' in page
    assert 'data-title="Cinnamon &quot;Rolls&quot;"' in page
    assert 'data-date="2024-06-15"' in page


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
