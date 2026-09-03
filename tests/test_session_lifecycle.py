"""Where the ATC dialogue ends: File > Disconnect, exit, a rejected logon code.

A lost link is not one of them: the network holds the logon by callsign, so
the session must survive an outage (design decision 4).
"""

import wx
from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

import src.gui.main_window as mw
from src.controller.link_state import LinkState
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeCloseEvent,
    FakeConnectionManager,
    make_main_window,
)

STATION = "EDYY"


def build(logger, connection=None):
    """A window logged on to EDYY as DLH123 on Hoppie, MIN counter at 1."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock())
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, session, connection, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def dialogue(session):
    """The state reset() is responsible for."""
    return (
        session.get_current_station(),
        session.pending_logon_station,
        session.previous_station,
        session.cpdlc_min_counter,
    )


# --- File > Disconnect --------------------------------------------------------


def test_disconnect_logs_off_and_forgets_the_dialogue(logger):
    window, session, connection, manager = build(logger)

    window.on_disconnect()

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert connection.disconnected is True
    assert rows(manager) == [
        (CLIENT_CALLSIGN, "LOGOFF"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert window.status_texts == ["Disconnected from CPDLC network."]


def test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails(logger):
    """Audit M-1: a dead link is the usual reason to disconnect, and the
    failed LOGOFF used to leave the app believing it was still logged on."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, connection, manager = build(logger, connection)

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert rows(manager)[0] == ("SYSTEM", "Could not send LOGOFF to EDYY: timed out")
    assert connection.disconnected is True


def test_disconnect_closes_a_handover_in_progress(logger):
    window, session, connection, _ = build(logger)
    session.handle_handover(STATION, "EDGG")

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert session.is_answerable_sender(STATION) is False
    assert [frame[3] for frame in connection.sent] == ["REQUEST LOGON"]


def test_a_cancelled_disconnect_changes_nothing(logger, message_boxes):
    message_boxes.answer = wx.NO
    window, session, connection, _ = build(logger)

    window.on_disconnect()

    assert session.get_current_station() == STATION
    assert connection.sent == []
    assert connection.disconnected is False


# --- exit ---------------------------------------------------------------------


def test_exit_logs_off_and_forgets_the_dialogue(logger):
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert window.polling_controller.stopped is True
    assert window.weather_monitor.shut_down is True
    assert event.skipped is True


def test_exit_reports_a_logoff_it_could_not_send(logger):
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, _, manager = build(logger, connection)

    window.on_close(FakeCloseEvent())

    assert rows(manager) == [("SYSTEM", "Could not send LOGOFF to EDYY: timed out")]
    assert session.is_logged_on() is False


def test_a_vetoed_exit_keeps_the_logon(logger, message_boxes):
    message_boxes.answer = wx.NO
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)

    assert event.vetoed is True
    assert session.get_current_station() == STATION
    assert connection.sent == []


# --- a rejected logon code ----------------------------------------------------


def test_a_rejected_logon_code_forgets_the_dialogue(logger):
    window, session, _, _ = build(logger)
    session.handle_handover(STATION, "EDGG")

    window._on_link_change(LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")

    assert dialogue(session) == ("", None, "", 1)


# --- an outage is not a disconnect --------------------------------------------


def test_a_lost_and_restored_link_keeps_the_logon(logger):
    window, session, _, _ = build(logger)
    session.send_altitude_change_request("FL350")

    window._on_link_change(LinkState.DEGRADED, LinkState.LOST, "timed out")
    window._on_link_change(LinkState.LOST, LinkState.CONNECTED, None)

    assert dialogue(session) == (STATION, None, "", 2)


# --- File > Connect -----------------------------------------------------------


class FakeConnectDialog:
    """Stands in for ConnectDialog: answers OK with fixed details, never shows."""

    def __init__(self, parent):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_connection_details(self):
        return ("BAW123", "secret", "sayintentions")

    def Destroy(self):
        pass


def test_connecting_hands_the_identity_to_the_session(logger, monkeypatch):
    """A different callsign or network starts a clean dialogue; the session
    decides, the window only passes both on."""
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    window, session, connection, manager = build(logger)

    window.on_connect()

    assert connection.connected_as == ("BAW123", "sayintentions")
    assert (session.get_callsign(), session.network) == ("BAW123", "sayintentions")
    assert session.is_logged_on() is False
    assert window.polling_controller.started is True
    assert window.status_texts == ["Connected as BAW123."]
    assert rows(manager) == [("SYSTEM", "Connected as BAW123")]
