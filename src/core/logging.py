import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)

    try:
        # python-json-logger >= 3.x uses a different import path
        from pythonjsonlogger.json import JsonFormatter
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    except ImportError:
        try:
            # python-json-logger 2.x
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
            )
        except ImportError:
            # Fallback to standard formatting if python-json-logger is not installed
            formatter = logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
            )

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
