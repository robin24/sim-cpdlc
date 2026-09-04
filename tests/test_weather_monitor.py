"""Tests for automatic weather updates: change detection and timer lifecycle.

Neither Hoppie nor SayIntentions pushes weather, so an automatic update is a
re-request on a timer. What makes it usable is that a report is only announced
when it has actually changed, so these tests drive the result path directly —
which is what the worker thread posts back through wx.CallAfter.
"""

import pytest
from hoppie_connector import HoppieError

from src.model.weather_monitor import MAX_CONSECUTIVE_ERRORS, WeatherMonitor
from tests.support import inline_worker


class ScriptedConnection:
    """Serves a fixed sequence of reports, repeating the last one forever."""

    def __init__(self, reports=("unused",)):
        self.reports = list(reports)
        self.calls = 0

    def is_connected(self):
        return True

    def send_info_request(self, info_type, icao):
        value = self.reports[min(self.calls, len(self.reports) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def deliver(monitor, connection, icao="EGLL", info_type="vatatis"):
    """Hand the monitor the next scripted report, as the worker thread would."""
    monitor._on_result(
        icao, info_type, connection.send_info_request(info_type, icao), None
    )


@pytest.fixture
def atis(logger, frame):
    connection = ScriptedConnection(
        [
            "EGLL ATIS INFORMATION K RWY 27R",
            "EGLL ATIS INFO KILO RUNWAY 27R",  # reworded, same letter
            "EGLL ATIS INFORMATION L RWY 09L",  # new letter
        ]
    )
    announced = []
    monitor = WeatherMonitor(
        logger,
        connection,
        on_update=lambda subscription, text, description: announced.append(
            description
        ),
        worker=inline_worker(logger),
    )
    monitor._parent = frame
    monitor.subscribe("EGLL", "vatatis")
    return monitor, connection, announced


@pytest.fixture
def metar(logger, frame):
    announced = []
    monitor = WeatherMonitor(
        logger,
        ScriptedConnection(),
        on_update=lambda subscription, text, description: announced.append(
            description
        ),
        worker=inline_worker(logger),
    )
    monitor._parent = frame
    monitor.subscribe("EGLL", "metar", initial_text="EGLL 261150Z 24010KT Q1013")
    return monitor, announced


# --- change detection ---------------------------------------------------------


def test_the_first_report_is_announced(atis):
    monitor, connection, announced = atis

    deliver(monitor, connection)

    assert len(announced) == 1


def test_a_reworded_atis_with_the_same_letter_stays_silent(atis):
    """Being interrupted for an unchanged ATIS is worse than not being told."""
    monitor, connection, announced = atis

    deliver(monitor, connection)
    deliver(monitor, connection)

    assert len(announced) == 1


def test_a_new_information_letter_is_announced(atis):
    monitor, connection, announced = atis

    for _ in range(3):
        deliver(monitor, connection)

    assert len(announced) == 2
    assert announced[-1] == "ATIS EGLL information L"


def test_a_metar_matching_the_one_already_shown_stays_silent(metar):
    """Subscribing from a report just requested must not immediately repeat it,
    and whitespace alone is not a change."""
    monitor, announced = metar

    monitor._on_result("EGLL", "metar", "EGLL 261150Z  24010KT  Q1013", None)

    assert announced == []


def test_an_amended_metar_is_announced(metar):
    """METAR carries no information letter, so the text itself is compared."""
    monitor, announced = metar

    monitor._on_result("EGLL", "metar", "EGLL 261220Z 26015KT Q1012", None)

    assert len(announced) == 1


# --- failure handling ---------------------------------------------------------


def test_repeated_failures_drop_the_subscription(logger, frame):
    """A mistyped ICAO would otherwise retry for the rest of the session."""
    errors = []
    monitor = WeatherMonitor(
        logger,
        ScriptedConnection(),
        on_error=lambda subscription, error: errors.append(error),
        worker=inline_worker(logger),
    )
    monitor._parent = frame
    monitor.subscribe("ZZZZ", "metar")

    for _ in range(5):
        monitor._on_result("ZZZZ", "metar", None, "no data")

    assert monitor.count() == 0
    assert len(errors) == 1


# --- subscription lifecycle ---------------------------------------------------


def test_unsubscribing_stops_the_updates(atis):
    monitor, _, _ = atis

    assert monitor.unsubscribe("EGLL", "vatatis") is True
    assert monitor.count() == 0


def test_unsubscribing_twice_is_a_no_op(atis):
    monitor, _, _ = atis
    monitor.unsubscribe("EGLL", "vatatis")

    assert monitor.unsubscribe("EGLL", "vatatis") is False


def test_the_monitor_can_be_stopped_and_started_again(logger, frame):
    """Disconnecting stops the timer, so reconnecting has to bring it back."""
    monitor = WeatherMonitor(
        logger, ScriptedConnection(), interval_ms=60000, worker=inline_worker(logger)
    )

    monitor.start(frame)
    assert monitor._timer.IsRunning()

    monitor.stop()
    assert not monitor._timer.IsRunning()

    monitor.start(frame)
    assert monitor._timer.IsRunning()
    assert monitor._shutting_down is False

    monitor.shutdown()
    assert monitor._timer is None


# --- the update cycle runs on the worker --------------------------------------


def build(logger, frame, connection, **callbacks):
    worker = inline_worker(logger)
    monitor = WeatherMonitor(logger, connection, worker=worker, **callbacks)
    monitor.start(frame)
    return monitor, worker


def test_check_now_says_a_cycle_started(logger, frame):
    """The dialog tells the user reports are being checked, so it needs to know
    whether that is true."""
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))
    monitor.subscribe("EGLL", "metar")

    assert monitor.check_now() is True


