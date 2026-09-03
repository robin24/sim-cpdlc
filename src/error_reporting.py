"""Last-resort reporting of unhandled exceptions to the log and to the user.

wxPython discards exceptions raised inside event handlers, and the packaged
build runs with console=False so stderr goes nowhere. Without a last-resort
handler a failing handler looks exactly like a button that does nothing.

The dialog is always deferred to the next pass of the event loop and never
stacked: a fault that repeats on every poll tick would otherwise open a new
modal dialog inside the previous one.
"""

import sys
import threading
import traceback

import wx


class ExceptionReporter:
    """Routes otherwise-unhandled exceptions to the log and to one dialog."""

    def __init__(self, logger):
        """Initialize the reporter.

        Args:
            logger: Application logger
        """
        self.logger = logger
        self._dialog_open = False

    def install(self):
        """Become the process-wide handler for main-thread and thread exceptions."""
        sys.excepthook = self.handle_uncaught
        threading.excepthook = self.handle_thread

    def report(self, exc_type, exc_value, exc_tb, source):
        """Log an exception with its traceback and queue the dialog.

        Args:
            exc_type: Exception class
            exc_value: Exception instance
            exc_tb: Traceback, or None
            source: Where it came from, for the log line
        """
        self.logger.error(
            f"Unhandled exception in {source}: {exc_type.__name__}: {exc_value}\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        text = (
            f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
            "The details have been written to the log file."
        )
        if wx.GetApp() is None:
            # A background thread outliving the application, or a failure
            # before the application exists: there is nothing to show it on.
            self.logger.error("No application running; the error dialog was not shown")
            return
        # Deferred even on the GUI thread, so the failing handler unwinds
        # before a modal loop starts.
        wx.CallAfter(self._show_dialog, text)

    def _show_dialog(self, text):
        """Show the dialog unless one is already open. Runs on the GUI thread."""
        if self._dialog_open:
            self.logger.warning("Error dialog already open; a further error was logged only")
            return
        self._dialog_open = True
        try:
            wx.MessageBox(text, "Unexpected Error", wx.OK | wx.ICON_ERROR)
        except Exception:
            # Never let the reporter itself take the application down.
            self.logger.exception("Failed to display the unhandled-exception dialog")
        finally:
            self._dialog_open = False

    def handle_uncaught(self, exc_type, exc_value, exc_tb):
        """sys.excepthook replacement."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        self.report(exc_type, exc_value, exc_tb, "main thread")

    def handle_thread(self, args):
        """threading.excepthook replacement."""
        self.report(args.exc_type, args.exc_value, args.exc_traceback, "background thread")
