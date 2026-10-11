import recipeserver as rs
from pathlib import Path

# CATEGORIES = (
#     "breakfast",
#     "lunch",
#     "dinner",
#     "dessert",
#     "ingredient",
# )

working_dir = Path.cwd()
recipe_files: list[Path] = []
ihg = rs.IndexHTMLGenerator()
for directory in working_dir.iterdir():
    # if directory.name in CATEGORIES:
    if directory.is_dir():
        for recipe_dir in directory.iterdir():
            if (
                recipe_dir.is_dir() and (recipe_dir / "recipe.md").is_file()
            ):  # TODO: Support more than depth==2 (all depths)
                markdown = recipe_dir / "recipe.md"
                html = markdown.with_suffix(".html")
                recipe_files.append(html)
                md2html = rs.MarkdownToHTMLConverter()
                md2html.convert(markdown, html)
                rs.HTMLEmbedder(html).process()
                ihg.add(
                    rs.Recipe(md2html.metadata, html)
                )  # TODO: Recipe is scoped poorly, IndexHTMLGenerator should be the module with Recipe and Generator inside

ihg.convert()
