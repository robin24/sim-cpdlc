"""Tests for polling-rate decisions."""

import logging

import pytest

from tests.support import FakeConnectionManager, inline_worker, uplink
from hoppie_connector import CpdlcResponseRequirement as RR

from src.controller.polling_controller import PollingController
from src.model.connection_manager import PollResult, UnreadableMessage
from src.controller.link_state import LinkState
from src.model.message_manager import CPDLC_RESPONSES


def controller(logger):
    return PollingController(logger, connection_manager=None, worker=inline_worker(logger))


def build(logger, connection, message_callback=None, **kwargs):
    """A controller wired to an inline worker.

    Returns:
        tuple: (poller, worker)
    """
    worker = inline_worker(logger)
    poller = PollingController(logger, connection, message_callback, worker=worker, **kwargs)
    return poller, worker


def tick(poller, worker):
    """Run one timer tick the way wx would: the one-shot has already stopped,
    the poll runs on the worker, and its result comes back to the controller."""
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)
    worker.run_pending()


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
    poller, _ = build(logger, FakeConnectionManager())
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
        return PollResult(ok=True, messages=["UPLINK"])


def test_a_poll_that_raises_still_schedules_the_next_one(logger, frame):
    """The timer is one-shot, so a tick that dies without rescheduling ends
    polling for the session while the status bar still reads Connected."""
    connection = RaisingConnection()

    def explode(_message):
        raise RuntimeError("SimConnect went away")

    poller, worker = build(logger, connection, explode)
    poller.start(frame)
    poller.poll_timer.Stop()

    with pytest.raises(RuntimeError):
        poller.on_poll_timer(None)
        worker.run_pending()

    assert poller.is_running() is True
    assert connection.polls == 1


def test_a_dropped_message_is_logged_before_it_propagates(logger, frame, caplog):
    """app.spec builds with console=False, so the log file is the only place
    a callback failure can ever surface. Without a log record here, the pilot
    just loses the message with no evidence anywhere it arrived.
    """
    # The shared `logger` fixture disables propagation so tests stay silent;
    # caplog listens on the root logger by default, so its handler has to be
    # attached here directly to see records from this logger at all.
    connection = RaisingConnection()

    def explode(_message):
        raise RuntimeError("SimConnect went away")

    poller, worker = build(logger, connection, explode)
    poller.start(frame)
    poller.poll_timer.Stop()

    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.addHandler(caplog.handler)
        with pytest.raises(RuntimeError):
            poller.on_poll_timer(None)
            worker.run_pending()

    assert "SimConnect went away" in caplog.text


class IdleConnection:
    """Connected, with nothing to report."""

    def is_connected(self):
        return True


def test_repeated_activity_does_not_defer_a_pending_poll(logger, frame):
    """Answering uplinks faster than the active interval used to restart the
    countdown every time, so the poll that would fetch the reply never ran."""
    poller, _ = build(logger, IdleConnection())
    poller.start(frame)

    poller.set_active_polling()
    deadline = poller._next_poll_at

    for _ in range(5):
        poller.set_active_polling()

    assert poller._next_poll_at == deadline


def test_an_idle_poll_is_pulled_forward_to_the_active_rate(logger, frame):
    """The point of active mode is a faster reply, so a poll a minute away has
    to come forward when the pilot sends something."""
    poller, _ = build(logger, IdleConnection())
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
        return PollResult(ok=True, messages=[self.message])


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

    poller, worker = build(logger, ClearanceConnection(message))
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
    worker.run_pending()

    assert len(schedule_calls) == 1
    assert poller.is_active_mode() is True
    assert poller.poll_timer.GetInterval() == poller.active_poll_interval


# --- link state and back-off --------------------------------------------------


class ScriptedConnection:
    """Connected; serves a scripted sequence of poll results, then clean polls."""

    def __init__(self, *results):
        self.results = list(results)
        self.polls = 0

    def is_connected(self):
        return True

    def poll(self):
        self.polls += 1
        return self.results.pop(0) if self.results else PollResult(ok=True)


def failed(count, reason="timed out", fatal=False):
    return PollResult(ok=False, reason=reason, fatal=fatal, failures=count)