def test_check_now_says_nothing_started_while_stopped(logger, frame):
    """Disconnecting stops the monitor but leaves the dialog reachable. Saying
    a check is under way when none is would be worse than saying nothing."""
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))
    monitor.subscribe("EGLL", "metar")
    monitor.stop()

    assert monitor.check_now() is False


def test_check_now_says_nothing_started_with_no_subscriptions(logger, frame):
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))

    assert monitor.check_now() is False


def test_a_cycle_asks_for_every_subscription_through_the_worker(logger, frame):
    """One inforeq job per subscription; the worker spaces them out. A second
    cycle waits until the first has reported in full."""
    connection = ScriptedConnection(["EGLL 1150Z"])
    monitor, worker = build(logger, frame, connection)
    monitor.subscribe("EGLL", "metar")
    monitor.subscribe("EDDF", "metar")

    assert monitor.check_now() is True
    assert worker.pending() == 2
    assert monitor.check_now() is False

    worker.run_pending()

    assert connection.calls == 2
    assert monitor.check_now() is True


def test_results_of_a_stopped_cycle_are_ignored(logger, frame):
    """Disconnecting stops the monitor while a cycle is out; its answers must
    neither announce anything nor count against a subscription."""
    errors = []
    monitor, worker = build(
        logger,
        frame,
        ScriptedConnection([HoppieError("no data")]),
        on_error=lambda subscription, error: errors.append(error),
    )
    monitor.subscribe("EGLL", "metar")
    monitor.check_now()
    monitor.stop()

    worker.run_pending()

    assert monitor.get_subscriptions()[0].error_count == 0
    assert errors == []


def test_a_stopped_cycle_makes_no_more_requests(logger, frame):
    """On a lost link the monitor is stopped so it does not hammer the dead
    link; the jobs already queued must not do so either."""
    connection = ScriptedConnection(["EGLL 1150Z"])
    monitor, worker = build(logger, frame, connection)
    monitor.subscribe("EGLL", "metar")
    monitor.subscribe("EDDF", "metar")
    monitor.check_now()
    monitor.stop()

    worker.run_pending()

    assert connection.calls == 0


def test_a_failed_fetch_counts_against_the_subscription(logger, frame):
    monitor, worker = build(logger, frame, ScriptedConnection([HoppieError("no data")]))
    monitor.subscribe("EGLL", "metar")
    monitor.check_now()

    worker.run_pending()

    assert monitor.get_subscriptions()[0].error_count == 1


# --- change listeners ----------------------------------------------------------


def test_listeners_hear_the_subscription_list_change(logger, frame):
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    counts = []
    stop_listening = monitor.subscribe_to_changes(lambda: counts.append(monitor.count()))

    monitor.subscribe("EGLL", "vatatis")
    monitor.subscribe("EGLL", "vatatis")  # already watched: nothing changed
    monitor.unsubscribe("EGLL", "vatatis")
    monitor.unsubscribe("EGLL", "vatatis")  # already gone: nothing changed
    monitor.subscribe("EGKK", "metar")
    monitor.clear()
    monitor.clear()  # already empty: nothing changed

    assert counts == [1, 0, 1, 0]

    stop_listening()
    stop_listening()  # a second call is harmless
    monitor.subscribe("EGLL", "vatatis")
    assert counts == [1, 0, 1, 0]


def test_listeners_hear_a_successful_check_and_a_dropped_subscription(logger, frame):
    """The dialog shows "last checked" and lists dropped reports until told
    otherwise, so both events have to reach it. Failed checks short of the
    limit change nothing it shows."""
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    monitor.subscribe("EGLL", "metar")
    changes = []
    monitor.subscribe_to_changes(lambda: changes.append(monitor.count()))

    monitor._on_result("EGLL", "metar", "EGLL 261150Z 24010KT Q1013", None)
    assert changes == [1]

    for _ in range(MAX_CONSECUTIVE_ERRORS - 1):
        monitor._on_result("EGLL", "metar", None, "timeout")
    assert changes == [1]

    monitor._on_result("EGLL", "metar", None, "timeout")
    assert changes == [1, 0]


def test_a_listener_that_raises_is_dropped_and_the_others_still_run(logger, frame):
    """A dialog wx has already destroyed raises from its list; that must not
    break the update cycle for the rest of the session. It is dropped after
    the first raise, so it is not called again."""
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    heard = []
    raised = []

    def broken():
        raised.append("raised")
        raise RuntimeError("wrapped C++ object has been deleted")

    monitor.subscribe_to_changes(broken)
    monitor.subscribe_to_changes(lambda: heard.append(monitor.count()))

    monitor.subscribe("EGLL", "vatatis")
    monitor.unsubscribe("EGLL", "vatatis")

    assert heard == [1, 0]
    assert raised == ["raised"]


def test_shutdown_drops_listeners_so_a_later_subscribe_does_not_reach_them(logger, frame):
    """A listener must not outlive the monitor's data: shutdown() is the end
    of the session, and no dialog can still be open to receive it."""
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    heard = []
    monitor.subscribe_to_changes(lambda: heard.append(monitor.count()))

    monitor.shutdown()
    monitor.subscribe("EGLL", "metar")

    assert heard == []
