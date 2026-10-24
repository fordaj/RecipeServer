from recipeserver.core import setup_logger, run, Configuration
from pathlib import Path

FILE_PATH = Path(__file__)
CONFIG_TXT_PATH = FILE_PATH.parent / "config.txt"


def test_recipeserver():
    setup_logger()
    cfg = Configuration()
    cfg.handle_configuration(CONFIG_TXT_PATH)
    run(cfg)


if __name__ == "__main__":
    test_recipeserver()
