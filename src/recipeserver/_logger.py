# python_common/logger.py

from loguru import logger
import socket, sys, os, atexit

hostname = socket.gethostname()
file_sink_id = None
_is_configured = False

# | Level      | Numeric value |
# | ---------- | ------------: |
# | `TRACE`    |           `5` |
# | `DEBUG`    |          `10` |
# | `INFO`     |          `20` |
# | `SUCCESS`  |          `25` |
# | `WARNING`  |          `30` |
# | `ERROR`    |          `40` |
# | `CRITICAL` |          `50` |

logger.level("COMMAND", no=6, color="<dim><magenta>")
logger.command = lambda msg, *args, **kwargs: logger.opt(depth=1).log(
    "COMMAND", msg, *args, **kwargs
)

logger.level("FILE", no=7, color="<dim><fg 208>")
logger.file = lambda msg, *args, **kwargs: logger.opt(depth=1).log(
    "FILE", msg, *args, **kwargs
)

logger.level("TRACE", color="<cyan>")


def setup_logger(log_level="INFO"):
    global file_sink_id, _is_configured

    if _is_configured:
        return

    logger.remove()

    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        f"<magenta>{hostname}</magenta> "
        "<blue>{file}:{line} [{thread.name}]</blue> "
        "<bold><black>[{level}]</black></> "
        "<level>{message}</level>",
        level=log_level.upper(),
        colorize=True,
        enqueue=True,
    )

    caller_filename = os.path.basename(sys.argv[0])
    os.makedirs(".logs", exist_ok=True)
    log_file = os.path.join(
        ".logs",
        f"{os.path.splitext(caller_filename)[0]}.py.log",
    )

    file_sink_id = logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} "
        f"{hostname} "
        "{file}:{line} "
        "[{level}] {message}",
        level="TRACE",
        colorize=False,
        enqueue=True,
    )

    # def zip_logs():
    #     logger.complete()
    #     logger.remove()
    #     from python_common.log_zipper import LogZipper
    #     LogZipper().run()

    # atexit.register(zip_logs)

    logger.trace("Logger setup complete")
    _is_configured = True


__all__ = ["logger", "setup_logger"]
