"""Tests for polling-rate decisions."""

from conftest import FakeConnectionManager, uplink
from hoppie_connector import CpdlcResponseRequirement as RR

from src.controller.polling_controller import PollingController
from src.model.message_manager import CPDLC_RESPONSES


def controller(logger):
    return PollingController(logger, connection_manager=None)


def test_a_bare_acknowledgement_does_not_speed_up_polling(logger):
    """Every response the client can send counts as an acknowledgement."""
    poller = controller(logger)

    for response in sorted(CPDLC_RESPONSES):
        message = uplink("LSAG", 1, response, rr=RR.NO)
        assert poller.should_increase_polling_rate(message) is False, response


def test_a_clearance_speeds_up_polling(logger):
    poller = controller(logger)

    message = uplink("LSAG", 1, "CLIMB TO AND MAINTAIN FL360")

    assert poller.should_increase_polling_rate(message) is True


# --- polling rate -------------------------------------------------------------


def test_idle_polls_are_spread_across_the_band_hoppie_asks_for(logger):
    """Hoppie asks for a poll "once between every 45 and 75 seconds, randomly
    timed so that the average server load is stable". A fixed 60 second repeat
    made each client a steady beat rather than a spread one.
    """
    poller = controller(logger)

    draws = [poller.next_interval() for _ in range(2000)]

    assert all(45000 <= draw <= 75000 for draw in draws)
    assert len(set(draws)) > 100, "a fixed interval would draw the same value"
    assert 57000 < sum(draws) / len(draws) < 63000


def test_active_mode_polls_at_the_fastest_rate_permitted(logger):
    poller = controller(logger)

    poller.set_active_polling()

    assert poller.is_active_mode() is True
    assert {poller.next_interval() for _ in range(20)} == {20000}


def test_a_quiet_period_returns_to_the_randomised_band(logger):
    poller = controller(logger)
    poller.set_active_polling()

    poller.last_activity_time -= 400  # seconds of quiet
    poller.check_polling_timeout()

    assert poller.is_active_mode() is False
    assert 45000 <= poller.next_interval() <= 75000


def test_a_stopped_poller_does_not_reschedule_itself(logger, frame):
    """Each tick arranges the next one, so a stop that failed to take would
    leave the timer running for the rest of the session.
    """
    poller = PollingController(logger, FakeConnectionManager())
    poller.start(frame)

    poller.stop()
    poller._schedule_next()

    assert poller.is_running() is False
