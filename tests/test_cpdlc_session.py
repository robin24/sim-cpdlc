"""Tests for CPDLC session state: logon validation, lifecycle and the handover window."""

from hoppie_connector import HoppieError

from src.model.cpdlc_session import CpdlcSession
from tests.support import FakeClock, FakeConnectionManager


def build(logger, connection=None):
    """A session with a hand-driven clock, identified as DLH123 on Hoppie."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock())
    session.begin_session("DLH123", "hoppie")
    return session


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


def test_logon_accepted_with_a_different_mrn_is_rejected(logger):
    """TODOS item 24: the MRN must reference our REQUEST LOGON, which always
    carries MIN 1 because logon() restarts the counter."""
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDDF", mrn=2)

    assert accepted is False
    assert session.get_current_station() == ""


# --- lifecycle ----------------------------------------------------------------


def test_reset_forgets_the_dialogue_but_not_the_identity(logger):
    session = build(logger)
    session.logon("EDGG")
    session.handle_logon_accepted("EDGG", mrn=1)
    session.send_altitude_change_request("FL350")

    session.reset()

    assert session.get_current_station() == ""
    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)
    assert session.cpdlc_min_counter == 1
    assert session.get_callsign() == "DLH123"


def test_reset_clears_a_pending_logon(logger):
    session = build(logger)
    session.logon("EDGG")

    session.reset()

    assert (
        session.pending_logon_station,
        session.pending_logon_min,
        session.pending_logon_at,
    ) == (None, None, None)


def test_a_new_session_under_the_same_identity_keeps_the_logon(logger):
    """Decision 4 of the design: the network holds the ATC logon by callsign,
    so reconnecting as the same aircraft must not pretend it is gone."""
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("DLH123", "hoppie")

    assert session.get_current_station() == "EDGG"


def test_a_new_session_under_another_callsign_starts_clean(logger):
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("BAW123", "hoppie")

    assert session.get_current_station() == ""
    assert session.get_callsign() == "BAW123"


def test_a_new_session_on_another_network_starts_clean(logger):
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("DLH123", "sayintentions")

    assert session.get_current_station() == ""
    assert session.network == "sayintentions"


def test_a_logon_request_records_when_it_was_sent(logger):
    session = build(logger)
    session.clock.now = 1234.0

    session.logon("EDGG")

    assert session.pending_logon_at == 1234.0


# --- logon while logged on (audit M-7) ----------------------------------------


def test_logging_on_while_logged_on_sends_logoff_first(logger):
    """Audit M-7: without the LOGOFF the old station was never told, and the
    MIN restarted on a dialogue it still considered open."""
    session = build(logger)
    session.handle_logon_accepted("EDYY")
    session.send_altitude_change_request("FL350")  # MIN 1 spent

    result = session.logon("EDGG")

    assert result == (True, "REQUEST LOGON")
    assert session.connection_manager.sent[1:] == [
        ("EDYY", 2, "NE", "LOGOFF", None),
        ("EDGG", 1, "Y", "REQUEST LOGON", None),
    ]
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"


def test_relogging_on_to_the_same_station_closes_the_dialogue_first(logger):
    session = build(logger)
    session.handle_logon_accepted("EDYY")

    session.logon("EDYY")

    assert [frame[3] for frame in session.connection_manager.sent] == ["LOGOFF", "REQUEST LOGON"]
    assert session.pending_logon_station == "EDYY"


def test_a_failed_logoff_aborts_the_new_logon(logger):
    """The old station must be told before the dialogue moves on, and a link
    that has just failed would only fail again; the pilot retries instead."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    session = build(logger, connection)
    session.handle_logon_accepted("EDYY")

    result = session.logon("EDGG")

    assert result == (False, "could not send LOGOFF to EDYY: timed out")
    assert session.get_current_station() == "EDYY"
    assert session.pending_logon_station is None
    assert connection.sent == []


def test_logoff_clears_a_pending_logon(logger):
    """State an earlier build could leave behind: logged on and pending."""
    session = build(logger)
    session.handle_logon_accepted("EDYY")
    session.pending_logon_station, session.pending_logon_min = "EDGG", 1

    session.logoff()

    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)
