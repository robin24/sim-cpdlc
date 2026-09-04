"""How the window reacts to uplinks that change session state or tune the radio.

These drive MainWindow._on_message_received with the exact texts the two
networks send, taken from the maintainer's logs.
"""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR, TelexMessage

from src.config import PREVIOUS_STATION_WINDOW_SECONDS
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeConnectionManager,
    FakeSimConnectManager,
    inline_worker,
    make_main_window,
    uplink,
)

CURRENT = "EDYY"
OTHER = "EDUU"
CONTACT = "CONTACT MARSEILLE CONTROL ON @133.325@."


def build(logger, config=None, simconnect=None, station=CURRENT):
    """A window logged on to `station` ("" for none) as DLH123 on Hoppie."""
    connection = FakeConnectionManager()
    session = CpdlcSession(
        logger, connection, clock=FakeClock(), worker=inline_worker(logger)
    )
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    if station:
        session.handle_logon_accepted(station)
    simconnect = simconnect if simconnect is not None else FakeSimConnectManager()
    window = make_main_window(
        logger, session, MessageManager(logger), config=config, simconnect=simconnect
    )
    return window, session, connection, simconnect


def system_rows(window):
    """The texts of the SYSTEM rows in the message list, in order."""
    manager = window.message_manager
    rows = [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]
    return [text for sender, text in rows if sender == "SYSTEM"]


# --- handover -----------------------------------------------------------------


def test_a_handover_logs_off_and_requests_logon_with_the_next_station(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))
    window.worker.run_pending()

    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"
    assert connection.sent == [("EDGG", 1, RR.YES.value, "REQUEST LOGON", None)]
    assert window.status_texts == ["Logged off from EDYY.", "Pending logon to EDGG."]
    assert window.polling_controller.active_calls == 1


def test_a_handover_from_another_station_is_shown_but_not_acted_on(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(OTHER, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == CURRENT
    assert connection.sent == []
    assert window.status_texts == []
    assert len(window.message_view.added) == 1


def test_a_handover_keeps_the_old_station_answerable(logger):
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

    assert session.is_answerable_sender(CURRENT) is True


def test_the_logged_handover_sequence_tunes_and_answers_the_late_contact(logger):
    """Verbatim from the log: KUSA hands over to CZYZ, and the next poll
    carries KUSA's CONTACT together with CZYZ's LOGON ACCEPTED. Older builds
    let the pilot WILCO that CONTACT; the strict scoping on main did not."""
    window, session, connection, simconnect = build(logger, station="KUSA")
    window._on_message_received(uplink("KUSA", 12, "HANDOVER @CZYZ@", rr=RR.NOT_REQUIRED))
    window.worker.run_pending()

    before = len(window.message_view.added)
    window._on_message_received(uplink("KUSA", 13, "CONTACT TORONTO CENTER ON @135.625@."))
    window._on_message_received(uplink("CZYZ", 1, "LOGON ACCEPTED", rr=RR.NOT_REQUIRED, mrn=1))

    contact_id = window.message_view.added[before]
    assert connection.sent == [("CZYZ", 1, RR.YES.value, "REQUEST LOGON", None)]
    assert session.get_current_station() == "CZYZ"
    assert simconnect.tuned == [135.625]
    assert window.message_manager.needs_acknowledgement(contact_id, session.is_answerable_sender)[0] is True

    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)

    assert window.message_manager.needs_acknowledgement(contact_id, session.is_answerable_sender)[0] is False


def test_a_contact_from_the_old_station_is_not_tuned_once_the_window_has_closed(logger):
    window, session, _, simconnect = build(logger, station="KUSA")
    window._on_message_received(uplink("KUSA", 12, "HANDOVER @CZYZ@", rr=RR.NOT_REQUIRED))
    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)

    window._on_message_received(uplink("KUSA", 13, "CONTACT TORONTO CENTER ON @135.625@."))

    assert simconnect.tuned == []


# --- logoff -------------------------------------------------------------------


def test_a_logoff_from_the_current_station_ends_the_logon(logger):
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 5, "LOGOFF", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == ""
    assert window.status_texts == ["Logged off from EDYY."]


@pytest.mark.parametrize(
    "sender, text",
    [(OTHER, "LOGOFF"), (CURRENT, "LOGOFF NOT REQUIRED AT THIS TIME")],
    ids=["other-station", "not-an-exact-logoff"],
)
def test_other_logoff_texts_leave_the_logon_alone(logger, sender, text):
    """TODOS item 23: substring matching once logged off on the second text."""
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(sender, 5, text, rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == CURRENT
    assert window.status_texts == []


# --- protocol noise -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["CURRENT ATC UNIT@_@EDYY@_@MAASTRICHT RADAR", "CURRENT ATS UNIT@_@EDYY@_@MAASTRICHT RADAR"],
    ids=["atc", "ats"],
)
def test_current_unit_announcements_are_hidden(logger, text):
    window, _, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 2, text, rr=RR.NOT_REQUIRED))

    assert window.message_view.added == []
    assert window.message_manager.message_log == {}
    assert window.status_texts == []


