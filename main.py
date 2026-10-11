import recipeserver as rs
from pathlib import Path

CATEGORIES = (
    "breakfast",
    "lunch",
    "dinner",
    "dessert",
    "ingredient",
)

working_dir = Path.cwd()
recipe_files: list[Path] = []
for directory in working_dir.iterdir():
    if directory.name in CATEGORIES:
        for recipe_dir in directory.iterdir():
            if recipe_dir.is_dir() and (recipe_dir / "recipe.md").is_file():
                markdown = recipe_dir / "recipe.md"
                html = markdown.with_suffix(".html")
                recipe_files.append(html)
                rs.MarkdownToHTMLConverter().convert(markdown, html)
                rs.HTMLEmbedder(html).process()

rs.IndexHTMLGenerator().convert(recipe_files)
