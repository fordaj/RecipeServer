from .core import *

setup_logger()


def main():
    cfg = Configuration()
    cfg.handle_configuration()

    working_dir = cfg.working_directory
    recipe_files: list[Path] = []
    ihg = IndexHTMLGenerator(cfg)
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
                    md2html = MarkdownToHTMLConverter(cfg)
                    md2html.convert(markdown, html)
                    HTMLEmbedder(html).process()
                    # TODO: Recipe is scoped poorly, IndexHTMLGenerator should be the module with Recipe and Generator inside
                    ihg.add(Recipe(md2html.metadata, html))

    ihg.convert()
    Server(cfg).run()  # TODO: Put this on another thread and monitor recipes for changes


if __name__ == "__main__":
    main()
