"""Tests for polling-rate decisions."""

import pytest

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


class RaisingConnection:
    """Polls successfully but hands back a message the callback will choke on."""

    def __init__(self):
        self.polls = 0

    def is_connected(self):
        return True

    def poll(self):
        self.polls += 1
        return ["UPLINK"], None

    def poll_failed(self):
        return False

    def should_attempt_reconnection(self):
        return False


def test_a_poll_that_raises_still_schedules_the_next_one(logger, frame):
    """The timer is one-shot, so a tick that dies without rescheduling ends
    polling for the session while the status bar still reads Connected."""
    connection = RaisingConnection()

    def explode(_message):
        raise RuntimeError("SimConnect went away")

    poller = PollingController(logger, connection, explode)
    poller.start(frame)
    poller.poll_timer.Stop()

    with pytest.raises(RuntimeError):
        poller.on_poll_timer(None)

    assert poller.is_running() is True


class IdleConnection:
    """Connected, with nothing to report."""

    def is_connected(self):
        return True


def test_repeated_activity_does_not_defer_a_pending_poll(logger, frame):
    """Answering uplinks faster than the active interval used to restart the
    countdown every time, so the poll that would fetch the reply never ran."""
    poller = PollingController(logger, IdleConnection(), None)
    poller.start(frame)

    poller.set_active_polling()
    deadline = poller._next_poll_at

    for _ in range(5):
        poller.set_active_polling()

    assert poller._next_poll_at == deadline


def test_an_idle_poll_is_pulled_forward_to_the_active_rate(logger, frame):
    """The point of active mode is a faster reply, so a poll a minute away has
    to come forward when the pilot sends something."""
    poller = PollingController(logger, IdleConnection(), None)
    poller.start(frame)
    idle_deadline = poller._next_poll_at

    poller.set_active_polling()

    assert poller._next_poll_at < idle_deadline
    assert poller.poll_timer.GetInterval() == poller.active_poll_interval


class ClearanceConnection:
    """Connected, and hands back a clearance that should speed up polling."""

    def __init__(self, message):
        self.message = message

    def is_connected(self):
        return True

    def poll(self):
        return [self.message], None

    def poll_failed(self):
        return False

    def should_attempt_reconnection(self):
        return False


def test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once(logger, frame):
    """set_active_polling() is also called from inside on_poll_timer itself,
    when a message warrants faster polling. At that point the one-shot has
    just fired and reports IsRunning() == False - the platform quirk the
    `not self.is_running()` guard exists to handle. Without that guard, a
    message arriving mid-tick would have set_active_polling() schedule a
    poll of its own, and the tick's own finally block would schedule a
    second one on top of it.
    """
    message = uplink("LSAG", 1, "CLIMB TO AND MAINTAIN FL360", rr=RR.WILCO_UNABLE)
    assert controller(logger).should_increase_polling_rate(message) is True

    poller = PollingController(logger, ClearanceConnection(message))
    poller.start(frame)

    schedule_calls = []
    real_schedule_next = poller._schedule_next

    def counting_schedule_next():
        schedule_calls.append(None)
        real_schedule_next()

    poller._schedule_next = counting_schedule_next

    # Simulate being inside the timer's own firing handler, where a one-shot
    # wx.Timer reports IsRunning() == False.
    poller.poll_timer.Stop()

    poller.on_poll_timer(None)

    assert len(schedule_calls) == 1
    assert poller.is_active_mode() is True
    assert poller.poll_timer.GetInterval() == poller.active_poll_interval
