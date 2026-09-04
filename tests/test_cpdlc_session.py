"""Tests for CPDLC session state: logon validation, lifecycle and the handover window."""

import logging

from hoppie_connector import HoppieError

from src.config import PENDING_LOGON_TIMEOUT_SECONDS, PREVIOUS_STATION_WINDOW_SECONDS
from src.model.cpdlc_session import CpdlcSession
from tests.support import FakeClock, FakeConnectionManager, inline_worker


def build(logger, connection=None):
    """A session with a hand-driven clock, identified as DLH123 on Hoppie."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(
        logger, connection, clock=FakeClock(), worker=inline_worker(logger)
    )
    session.begin_session("DLH123", "hoppie")
    return session


def test_logon_accepted_from_a_station_other_than_the_pending_one_is_rejected(logger):
    """A stale station must not be able to claim a logon we requested elsewhere.

    Each logon() resets cpdlc_min_counter to 1, so every pending logon carries
    MIN 1 and the MRN alone cannot distinguish which station we asked.
    """
    session = build(logger)
    session.logon("EDGG")
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDGG", mrn=1)

    assert accepted is False
    assert session.get_current_station() == ""


def test_logon_accepted_from_the_pending_station_is_accepted(logger):
    session = build(logger)
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDDF", mrn=1)

    assert accepted is True
    assert session.get_current_station() == "EDDF"


def test_unsolicited_logon_accepted_is_still_honoured(logger):
    """Automatic handovers arrive with no pending logon; that path must keep working."""
    session = build(logger)

    accepted = session.handle_logon_accepted("EDUU", mrn=None)

    assert accepted is True
    assert session.get_current_station() == "EDUU"


def test_logon_accepted_with_invalid_station_name_is_rejected(logger):
    session = build(logger)

    accepted = session.handle_logon_accepted("TOOLONG", mrn=None)

    assert accepted is False
    assert session.get_current_station() == ""


def test_logon_accepted_with_a_different_mrn_is_rejected(logger):
    """TODOS item 24: the MRN must reference our REQUEST LOGON, which always
    carries MIN 1 because logon() restarts the counter."""
    session = build(logger)
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
    session.worker.run_pending()

    assert result is True
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
    session.worker.run_pending()

    assert [frame[3] for frame in session.connection_manager.sent] == ["LOGOFF", "REQUEST LOGON"]
    assert session.pending_logon_station == "EDYY"


def test_a_failed_logoff_does_not_stop_the_new_logon(logger):
    """Both frames are queued before either goes out (the worker spaces
    them); each reports for itself, and a REQUEST LOGON that failed to go
    out leaves nothing pending."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    session = build(logger, connection)
    session.handle_logon_accepted("EDYY")
    outcomes = []

    assert session.logon("EDGG", lambda ok, text: outcomes.append((ok, text))) is True
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"

    session.worker.run_pending()

    assert outcomes == [(False, "timed out"), (False, "timed out")]
    assert session.pending_logon_station is None


def test_logoff_clears_a_pending_logon(logger):
    """State an earlier build could leave behind: logged on and pending."""
    session = build(logger)
    session.handle_logon_accepted("EDYY")
    session.pending_logon_station, session.pending_logon_min = "EDGG", 1

    session.logoff()

    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)


# --- the handover window ------------------------------------------------------


def test_a_handover_moves_the_logon_and_keeps_the_old_station_answerable(logger):
    """In 22 of 163 logged handovers the old station's CONTACT arrived after
    the handover, in the same poll as the new station's LOGON ACCEPTED."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    result = session.handle_handover("KUSA", "CZYZ")
    session.worker.run_pending()

    assert result is True
    assert session.connection_manager.sent == [("CZYZ", 1, "Y", "REQUEST LOGON", None)]
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "CZYZ"
    assert session.is_answerable_sender("KUSA") is True
    assert session.is_answerable_sender("CZYZ") is False


def test_the_old_station_stops_being_answerable_when_the_window_closes(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")
    session.handle_logon_accepted("CZYZ", mrn=1)

    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS - 1)
    assert session.is_answerable_sender("KUSA") is True

    session.clock.advance(1)
    assert session.is_answerable_sender("KUSA") is False
    assert session.is_answerable_sender("CZYZ") is True


def test_a_handover_from_a_station_that_is_not_logged_on_is_ignored(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    assert session.handle_handover("EDUU", "CZYZ") is False
    assert session.get_current_station() == "KUSA"
    session.worker.run_pending()
    assert session.connection_manager.sent == []


def test_a_handover_sends_no_logoff(logger):
    """The station handing over has ended the dialogue itself."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    session.handle_handover("KUSA", "CZYZ")
    session.worker.run_pending()

    assert [frame[3] for frame in session.connection_manager.sent] == ["REQUEST LOGON"]


