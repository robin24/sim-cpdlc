"""Tests for automatic weather updates: change detection and timer lifecycle.

Neither Hoppie nor SayIntentions pushes weather, so an automatic update is a
re-request on a timer. What makes it usable is that a report is only announced
when it has actually changed, so these tests drive the result path directly —
which is what the worker thread posts back through wx.CallAfter.
"""

import pytest

from src.model.weather_monitor import WeatherMonitor


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
    monitor = WeatherMonitor(logger, ScriptedConnection(), interval_ms=60000)

    monitor.start(frame)
    assert monitor._timer.IsRunning()

    monitor.stop()
    assert not monitor._timer.IsRunning()

    monitor.start(frame)
    assert monitor._timer.IsRunning()
    assert monitor._shutting_down is False

    monitor.shutdown()
    assert monitor._timer is None


# --- reporting whether a cycle actually started -------------------------------


def test_check_now_says_a_cycle_started(logger, frame):
    """The dialog tells the user reports are being checked, so it needs to know
    whether that is true."""
    monitor = WeatherMonitor(logger, ScriptedConnection(["EGLL 1150Z"]))
    monitor.start(frame)
    monitor.subscribe("EGLL", "metar")

    assert monitor.check_now() is True


def test_check_now_says_nothing_started_while_stopped(logger, frame):
    """Disconnecting stops the monitor but leaves the dialog reachable. Saying
    a check is under way when none is would be worse than saying nothing."""
    monitor = WeatherMonitor(logger, ScriptedConnection(["EGLL 1150Z"]))
    monitor.start(frame)
    monitor.subscribe("EGLL", "metar")
    monitor.stop()

    assert monitor.check_now() is False


def test_check_now_says_nothing_started_with_no_subscriptions(logger, frame):
    monitor = WeatherMonitor(logger, ScriptedConnection(["EGLL 1150Z"]))
    monitor.start(frame)

    assert monitor.check_now() is False
