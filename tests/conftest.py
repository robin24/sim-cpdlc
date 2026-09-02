"""Shared fixtures for the sim-cpdlc test suite."""

import logging

import pytest
import wx
from hoppie_connector import CpdlcMessage, CpdlcResponseRequirement as RR

CLIENT_CALLSIGN = "DLH123"


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


def uplink(sender, min_value, text="CLIMB TO AND MAINTAIN FL360", rr=RR.WILCO_UNABLE):
    """Build an uplink CpdlcMessage as it would arrive from a station."""
    return CpdlcMessage(sender, CLIENT_CALLSIGN, min_value, rr, text)


class FakeConnectionManager:
    """Stands in for ConnectionManager, recording frames instead of transmitting.

    ConnectionManager is the network boundary and is injected into CpdlcSession,
    so this is the intended seam rather than a mock of code under test.
    """

    def __init__(self, connected=True):
        self._connected = connected
        self.sent = []
        self.info_requests = []

    def is_connected(self):
        return self._connected

    def send_cpdlc(self, recipient, min_value, response_type, message, mrn=None):
        self.sent.append((recipient, min_value, response_type, message, mrn))

    def send_info_request(self, info_type, icao):
        self.info_requests.append((info_type, icao))
        return f"{icao} REPORT FOR {info_type}"


class RecordingMessageView:
    """Captures the message IDs the window pushes into the list view."""

    def __init__(self):
        self.added = []

    def add_message(self, message_id):
        self.added.append(message_id)


class FakePollingController:
    """Records polling-rate changes without owning a wx.Timer."""

    def __init__(self):
        self.active_calls = 0

    def set_active_polling(self):
        self.active_calls += 1


def make_main_window(logger, cpdlc_session, message_manager):
    """Build a MainWindow whose wx.Frame half is never initialised.

    MainWindow.__init__ opens dialogs, loads sounds and starts an update check,
    none of which a unit test should trigger. Allocating the instance and wiring
    only the collaborators the message path touches lets the real
    _on_message_received / _on_acknowledge_message code run unmodified.
    """
    from src.gui.main_window import MainWindow

    window = MainWindow.__new__(MainWindow)
    window.logger = logger
    window.cpdlc_session = cpdlc_session
    window.message_manager = message_manager
    window.message_view = RecordingMessageView()
    window.polling_controller = FakePollingController()
    window.new_message_sound = None
    window.status_texts = []
    # Instance attribute shadows wx.Frame.SetStatusText, which would need a
    # live C++ frame behind it.
    window.SetStatusText = window.status_texts.append
    return window
