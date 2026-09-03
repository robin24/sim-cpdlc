"""Tests for message identity, acknowledgement state and response options."""

from tests.support import uplink
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

    needs_ack, responses = manager.needs_acknowledgement(contact, STATION)
    assert needs_ack is True
    assert responses == ["WILCO", "UNABLE", "STANDBY"]


def test_acknowledging_one_message_does_not_answer_the_other(logger):
    manager = MessageManager(logger)
    climb = manager.add_message(uplink(STATION, 53, "CLIMB TO AND MAINTAIN FL360"))
    manager.mark_acknowledged(climb, "WILCO")

    assert manager.needs_acknowledgement(climb, STATION) == (False, [])


def test_standby_leaves_the_message_answerable(logger):
    """The one behaviour that must not regress: STANDBY is not a final answer."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 7))

    manager.mark_acknowledged(message_id, "STANDBY")

    needs_ack, responses = manager.needs_acknowledgement(message_id, STATION)
    assert needs_ack is True
    assert responses == ["WILCO", "UNABLE", "STANDBY"]


def test_standby_is_recognised_regardless_of_case(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 7))

    manager.mark_acknowledged(message_id, "standby")

    assert manager.needs_acknowledgement(message_id, STATION)[0] is True


def test_a_message_from_another_station_offers_no_responses(logger):
    """After a handover the old station's messages are no longer answerable."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("EDYY", 4))

    assert manager.needs_acknowledgement(message_id, "EDGG") == (False, [])


def test_a_message_offers_no_responses_when_not_logged_on(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("EDYY", 4))

    assert manager.needs_acknowledgement(message_id, "") == (False, [])


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

    assert manager.needs_acknowledgement(message_id, STATION) == (
        True,
        ["ROGER", "STANDBY"],
    )


def test_a_message_needing_no_response_offers_none(logger):
    manager = MessageManager(logger)
    message_id = manager.add_message(
        uplink(STATION, 10, "LOGON ACCEPTED", rr=RR.NOT_REQUIRED)
    )

    assert manager.needs_acknowledgement(message_id, STATION) == (False, [])


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
