from pathlib import Path
from .pallette import Pallette
from textwrap import dedent
from dataclasses import dataclass
from slugify import slugify

FILE_PATH = Path(__file__)
INDEX_CSS_PATH = FILE_PATH.parent / "assets" / "index.css"


class Recipe:
    def __init__(self, metadata: str, html_file: Path):
        self.metadata: str = metadata
        self.html_file: Path = html_file


class IndexHTMLGenerator:
    def __init__(self):
        self.recipes: list[Recipe] = []

    def add(self, recipe: Recipe):
        self.recipes.append(recipe)

    @staticmethod
    def deslugify(slug: str) -> str:
        return slug.replace("-", " ").title()

    def convert(self):
        links: list[str] = []

        for i, recipe in enumerate(self.recipes):

            file = recipe.html_file.relative_to(Path.cwd())
            link = f'<li><a href="{file}">{self.deslugify(str(file.parent.name))}</a></li>'
            links.append(link)

        html = dedent(f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Recipe Server</title>
            <style>
            {INDEX_CSS_PATH.read_text(encoding="UTF-8", newline="\n")}
            </style>
        </head>
        <body>
            <main class="recipes">
            <ul>
                {"\n".join(links)}
            </ul>
            </main>
        </body>
        </html>
        """)

        Path("./index.html").write_text(html, encoding="UTF-8", newline="\n")
