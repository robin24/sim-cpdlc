"""The status bar must not report a logon the session model refused.

README.md documents the status bar as the surface screen-reader users query
with NVDA+End, so a false 'Logged on to X' is the one message a blind pilot
cannot cross-check.
"""

from conftest import FakeConnectionManager, make_main_window, uplink
from hoppie_connector import CpdlcResponseRequirement as RR

from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager


def _logon_accepted_from(station, mrn):
    return uplink(station, mrn, text="LOGON ACCEPTED", rr=RR.NOT_REQUIRED)


def test_status_bar_is_silent_when_logon_acceptance_is_rejected(logger):
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDGG")
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDGG", 1))

    assert window.status_texts == []
    assert session.get_current_station() == ""


def test_status_bar_reports_an_accepted_logon(logger):
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDDF", 1))

    assert window.status_texts == ["Logged on to EDDF."]
    assert session.get_current_station() == "EDDF"
