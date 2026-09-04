"""Tests for message identity, acknowledgement state and response options."""

import pytest

from tests.support import answerable, uplink
from hoppie_connector import CpdlcResponseRequirement as RR

from src.model.message_manager import MessageManager

STATION = "LSAG"


def test_a_reused_min_does_not_suppress_a_later_message(logger):
    """Regression test for the bug this branch fixes.

    MIN is the sending station's own counter and restarts when that station
    re-logs on, so the same (sender, MIN) pair recurs within one flight. Keying
    acknowledgements on it made the second instruction unanswerable.
    """
    manager = MessageManager(logger)
    climb = manager.add_message(uplink(STATION, 53, "CLIMB TO AND MAINTAIN FL360"))
    manager.mark_acknowledged(climb, "WILCO")

    contact = manager.add_message(uplink(STATION, 53, "CONTACT MARSEILLE CONTROL"))

    needs_ack, responses = manager.needs_acknowledgement(contact, answerable(STATION))
    assert needs_ack is True
    assert responses == ["WILCO", "UNABLE", "STANDBY"]


def test_acknowledging_one_message_does_not_answer_the_other(logger):
    manager = MessageManager(logger)
    climb = manager.add_message(uplink(STATION, 53, "CLIMB TO AND MAINTAIN FL360"))
    manager.mark_acknowledged(climb, "WILCO")

    assert manager.needs_acknowledgement(climb, answerable(STATION)) == (False, [])


def test_standby_leaves_the_message_answerable(logger):
    """The one behaviour that must not regress: STANDBY is not a final answer."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 7))

    manager.mark_acknowledged(message_id, "STANDBY")

    needs_ack, responses = manager.needs_acknowledgement(message_id, answerable(STATION))
    assert needs_ack is True
    assert responses == ["WILCO", "UNABLE", "STANDBY"]


def test_standby_is_recognised_regardless_of_case(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 7))

    manager.mark_acknowledged(message_id, "standby")

    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True


def test_a_message_from_another_station_offers_no_responses(logger):
    """A station the session no longer answers for offers no responses."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("EDYY", 4))

    assert manager.needs_acknowledgement(message_id, answerable("EDGG")) == (False, [])


def test_a_message_offers_no_responses_when_not_logged_on(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("EDYY", 4))

    assert manager.needs_acknowledgement(message_id, answerable()) == (False, [])


def test_the_predicate_is_asked_about_the_message_sender(logger):
    """After a handover the previous station stays answerable for a while;
    the manager only relays the question to whoever knows the dialogue."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("KUSA", 4))
    asked = []

    def is_answerable(sender):
        asked.append(sender)
        return True

    assert manager.needs_acknowledgement(message_id, is_answerable)[0] is True
    assert asked == ["KUSA"]


def test_a_custom_row_never_asks_the_predicate(logger):
    manager = MessageManager(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    def never(sender):
        raise AssertionError("asked about a SYSTEM row")

    assert manager.needs_acknowledgement(message_id, never) == (False, [])


def test_get_cpdlc_addressing_returns_sender_and_min(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    assert manager.get_cpdlc_addressing(message_id) == (STATION, 53)


def test_get_cpdlc_addressing_rejects_a_custom_message(logger):
    manager = MessageManager(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    assert manager.get_cpdlc_addressing(message_id) is None


def test_get_cpdlc_addressing_rejects_an_unknown_id(logger):
    manager = MessageManager(logger)

    assert manager.get_cpdlc_addressing(4242) is None


def test_a_roger_message_offers_roger_and_standby(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 9, "ALTIMETER 1013", rr=RR.ROGER))

    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (
        True,
        ["ROGER", "STANDBY"],
    )


def test_a_message_needing_no_response_offers_none(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(
        uplink(STATION, 10, "LOGON ACCEPTED", rr=RR.NOT_REQUIRED)
    )

    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (False, [])


def test_marking_an_unknown_id_is_harmless(logger):
    manager = MessageManager(logger)

    manager.mark_acknowledged(4242, "WILCO")  # must not raise


def test_a_weather_report_reaches_the_reader_without_separators(logger):
    """Hoppie separates report lines with @, which a screen reader announces as
    the word "at" if it is left in the text."""
    manager = MessageManager(logger)
    message_id = manager.add_weather_message(
        "EGLL ATIS INFO K@RWY IN USE 27R", "EGLL", "vatatis"
    )

    _, row = manager.get_message_display_text(message_id)
    detail = manager.get_message_detail_text(message_id)

    assert "@" not in row
    assert "@" not in detail
    assert detail == "ATIS EGLL\n\nEGLL ATIS INFO K\nRWY IN USE 27R"


RESPONSE_TABLE = [
    (RR.WILCO_UNABLE, ["WILCO", "UNABLE", "STANDBY"]),
    (RR.AFFIRM_NEGATIVE, ["AFFIRM", "NEGATIVE", "STANDBY"]),
    (RR.ROGER, ["ROGER", "STANDBY"]),
    (RR.YES, ["YES", "NO"]),
    (RR.NO, []),
    (RR.NOT_REQUIRED, []),
]


def test_the_response_table_covers_every_requirement_code():
    assert {rr for rr, _ in RESPONSE_TABLE} == set(RR)


@pytest.mark.parametrize("rr, expected", RESPONSE_TABLE, ids=[rr.name for rr, _ in RESPONSE_TABLE])
def test_the_responses_offered_for_each_requirement_code(logger, rr, expected):
    """TODOS item 22: "Y" once offered only YES, and "N" wrongly offered NO."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 9, "CONFIRM SQUAWK", rr=rr))

    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (bool(expected), expected)