# --- CONTACT / MONITOR auto-tune ----------------------------------------------


def test_a_contact_instruction_tunes_the_standby_radio(logger):
    window, _, _, simconnect = build(logger)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert window.status_texts == []


def test_auto_tune_can_be_switched_off(logger):
    window, _, _, simconnect = build(logger, config={"auto_tune_com1": False})

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == []


def test_a_failed_auto_tune_tells_the_pilot_the_frequency(logger):
    """One reconnect off the GUI thread, one more try; then the pilot is told."""
    window, _, _, simconnect = build(logger, simconnect=FakeSimConnectManager(result=False))

    window._on_message_received(uplink(CURRENT, 7, CONTACT))
    window.worker.run_pending()

    assert simconnect.tuned == [133.325]
    assert simconnect.connects == 1
    assert window.status_texts == ["Auto-tune failed \u2014 set 133.325 manually"]


def test_a_lost_simulator_is_reconnected_once_and_the_frequency_resent(logger):
    """MSFS closed and reopened: the first send is refused, the reconnect
    succeeds, the second send lands, and the pilot hears nothing."""
    simconnect = FakeSimConnectManager(tune_results=[False, True])
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert simconnect.disconnects == 1

    window.worker.run_pending()

    assert simconnect.tuned == [133.325, 133.325]
    assert simconnect.connects == 1
    assert window.status_texts == []


def test_the_reconnect_does_not_run_on_the_gui_thread(logger):
    simconnect = FakeSimConnectManager(tune_results=[False, True])
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.connects == 0
    assert window.worker.pending() == 1


def test_two_contacts_during_one_reconnect_share_it_and_the_latest_frequency_wins(logger):
    """Two detached connects would race on the simulator handle; the second
    CONTACT only replaces the frequency the one reconnect will send."""
    simconnect = FakeSimConnectManager(tune_results=[False, False, True])
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))
    window._on_message_received(uplink(CURRENT, 8, "CONTACT PARIS CONTROL ON @128.100@."))

    assert window.worker.pending() == 1
    assert simconnect.disconnects == 1

    window.worker.run_pending()

    assert simconnect.tuned == [133.325, 128.1, 128.1]
    assert simconnect.connects == 1
    assert window.status_texts == []
    assert window._simconnect_reconnecting is False


def test_a_reconnect_that_fails_reports_the_latest_frequency(logger):
    simconnect = FakeSimConnectManager(result=False)
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))
    window._on_message_received(uplink(CURRENT, 8, "CONTACT PARIS CONTROL ON @128.100@."))
    window.worker.run_pending()

    assert window.status_texts == ["Auto-tune failed — set 128.100 manually"]


def test_a_contact_from_another_station_is_not_tuned(logger):
    window, _, _, simconnect = build(logger)

    window._on_message_received(uplink(OTHER, 7, CONTACT))

    assert simconnect.tuned == []


# --- only CPDLC carries session state (audit L-2) -----------------------------


@pytest.mark.parametrize(
    "text",
    ["LOGON ACCEPTED", "LOGOFF", "HANDOVER @EDGG@"],
    ids=["accepted", "logoff", "handover"],
)
def test_a_telex_cannot_drive_the_session(logger, text):
    """The old hasattr gate let any HoppieMessage through; a telex from the
    current station reading LOGON ACCEPTED was treated as one."""
    window, session, connection, _ = build(logger)

    window._on_message_received(TelexMessage(CURRENT, CLIENT_CALLSIGN, text))

    assert session.get_current_station() == CURRENT
    assert connection.sent == []
    assert window.status_texts == []
    assert len(window.message_view.added) == 1


# --- logon acceptance and rejection (audit L-3) -------------------------------


def test_logon_accepted_with_trailing_text_still_logs_on(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(
        uplink("EDGG", 1, "LOGON ACCEPTED WELCOME", rr=RR.NOT_REQUIRED, mrn=1)
    )

    assert session.get_current_station() == "EDGG"
    assert window.status_texts == ["Logged on to EDGG."]


def test_a_logon_rejected_cancels_the_pending_logon(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink("EDGG", 1, "LOGON REJECTED", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station is None
    assert window.status_texts == ["Logon to EDGG rejected."]
    assert system_rows(window) == ["Logon to EDGG rejected"]


def test_an_unable_answering_the_logon_request_cancels_it(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink("EDGG", 1, "UNABLE", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station is None
    assert window.status_texts == ["Logon to EDGG rejected."]
    assert system_rows(window) == ["Logon to EDGG rejected"]


def test_an_unable_answering_another_request_is_only_shown(logger):
    window, session, _, _ = build(logger)
    session.send_altitude_change_request("FL350")  # our MIN 1

    window._on_message_received(uplink(CURRENT, 9, "UNABLE", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.get_current_station() == CURRENT
    assert window.status_texts == []
    assert system_rows(window) == []
    assert len(window.message_view.added) == 1


def test_a_rejection_from_a_station_we_did_not_ask_is_only_shown(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink(OTHER, 1, "LOGON REJECTED", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station == "EDGG"
    assert window.status_texts == []
