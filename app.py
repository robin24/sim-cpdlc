#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai

This is the main entry point for the application.
"""

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir


def main():
    """Main entry point for the application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Application starting")

    # Log user data directory location
    user_data_dir = get_user_data_dir()
    logger.info(f"Using user data directory: {user_data_dir}")

    # Create and start the application
    app = wx.App(False)
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
