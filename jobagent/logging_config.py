"""Structured logging for JobAgent."""

import logging

import rich.logging


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Configure application-wide logging with rich formatting."""
    handlers: list[logging.Handler] = [
        rich.logging.RichHandler(
            rich_tracebacks=True,
            show_path=False,
            markup=True,
        )
    ]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )

    # Quieten noisy third-party libraries
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
