import logging


_SENSITIVE_LOGGERS = ("httpx", "httpcore", "hpack", "aiormq", "aio_pika")


def configure_logging(debug: bool = False) -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("qhub_api").setLevel(logging.DEBUG if debug else logging.INFO)
    for name in _SENSITIVE_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
