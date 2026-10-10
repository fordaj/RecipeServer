from pathlib import Path
from base64 import b64encode
from mimetypes import guess_type
from bs4 import BeautifulSoup


class HTMLEmbedder:

    def __init__(self, html_file: Path):
        self.html_file = html_file
        self.base_path = html_file.parent

    def process(self) -> None:
        html = self.html_file.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        self.embed_images(soup)
        # self.embed_stylesheets(soup)

        self.html_file.write_text(str(soup), encoding="utf-8")

    def embed_images(self, soup: BeautifulSoup) -> None:
        for image in soup.find_all("img", src=True):
            src = image["src"]

            if src.startswith("data:"):
                continue

            path = (self.base_path / src).resolve()

            mime_type, _ = guess_type(path)

            if not path.is_file():
                raise FileNotFoundError(path)

            if mime_type is None:
                raise ValueError(f"Unknown MIME type: {path}")

            encoded = b64encode(path.read_bytes()).decode("ascii")
            image["src"] = f"data:{mime_type};base64,{encoded}"

    # def embed_stylesheets(self, soup: BeautifulSoup) -> None:
    #     for link in soup.find_all("link", rel="stylesheet", href=True):
    #         ...
