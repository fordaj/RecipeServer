from ._logger import setup_logger
from .config import Configuration
from .core import main, parse_args

if __name__ == "__main__":
    args = parse_args()
    setup_logger(args.log_level)
    cfg = Configuration()
    cfg.handle_configuration()
    main(cfg)
