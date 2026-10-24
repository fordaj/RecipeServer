from .core import setup_logger, run, Configuration

if __name__ == "__main__":
    setup_logger()
    cfg = Configuration()
    cfg.handle_configuration()
    run(cfg)
