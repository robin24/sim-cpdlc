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
    inline_worker,
    make_main_window,
)

STATION = "EDYY"


def build(logger, connection=None):
    """A window logged on to EDYY as DLH123 on Hoppie, MIN counter at 1."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(
        logger, connection, clock=FakeClock(), worker=inline_worker(logger)
    )
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
    """The LOGOFF is queued ahead of the disconnect, so the connection is only
    closed once it has gone out; the menu item comes back with the result."""
    window, session, connection, manager = build(logger)

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert window.status_texts[-1] == "Disconnecting..."
    assert window.menu_item_connect.enabled is False
    assert connection.disconnected is False

    window.worker.run_pending()

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert connection.disconnected is True
    assert rows(manager) == [
        (CLIENT_CALLSIGN, "LOGOFF"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert window.status_texts[-1] == "Disconnected from CPDLC network."
    assert (window.menu_item_connect.enabled, window.menu_item_connect.label) == (True, "&Connect")
    assert window.worker.generation == 1


def test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails(logger):
    """Audit M-1: a dead link is the usual reason to disconnect, and the
    failed LOGOFF used to leave the app believing it was still logged on."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, connection, manager = build(logger, connection)

    window.on_disconnect()
    window.worker.run_pending()

    assert dialogue(session) == ("", None, "", 1)
    assert rows(manager) == [
        ("SYSTEM", "Could not send LOGOFF to EDYY: timed out"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert connection.disconnected is True


def test_disconnect_forgets_the_responses_that_were_in_flight(logger):
    """Their results were dropped with the generation, so nothing would ever
    release them; the next session must not find the uplink blocked."""
    window, session, connection, manager = build(logger)
    window._responses_in_flight[7] = "WILCO"

    window.on_disconnect()
    window.worker.run_pending()

    assert window._responses_in_flight == {}


def test_disconnect_closes_a_handover_in_progress(logger):
    window, session, connection, _ = build(logger)
    session.handle_handover(STATION, "EDGG")

    window.on_disconnect()
    window.worker.run_pending()

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


def test_a_request_during_the_disconnect_window_is_refused(logger, monkeypatch, message_boxes):
    """Between Disconnect and the disconnect job reporting, is_connected() is
    still True; a logon queued then would go out ahead of the disconnect and
    leave a pending logon behind for the next session."""
    monkeypatch.setattr(mw, "LogonDialog", FakeLogonDialog)
    window, session, connection, _ = build(logger)
    window.on_disconnect()

    window.on_logon(None)

    assert message_boxes.captions[-1] == "Not Connected"
    assert session.pending_logon_station is None

    window.worker.run_pending()

    assert [frame[3] for frame in connection.sent] == ["LOGOFF"]
    assert window._link_busy is False


def test_every_connection_gated_handler_refuses_while_the_link_is_busy(logger, message_boxes):
    window, _, _, _ = build(logger)
    window._link_busy = True

    for handler in (
        window.on_logon,
        window.on_altitude_change,
        window.on_direct_request,
        window.on_speed_request,
        window.on_when_can_we_expect,
        window.on_telex,
        window.on_weather_request,
        window.on_pdc_request,
    ):
        handler(None)

    assert message_boxes.captions == ["Not Connected"] * 8


# --- exit ---------------------------------------------------------------------


def test_exit_logs_off_and_forgets_the_dialogue(logger):
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)
    window.worker.run_pending()

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert window.polling_controller.stopped is True
    assert window.weather_monitor.shut_down is True
    assert event.skipped is True


def test_exit_reports_a_logoff_it_could_not_send(logger):
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, _, manager = build(logger, connection)

    window.on_close(FakeCloseEvent())
    window.worker.run_pending()

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
    window._responses_in_flight[7] = "WILCO"

    window._on_link_change(LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")

    assert dialogue(session) == ("", None, "", 1)
    assert window.worker.generation == 1
    assert window._responses_in_flight == {}


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

    def __init__(self, parent, fetch_simbrief=None):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_connection_details(self):
        return ("BAW123", "secret", "sayintentions")

    def Destroy(self):
        pass


def test_connecting_hands_the_identity_to_the_session(logger, monkeypatch):
    """The connect runs on the worker; the menu item is disabled until it
    reports. A different callsign or network starts a clean dialogue; the
    session decides, the window only passes both on."""
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    window, session, connection, manager = build(logger)

    window.on_connect()

    assert window.status_texts[-1] == "Connecting as BAW123..."
    assert window.menu_item_connect.enabled is False
    assert connection.connected_as is None

    window.worker.run_pending()

    assert connection.connected_as == ("BAW123", "sayintentions")
    assert (session.get_callsign(), session.network) == ("BAW123", "sayintentions")
    assert session.is_logged_on() is False
    assert window.polling_controller.started is True
    assert window.menu_item_connect.enabled is True
    assert window.status_texts[-1] == "Connected as BAW123."
    assert rows(manager) == [("SYSTEM", "Connected as BAW123")]


def test_a_failed_connection_is_reported_and_the_menu_item_comes_back(logger, monkeypatch, message_boxes):
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    connection = FakeConnectionManager(connect_error=HoppieError("invalid logon code"))
    window, session, connection, _ = build(logger, connection)

    window.on_connect()
    window.worker.run_pending()

    assert message_boxes.captions == ["Error"]
    assert "invalid logon code" in message_boxes.calls[0][0]
    assert window.menu_item_connect.enabled is True
    assert window.status_texts[-1] == "Not connected."
    assert window.polling_controller.started is False


# --- Requests > Logon ----------------------------------------------------------


class FakeLogonDialog:
    """Stands in for LogonDialog: answers OK with a fixed station, never shows."""

    def __init__(self, parent):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_logon_details(self):
        return "EDGG"

    def Destroy(self):
        pass


def test_a_manual_logon_while_logged_on_echoes_the_logoff_it_sends(logger, monkeypatch):
    """The message list is the transcript of what went out; the LOGOFF that
    logon() sends first must appear in it like every other frame."""
    monkeypatch.setattr(mw, "LogonDialog", FakeLogonDialog)
    window, session, connection, manager = build(logger)

    window.on_logon(None)
    window.worker.run_pending()

    assert [frame[3] for frame in connection.sent] == ["LOGOFF", "REQUEST LOGON"]
    assert rows(manager) == [(CLIENT_CALLSIGN, "LOGOFF"), (CLIENT_CALLSIGN, "REQUEST LOGON")]
    assert window.status_texts[-1] == "Pending logon to EDGG."


def test_a_failed_logoff_before_a_relogon_is_named_correctly(logger, monkeypatch, message_boxes):
    """The LOGOFF to the old station and the REQUEST LOGON to the new one
    report separately, each naming its own station and frame."""
    monkeypatch.setattr(mw, "LogonDialog", FakeLogonDialog)
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, connection, _ = build(logger, connection)

    window.on_logon(None)
    window.worker.run_pending()

    assert [call[0] for call in message_boxes.calls] == [
        "Failed to send LOGOFF to EDYY: timed out. The logon to EDGG goes ahead.",
        "Failed to send logon request to EDGG: timed out.",
    ]
    assert "Could not send LOGOFF to EDYY." in window.status_texts
    assert window.status_texts[-1] == "Could not log on to EDGG."
