"""Tests for CPDLC session state, especially logon acceptance validation."""

from conftest import FakeConnectionManager
from src.model.cpdlc_session import CpdlcSession


def test_logon_accepted_from_a_station_other_than_the_pending_one_is_rejected(logger):
    """A stale station must not be able to claim a logon we requested elsewhere.

    Each logon() resets cpdlc_min_counter to 1, so every pending logon carries
    MIN 1 and the MRN alone cannot distinguish which station we asked.
    """
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDGG")
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDGG", mrn=1)

    assert accepted is False
    assert session.get_current_station() == ""


def test_logon_accepted_from_the_pending_station_is_accepted(logger):
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDDF", mrn=1)

    assert accepted is True
    assert session.get_current_station() == "EDDF"


def test_unsolicited_logon_accepted_is_still_honoured(logger):
    """Automatic handovers arrive with no pending logon; that path must keep working."""
    session = CpdlcSession(logger, FakeConnectionManager())

    accepted = session.handle_logon_accepted("EDUU", mrn=None)

    assert accepted is True
    assert session.get_current_station() == "EDUU"


def test_logon_accepted_with_invalid_station_name_is_rejected(logger):
    session = CpdlcSession(logger, FakeConnectionManager())

    accepted = session.handle_logon_accepted("TOOLONG", mrn=None)

    assert accepted is False
    assert session.get_current_station() == ""
