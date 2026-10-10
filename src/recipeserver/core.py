from pathlib import Path
from .markdown_to_html import MarkdownToHTMLConverter
from .html_embedder import HTMLEmbedder
from .index_html_generator import IndexHTMLGenerator


def main():
    markdown = Path("./Chocolate Chip Cookies/recipe.md")
    html = markdown.with_suffix(".html")
    MarkdownToHTMLConverter().convert(markdown, html)