def test_three_failed_polls_lose_the_link_and_start_the_back_off_ladder(logger, frame):
    """The Jul 17 outage in the maintainer's log lasted six minutes and cleared
    by itself; the old controller would have stopped polling after two."""
    statuses = []
    frame.SetStatusText = statuses.append
    transitions = []
    poller, worker = build(
        logger,
        ScriptedConnection(*[failed(count) for count in range(1, 8)]),
        link_callback=lambda old, new, reason: transitions.append((old, new)),
    )
    poller.start(frame)

    intervals = []
    for _ in range(7):
        tick(poller, worker)
        intervals.append(poller.poll_timer.GetInterval())

    assert all(45000 <= interval <= 75000 for interval in intervals[:2])
    assert intervals[2:] == [20000, 60000, 120000, 300000, 300000]
    assert transitions == [
        (LinkState.CONNECTED, LinkState.DEGRADED),
        (LinkState.DEGRADED, LinkState.LOST),
    ]
    assert statuses[:3] == [
        "Connection problem (1/3) - retrying...",
        "Connection problem (2/3) - retrying...",
        "Connection lost - retrying in 20 s",
    ]
    assert statuses[-1] == "Connection lost - retrying in 300 s"
    assert poller.is_running() is True


def test_a_successful_poll_restores_a_lost_link(logger, frame):
    statuses = []
    frame.SetStatusText = statuses.append
    transitions = []
    poller, worker = build(
        logger,
        ScriptedConnection(failed(1), failed(2), failed(3)),
        link_callback=lambda old, new, reason: transitions.append((old, new)),
    )
    poller.start(frame)

    for _ in range(4):
        tick(poller, worker)

    assert transitions[-1] == (LinkState.LOST, LinkState.CONNECTED)
    assert statuses[-1] == "Connection restored."
    assert 45000 <= poller.poll_timer.GetInterval() <= 75000
    assert poller.is_running() is True


def test_a_rejected_logon_code_stops_polling_for_good(logger, frame):
    transitions = []
    poller, worker = build(
        logger,
        ScriptedConnection(failed(1, "invalid logon code", fatal=True)),
        link_callback=lambda old, new, reason: transitions.append((old, new, reason)),
    )
    poller.start(frame)

    tick(poller, worker)

    assert transitions == [(LinkState.CONNECTED, LinkState.FATAL, "invalid logon code")]
    assert poller.is_running() is False


def test_activity_does_not_shorten_the_back_off_while_the_link_is_lost(logger, frame):
    """Restarting the pending poll would push it back by a whole rung: with
    250 s of a 300 s wait elapsed, a send would make it 300 s again."""
    # A bare wx.Frame has no status bar; the DEGRADED/LOST ticks below reach
    # _set_status(), which would otherwise raise wxAssertionError.
    frame.SetStatusText = lambda text: None
    poller, worker = build(
        logger, ScriptedConnection(*[failed(count) for count in range(1, 6)])
    )
    poller.start(frame)
    for _ in range(5):
        tick(poller, worker)
    deadline = poller._next_poll_at
    assert poller.poll_timer.GetInterval() == 120000

    poller.set_active_polling()

    assert poller._next_poll_at == deadline


def test_a_failing_callback_does_not_lose_the_rest_of_the_batch(logger, frame):
    """The server has already marked the whole batch relayed."""
    delivered = []

    def callback(message):
        delivered.append(message)
        if message == "FIRST":
            raise RuntimeError("boom")

    poller, worker = build(
        logger, ScriptedConnection(PollResult(ok=True, messages=["FIRST", "SECOND"])), callback
    )
    poller.start(frame)

    with pytest.raises(RuntimeError):
        tick(poller, worker)

    assert delivered == ["FIRST", "SECOND"]
    assert poller.is_running() is True


def test_unreadable_uplinks_reach_their_own_callback(logger, frame):
    unreadable = [UnreadableMessage("EDGG", "/data2/6//R/QNH 1013 / TRL 70")]
    received = []
    poller, worker = build(
        logger,
        ScriptedConnection(PollResult(ok=True, unreadable=unreadable)),
        unreadable_callback=received.extend,
    )
    poller.start(frame)

    tick(poller, worker)

    assert received == unreadable


def test_start_forgets_the_previous_sessions_link_state(logger, frame):
    # A bare wx.Frame has no status bar; the DEGRADED/LOST ticks below reach
    # _set_status(), which would otherwise raise wxAssertionError.
    frame.SetStatusText = lambda text: None
    poller, worker = build(logger, ScriptedConnection(failed(1), failed(2), failed(3)))
    poller.start(frame)
    for _ in range(3):
        tick(poller, worker)
    poller.stop()

    poller.start(frame)

    assert poller.link.state == LinkState.CONNECTED
    assert 45000 <= poller.poll_timer.GetInterval() <= 75000


