"""The status bar must not report a logon the session model refused.

README.md documents the status bar as the surface screen-reader users query
with NVDA+End, so a false 'Logged on to X' is the one message a blind pilot
cannot cross-check.
"""

from hoppie_connector import CpdlcResponseRequirement as RR

from src.config import PENDING_LOGON_TIMEOUT_SECONDS
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    FakeClock,
    FakeConnectionManager,
    inline_worker,
    make_main_window,
    uplink,
)


def _logon_accepted_from(station, mrn):
    """A real acceptance: the station's own MIN 1, referencing our MIN as MRN.
    All 388 LOGON ACCEPTED uplinks in six months of logs carried an MRN."""
    return uplink(station, 1, text="LOGON ACCEPTED", rr=RR.NOT_REQUIRED, mrn=mrn)


def test_status_bar_is_silent_when_logon_acceptance_is_rejected(logger):
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    session.logon("EDGG")
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDGG", 1))

    assert window.status_texts == []
    assert session.get_current_station() == ""


def test_status_bar_reports_an_accepted_logon(logger):
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDDF", 1))

    assert window.status_texts == ["Logged on to EDDF."]
    assert session.get_current_station() == "EDDF"


def test_status_bar_is_silent_when_the_mrn_does_not_match(logger):
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDDF", 2))

    assert window.status_texts == []
    assert session.get_current_station() == ""


def test_an_unanswered_logon_is_given_up_on_and_announced(logger):
    """Audit L-3: a pending logon never expired, so the status bar said
    "Pending logon to X." for the rest of the flight."""
    session = CpdlcSession(
        logger, FakeConnectionManager(), clock=FakeClock(), worker=inline_worker(logger)
    )
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_poll_tick()
    assert window.status_texts == []

    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)
    window._on_poll_tick()
    window._on_poll_tick()

    assert window.status_texts == ["Logon to EDDF not answered."]
    assert session.pending_logon_station is None
    manager = window.message_manager
    assert [manager.get_message_display_text(mid) for mid in manager.message_log] == [
        ("SYSTEM", "Logon to EDDF not answered")
    ]
