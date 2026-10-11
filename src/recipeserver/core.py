from pathlib import Path
from .markdown_to_html import MarkdownToHTMLConverter
from .html_embedder import HTMLEmbedder
from .index_html_generator import IndexHTMLGenerator, Recipe
from ._logger import logger, setup_logger

setup_logger()


def main():

    markdown = Path("./Chocolate Chip Cookies/recipe.md")
    html = markdown.with_suffix(".html")
    MarkdownToHTMLConverter(logger).convert(markdown, html)
