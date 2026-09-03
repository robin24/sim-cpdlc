"""Shared fixtures for the sim-cpdlc test suite.

Helpers and test doubles live in tests/support.py; this file holds fixtures
only.
"""

import logging

import pytest
import wx


@pytest.fixture
def logger():
    """A real logger that discards output, so log calls are exercised but silent."""
    log = logging.getLogger("sim-cpdlc-tests")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


@pytest.fixture
def wx_app():
    """A wx application context.

    Torn down rather than shared, because wx allows only one live App at a
    time and a leaked one would break whichever test ran next.
    """
    app = wx.App()
    yield app
    # Destroy() only queues a window for deletion; without a yield the whole
    # object graph behind it -- and for a MainWindow that means a weather
    # monitor, a SimConnect manager and an update checker -- stays alive for
    # the rest of the session.
    wx.SafeYield()
    app.Destroy()


@pytest.fixture
def frame(wx_app):
    """A top-level window to parent dialogs and timers onto."""
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()
