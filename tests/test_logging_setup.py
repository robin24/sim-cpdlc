"""Where log records go: the file always, the console only when there is one."""

import logging
import sys

import pytest

import src.logging_setup as logging_setup
from src.utils import simbrief


@pytest.fixture
def app_logger(monkeypatch, tmp_path):
    """setup_logging() on a fresh logger writing under tmp_path, torn down after."""
    monkeypatch.setattr(logging_setup, "get_user_data_dir", lambda: str(tmp_path))
    logger = logging.getLogger("Sim-CPDLC")
    saved = list(logger.handlers)
    saved_level = logger.level
    logger.handlers = []
    try:
        yield logger
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = saved
        logger.setLevel(saved_level)


def test_the_windowed_build_gets_no_console_handler(app_logger, monkeypatch):
    """PyInstaller's console=False leaves sys.stderr as None, and a
    StreamHandler wrapped around None raises on the first record."""
    monkeypatch.setattr(sys, "stderr", None)

    logger = logging_setup.setup_logging()

    assert [type(h).__name__ for h in logger.handlers] == ["RotatingFileHandler"]


def test_a_console_gets_a_console_handler(app_logger):
    logger = logging_setup.setup_logging()

    assert [type(h).__name__ for h in logger.handlers] == ["StreamHandler", "RotatingFileHandler"]


def test_simbrief_logs_under_the_application_logger():
    """Its failure reasons went to an orphan logger with no handlers, so the
    log file only ever said "Failed to fetch SimBrief OFP data" (audit L-6)."""
    assert simbrief.logger.name == "Sim-CPDLC.simbrief"
    assert simbrief.logger.parent is logging.getLogger("Sim-CPDLC")
