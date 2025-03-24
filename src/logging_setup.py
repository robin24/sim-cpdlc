"""Logging configuration for the Sim-CPDLC application."""

import logging
from logging.handlers import RotatingFileHandler


def setup_logging():
    """Configure application logging with console and rotating file handlers."""
    # Create logger
    logger = logging.getLogger("Sim-CPDLC")
    logger.setLevel(logging.DEBUG)  # Set to DEBUG for early testing

    # Prevent duplicate handlers if logger already exists
    if logger.handlers:
        return logger

    # Configure log format
    log_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    # File handler with rotation (10MB max size, keep 5 backup files)
    try:
        file_handler = RotatingFileHandler(
            "sim-cpdlc.log", maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except (IOError, PermissionError) as e:
        # Log to console if file handler creation fails
        logger.error(f"Failed to create log file: {e}")
        logger.warning("Continuing with console logging only")

    return logger
