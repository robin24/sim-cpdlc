#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai

This is the main entry point for the application.
"""

import sys
import threading
import traceback

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir
from src.model.connection_manager import install_request_timeout


def _install_exception_handlers(logger):
    """Route otherwise-unhandled exceptions to the log and to the user.

    wxPython discards exceptions raised inside event handlers, and the packaged
    build runs with console=False so stderr goes nowhere. Without a last-resort
    handler a failing handler looks exactly like a button that does nothing.

    Args:
        logger: Application logger
    """

    def show_dialog(text):
        try:
            wx.MessageBox(text, "Unexpected Error", wx.OK | wx.ICON_ERROR)
        except Exception:
            # Never let the reporter itself take the application down.
            logger.exception("Failed to display the unhandled-exception dialog")

    def report(exc_type, exc_value, exc_tb, source):
        logger.error(
            f"Unhandled exception in {source}: {exc_type.__name__}: {exc_value}\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        text = (
            f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
            "The details have been written to the log file."
        )
        if wx.IsMainThread():
            show_dialog(text)
        else:
            # wx widgets may only be touched from the GUI thread.
            wx.CallAfter(show_dialog, text)

    def handle_uncaught(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        report(exc_type, exc_value, exc_tb, "main thread")

    def handle_thread(args):
        report(args.exc_type, args.exc_value, args.exc_traceback, "background thread")

    sys.excepthook = handle_uncaught
    threading.excepthook = handle_thread


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

    _install_exception_handlers(logger)

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
