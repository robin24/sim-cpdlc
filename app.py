#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai and Hoppie's ACARS

This is the main entry point for the application.
"""

import sys

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir
from src.error_reporting import ExceptionReporter
from src.model.connection_manager import install_request_timeout


class SimCpdlcApp(wx.App):
    """wx.App that reports exceptions escaping an event handler."""

    def __init__(self, logger):
        self.logger = logger
        super().__init__(False)

    def OnExceptionInMainLoop(self):
        """Log and show any exception raised inside a wx event handler."""
        sys.excepthook(*sys.exc_info())
        return True


def main():
    """Main entry point for the application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Application starting")

    # Log user data directory location
    user_data_dir = get_user_data_dir()
    logger.info(f"Using user data directory: {user_data_dir}")

    ExceptionReporter(logger).install()

    # hoppie_connector passes no timeout to requests, so a server that accepts
    # the connection and then goes silent would otherwise block the GUI thread
    # forever. This gives those calls a default timeout.
    install_request_timeout()

    # Create and start the application
    app = SimCpdlcApp(logger)
    frame = MainWindow(None, "Sim-CPDLC", logger)

    try:
        logger.debug("Entering main application loop")
        app.MainLoop()
    except KeyboardInterrupt:
        logger.info("Application terminated by keyboard interrupt")
        frame.on_exit(None)
    finally:
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
