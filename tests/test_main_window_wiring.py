"""Integration test for the real MainWindow._init_ui wiring.

MainWindow.__init__ opens dialogs, loads a sound and starts an update check.
This subclass runs the genuine _init_ui (and _init_menu) on a real frame with
only the collaborators those methods need, so a mis-wired MessageView is caught
here rather than at application startup.
"""

import pytest
import wx

from src.config import PREVIOUS_STATION_WINDOW_SECONDS
from src.gui.main_window import MainWindow
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeClock, FakeConnectionManager, inline_worker, uplink

STATION = "LSAG"


class HeadlessMainWindow(MainWindow):
    def __init__(self, logger, cpdlc_session, message_manager):
        wx.Frame.__init__(self, None, title="Sim-CPDLC test")
        self.logger = logger
        self.cpdlc_session = cpdlc_session
        self.message_manager = message_manager
        self._init_ui()


@pytest.fixture
def window(logger, wx_app):
    session = CpdlcSession(
        logger, FakeConnectionManager(), clock=FakeClock(), worker=inline_worker(logger)
    )
    frame = HeadlessMainWindow(logger, session, MessageManager(logger))
    # PopupMenu runs a nested modal loop, which would hang the test; count
    # the menus that would have been shown instead.
    frame.panel.popped = []
    frame.panel.PopupMenu = frame.panel.popped.append
    yield frame
    frame.Destroy()


def test_init_ui_wires_the_message_view_to_the_live_session(window):
    """The view must ask the session, not a stale copy, who can be answered."""
    window.cpdlc_session.handle_logon_accepted(STATION)

    assert window.message_view.is_answerable_sender(STATION) is True
    assert window.message_view.is_answerable_sender("EDGG") is False


def test_context_menu_follows_the_session_after_a_handover(window):
    """A message from the station that handed us over keeps offering
    responses until its window closes, then stops."""
    window.cpdlc_session.handle_logon_accepted("EDYY")
    message_id = window.message_manager.add_message(uplink("EDYY", 4))
    window.message_view.add_message(message_id)
    window.message_view.message_list.Select(0)
    window.cpdlc_session.handle_handover("EDYY", "EDGG")

    window.message_view.on_context_menu(None)
    assert len(window.panel.popped) == 1

    window.cpdlc_session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)
    window.message_view.on_context_menu(None)
    assert len(window.panel.popped) == 1
