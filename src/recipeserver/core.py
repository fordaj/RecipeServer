from pathlib import Path
from .markdown_to_html import MarkdownToHTMLConverter
from .html_embedder import HTMLEmbedder
from .index_html_generator import IndexHTMLGenerator, Recipe
from ._logger import logger, setup_logger
from .config import Configuration
from .server import Server


def main(cfg: Configuration):
    working_dir = cfg.working_directory
    recipe_files: list[Path] = []
    ihg = IndexHTMLGenerator(cfg)
    for markdown in working_dir.rglob("recipe.md"):
        if markdown.is_file():
            # recipe_dir = markdown.parent
            html = markdown.with_suffix(".html")
            recipe_files.append(html)
            md2html = MarkdownToHTMLConverter(cfg)
            md2html.convert(markdown, html)
            HTMLEmbedder(html).process()
            # TODO: Recipe is scoped poorly, IndexHTMLGenerator should be the module with Recipe and Generator inside
            ihg.add(Recipe(md2html.metadata, html))

    ihg.convert()
    Server(cfg).run()  # TODO: Put this on another thread and monitor recipes for changes
