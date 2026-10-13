from .core import setup_logger, main, Configuration

if __name__ == "__main__":
    setup_logger()
    cfg = Configuration()
    cfg.handle_configuration()
    main(cfg)
