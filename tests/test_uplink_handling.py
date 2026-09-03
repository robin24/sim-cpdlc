"""How the window reacts to uplinks that change session state or tune the radio.

These drive MainWindow._on_message_received with the exact texts the two
networks send, taken from the maintainer's logs.
"""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR

from tests.support import (
    FakeConnectionManager,
    FakeSimConnectManager,
    make_main_window,
    uplink,
)
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

CURRENT = "EDYY"
OTHER = "EDUU"
CONTACT = "CONTACT MARSEILLE CONTROL ON @133.325@."


def build(logger, config=None, simconnect=None):
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection)
    session.begin_session("DLH123", "hoppie")
    session.handle_logon_accepted(CURRENT)
    simconnect = simconnect if simconnect is not None else FakeSimConnectManager()
    window = make_main_window(
        logger, session, MessageManager(logger), config=config, simconnect=simconnect
    )
    return window, session, connection, simconnect


# --- handover -----------------------------------------------------------------


def test_a_handover_logs_off_and_requests_logon_with_the_next_station(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

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
    window, _, _, simconnect = build(logger, simconnect=FakeSimConnectManager(result=False))

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert window.status_texts == ["Auto-tune failed \u2014 set 133.325 manually"]


def test_a_contact_from_another_station_is_not_tuned(logger):
    window, _, _, simconnect = build(logger)

    window._on_message_received(uplink(OTHER, 7, CONTACT))

    assert simconnect.tuned == []
