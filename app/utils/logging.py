"""Logging setup shared by application entry points."""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("twitchio").setLevel(logging.CRITICAL + 1)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)