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


def test_the_context_menu_outlives_the_handover_window(window):
    """A message from the station that handed the aircraft over once stopped
    offering responses when its window closed. The pilot may still owe it a
    WILCO, and the response is addressed to that station anyway."""
    window.cpdlc_session.handle_logon_accepted("EDYY")
    message_id = window.message_manager.add_message(uplink("EDYY", 4))
    window.message_view.add_message(message_id)
    window.message_view.message_list.Select(0)
    window.cpdlc_session.handle_handover("EDYY", "EDGG")
    window.cpdlc_session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)

    window.message_view.on_context_menu(None)

    assert len(window.panel.popped) == 1


def test_the_context_menu_offers_responses_to_a_station_nobody_is_logged_on_to(window):
    """From the log: a PDC is requested by telex, with no logon anywhere, and
    the departure airport answers with a WILCO/UNABLE clearance. The clearance
    must be acknowledgeable, so responses cannot depend on who the session is
    talking to."""
    clearance = uplink(
        "EDDK",
        45,
        "CLRD TO @BIKF@. @WIPU1Q@ DEPARTURE. MNTN @5000@. DPRTR ON @121.055@. SQUAWK @7331@. EXPCT RWY @13L@.",
    )
    message_id = window.message_manager.add_message(clearance)
    window.message_view.add_message(message_id)
    window.message_view.message_list.Select(0)

    window.message_view.on_context_menu(None)

    assert len(window.panel.popped) == 1
