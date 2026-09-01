"""Integration test for the real MainWindow._init_ui wiring.

MainWindow.__init__ opens dialogs, loads a sound and starts an update check.
This subclass runs the genuine _init_ui (and _init_menu) on a real frame with
only the collaborators those methods need, so a mis-wired MessageView is caught
here rather than at application startup.
"""

import pytest
import wx

from conftest import FakeConnectionManager, uplink
from src.gui.main_window import MainWindow
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

STATION = "LSAG"


class HeadlessMainWindow(MainWindow):
    def __init__(self, logger, cpdlc_session, message_manager):
        wx.Frame.__init__(self, None, title="Sim-CPDLC test")
        self.logger = logger
        self.cpdlc_session = cpdlc_session
        self.message_manager = message_manager
        self._init_ui()


@pytest.fixture
def window(logger):
    app = wx.App()
    session = CpdlcSession(logger, FakeConnectionManager())
    frame = HeadlessMainWindow(logger, session, MessageManager(logger))
    yield frame
    frame.Destroy()
    app.Destroy()


def test_init_ui_wires_the_message_view_to_the_live_session(window):
    """The view must read the station from the session, not a stale copy."""
    window.cpdlc_session.handle_logon_accepted(STATION)

    assert window.message_view.get_current_station() == STATION


def test_context_menu_follows_the_session_after_a_handover(window):
    """A message from the station we have left stops offering responses."""
    window.cpdlc_session.handle_logon_accepted("EDYY")
    message_id = window.message_manager.add_message(uplink("EDYY", 4))
    window.message_view.add_message(message_id)
    window.message_view.message_list.Select(0)
    station = window.message_view.get_current_station()

    assert window.message_manager.needs_acknowledgement(message_id, station)[0] is True

    window.cpdlc_session.handle_station_logoff("EDYY")
    window.cpdlc_session.handle_logon_accepted("EDGG")
    station = window.message_view.get_current_station()

    assert window.message_manager.needs_acknowledgement(message_id, station)[0] is False
