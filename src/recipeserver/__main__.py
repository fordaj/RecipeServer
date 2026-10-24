from .core import setup_logger, main, Configuration, parse_args

if __name__ == "__main__":
    args = parse_args()
    setup_logger(args.log_level)
    cfg = Configuration()
    cfg.handle_configuration()
    main(cfg)
