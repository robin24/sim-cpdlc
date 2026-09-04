#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai and Hoppie's ACARS

This is the main entry point for the application.
"""

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir
from src.error_reporting import ExceptionReporter
from src.model.connection_manager import install_request_timeout


def main():
    """Main entry point for the application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Application starting")

    # Log user data directory location
    user_data_dir = get_user_data_dir()
    logger.info(f"Using user data directory: {user_data_dir}")

    # Exceptions escaping a wx handler already reach sys.excepthook; the
    # reporter logs them and shows one dialog at a time.
    ExceptionReporter(logger).install()

    # hoppie_connector passes no timeout to requests, so a server that accepts
    # the connection and then goes silent would otherwise block the worker
    # thread forever. This gives those calls a default timeout.
    install_request_timeout()

    # Create and start the application
    app = wx.App(False)
    MainWindow(None, "Sim-CPDLC", logger)

    try:
        logger.debug("Entering main application loop")
        app.MainLoop()
    finally:
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