def test_a_failing_link_callback_does_not_lose_the_batch(logger, frame):
    """The link callback reaches into the window; a failure there must not
    cost the messages the server has already marked relayed."""
    # A bare wx.Frame has no status bar; the restore transition below reaches
    # _set_status(), which would otherwise raise wxAssertionError.
    frame.SetStatusText = lambda text: None
    delivered = []

    def link_callback(old, new, reason):
        # Only the restore transition is under test here; raising
        # unconditionally would also blow up the arrange step below, which
        # goes through the very same (unwrapped) LinkState.record_poll().
        if new == LinkState.CONNECTED:
            raise RuntimeError("list control gone")

    poller, worker = build(
        logger,
        ScriptedConnection(PollResult(ok=True, messages=["CLEARANCE"])),
        delivered.append,
        link_callback=link_callback,
    )
    poller.start(frame)
    poller.link.record_poll(failed(3))  # already lost, so the clean poll is a transition

    with pytest.raises(RuntimeError, match="list control gone"):
        tick(poller, worker)

    assert delivered == ["CLEARANCE"]
    assert poller.is_running() is True


# --- the tick callback --------------------------------------------------------


def test_the_tick_callback_runs_after_every_poll_even_a_failed_one(logger, frame):
    """The window gives up on an unanswered logon from here, and an outage
    must not stop that clock."""
    # A bare wx.Frame has no status bar; the failed poll reaches _set_status().
    frame.SetStatusText = lambda text: None
    ticks = []
    poller, worker = build(
        logger, ScriptedConnection(failed(1)), tick_callback=lambda: ticks.append(1)
    )
    poller.start(frame)

    tick(poller, worker)
    tick(poller, worker)

    assert len(ticks) == 2


def test_the_tick_callback_runs_after_the_batch_is_delivered(logger, frame):
    order = []
    poller, worker = build(
        logger,
        ScriptedConnection(PollResult(ok=True, messages=["CLEARANCE"])),
        order.append,
        tick_callback=lambda: order.append("tick"),
    )
    poller.start(frame)

    tick(poller, worker)

    assert order == ["CLEARANCE", "tick"]


def test_a_raising_tick_callback_still_schedules_the_next_poll(logger, frame, caplog):
    def tick_callback():
        raise RuntimeError("status bar gone")

    poller, worker = build(logger, ScriptedConnection(), tick_callback=tick_callback)
    poller.start(frame)

    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.addHandler(caplog.handler)
        with pytest.raises(RuntimeError, match="status bar gone"):
            tick(poller, worker)

    assert "Error in tick callback" in caplog.text
    assert poller.is_running() is True


def test_the_tick_callback_is_skipped_on_the_tick_that_ends_the_session(logger, frame):
    """A rejected logon code tears the session down inside the tick; the
    housekeeping that follows a normal tick has nothing left to work on."""
    ticks = []
    poller, worker = build(
        logger,
        ScriptedConnection(failed(1, "invalid logon code", fatal=True)),
        tick_callback=lambda: ticks.append(1),
    )
    poller.start(frame)

    tick(poller, worker)

    assert ticks == []
    assert poller.is_running() is False


# --- the worker ---------------------------------------------------------------


def test_a_poll_runs_on_the_worker_not_in_the_timer_handler(logger, frame):
    """The GUI thread submits the poll and gets on with the event loop; the
    result comes back through the worker."""
    connection = ScriptedConnection(PollResult(ok=True, messages=["CLEARANCE"]))
    delivered = []
    poller, worker = build(logger, connection, delivered.append)
    poller.start(frame)
    poller.poll_timer.Stop()

    poller.on_poll_timer(None)

    assert (connection.polls, delivered, worker.pending()) == (0, [], 1)

    worker.run_pending()

    assert (connection.polls, delivered) == (1, ["CLEARANCE"])
    assert poller.is_running() is True


def test_a_tick_while_a_poll_is_out_does_not_queue_a_second_poll(logger, frame):
    """A slow server answers in its own time; stacking polls behind it would
    only add load and confuse the link state. The tick still re-arms the timer."""
    poller, worker = build(logger, ScriptedConnection())
    poller.start(frame)
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)

    poller.poll_timer.Stop()
    poller.on_poll_timer(None)

    assert worker.pending() == 1
    assert poller.is_running() is True


def test_a_result_arriving_after_stop_is_ignored(logger, frame):
    """Disconnect while a poll is out: its answer must neither restart the
    timer nor reach the window."""
    delivered = []
    poller, worker = build(
        logger, ScriptedConnection(PollResult(ok=True, messages=["LATE"])), delivered.append
    )
    poller.start(frame)
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)
    poller.stop()

    worker.run_pending()

    assert delivered == []
    assert poller.is_running() is False


class BrokenConnection:
    """A poll() that raises, which the real manager never does."""

    def is_connected(self):
        return True

    def poll(self):
        raise KeyError("cnx")


def test_a_poll_job_that_raises_counts_as_a_failed_poll(logger, frame):
    """connection_manager.poll() never raises, but a bug there must degrade
    the link, not stop polling."""
    frame.SetStatusText = lambda text: None
    poller, worker = build(logger, BrokenConnection())
    poller.start(frame)

    tick(poller, worker)

    assert poller.link.state == LinkState.DEGRADED
    assert poller.is_running() is True
