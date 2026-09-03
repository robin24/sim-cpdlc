"""Shared fixtures for the sim-cpdlc test suite.

Helpers and test doubles live in tests/support.py; this file holds fixtures
only. The autouse fixtures make the suite hermetic: whatever a test builds, it
cannot read or write the real configuration file, reach the network, call
SimBrief or block on a message box.
"""

import logging
import webbrowser

import pytest
import requests
import wx

from tests.support import MessageBoxes
from src import config as config_module


@pytest.fixture
def logger():
    """A real logger that discards output, so log calls are exercised but silent."""
    log = logging.getLogger("sim-cpdlc-tests")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Point the configuration file at a per-test temporary path.

    load_config(), save_config() and MainWindow._check_first_launch() all read
    src.config.CONFIG_FILE at call time, so one patch covers every path that
    could otherwise touch the developer's real config.json.

    Returns:
        str: Path of the isolated config file, which may not exist yet.
    """
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", str(path))
    return str(path)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Refuse every outbound request a test did not explicitly fake.

    Tests that need HTTP install their own fake over these (see serving() in
    test_connection_manager.py); a test's own monkeypatch runs after this one.
    """

    def refuse(*args, **kwargs):
        raise RuntimeError("network access in a test")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(webbrowser, "open", refuse)


@pytest.fixture(autouse=True)
def no_simbrief(monkeypatch):
    """Answer every SimBrief lookup with "no flight plan", recording the ids asked for.

    The Connect and PDC dialogs import get_latest_ofp by name, so the patch
    lands on each dialog module rather than on src.utils.simbrief.

    Returns:
        list: The SimBrief user ids the dialogs asked for.
    """
    asked = []

    def fake(user_id):
        asked.append(user_id)
        return None

    monkeypatch.setattr("src.gui.dialogs.connect_dialog.get_latest_ofp", fake)
    monkeypatch.setattr("src.gui.dialogs.pdc_dialog.get_latest_ofp", fake)
    return asked


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch):
    """Replace wx.MessageBox with a recorder so no test can block on a modal.

    Every module calls it as wx.MessageBox, so patching the wx module attribute
    covers them all. Set .answer to wx.NO to take the cancel branch of a
    confirmation.
    """
    recorder = MessageBoxes()
    monkeypatch.setattr(wx, "MessageBox", recorder)
    return recorder


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
    leaked = [type(window).__name__ for window in wx.GetTopLevelWindows()]
    app.Destroy()
    assert leaked == [], f"top-level windows leaked by this test: {leaked}"


@pytest.fixture
def frame(wx_app):
    """A top-level window to parent dialogs and timers onto."""
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()