def test_nobody_is_answerable_when_not_logged_on(logger):
    session = build(logger)

    assert session.is_answerable_sender("KUSA") is False
    assert session.is_answerable_sender("") is False


def test_reset_closes_the_handover_window(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")

    session.reset()

    assert session.is_answerable_sender("KUSA") is False
    assert (session.previous_station, session.previous_station_until) == ("", None)


def test_only_a_stranger_is_flagged_when_acknowledged(logger, caplog):
    """A WILCO to the station that handed over is part of the dialogue and
    must not be logged as a mismatch."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")
    session.handle_logon_accepted("CZYZ", mrn=1)

    # The shared `logger` fixture disables propagation so tests stay silent;
    # caplog's handler has to be attached to it directly.
    with caplog.at_level(logging.WARNING, logger=logger.name):
        logger.addHandler(caplog.handler)
        session.send_acknowledgement("KUSA", 7, "WILCO")
        session.send_acknowledgement("EDUU", 8, "WILCO")

    flagged = [record.getMessage() for record in caplog.records if "dialogue" in record.getMessage()]
    assert flagged == ["Acknowledgement sender EDUU is not part of the dialogue (current station CZYZ)"]


def test_logging_off_closes_the_handover_window(logger):
    """After Requests > Logoff the aircraft talks to nobody; a late CONTACT
    from the station that handed over must neither tune nor offer a WILCO."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")
    session.handle_logon_accepted("CZYZ", mrn=1)

    session.logoff()

    assert session.is_answerable_sender("KUSA") is False
    assert (session.previous_station, session.previous_station_until) == ("", None)


# --- rejection and expiry (audit L-3) -----------------------------------------


def test_a_logon_rejected_by_the_pending_station_cancels_the_logon(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG", mrn=1) is True
    assert session.pending_logon_station is None
    assert session.get_current_station() == ""


def test_a_rejection_without_an_mrn_still_counts(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG") is True
    assert session.pending_logon_station is None


def test_a_rejection_from_another_station_is_ignored(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDUU", mrn=1) is False
    assert session.pending_logon_station == "EDGG"


def test_an_unable_for_another_request_is_not_a_rejection(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG", mrn=2) is False
    assert session.pending_logon_station == "EDGG"


def test_a_rejection_with_nothing_pending_is_ignored(logger):
    session = build(logger)
    session.handle_logon_accepted("EDYY")

    assert session.handle_logon_rejected("EDYY", mrn=1) is False
    assert session.get_current_station() == "EDYY"


def test_an_unanswered_logon_expires_after_the_timeout(logger):
    session = build(logger)
    session.logon("EDGG")

    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS - 1)
    assert session.expire_pending() is None
    assert session.pending_logon_station == "EDGG"

    session.clock.advance(1)
    assert session.expire_pending() == "EDGG"
    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)


def test_expiry_reports_each_unanswered_logon_once(logger):
    session = build(logger)
    session.logon("EDGG")
    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)
    session.expire_pending()

    assert session.expire_pending() is None


def test_expiry_leaves_an_accepted_logon_alone(logger):
    session = build(logger)
    session.logon("EDGG")
    session.handle_logon_accepted("EDGG", mrn=1)
    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)

    assert session.expire_pending() is None
    assert session.get_current_station() == "EDGG"


def test_expiry_can_be_asked_about_a_given_time(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.expire_pending(now=session.clock.now + PENDING_LOGON_TIMEOUT_SECONDS) == "EDGG"
