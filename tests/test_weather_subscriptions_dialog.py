"""The Automatic Weather Updates dialog: what it lists, and how a stop is routed.

The dialog runs a modal loop while the monitor keeps working underneath it,
so a report dropped or checked meanwhile has to show up without reopening it.
Stopping goes through the window, so the SYSTEM row and the status text read
the same as from the report's context menu.
"""

import pytest
import wx

from src.gui.dialogs import WeatherSubscriptionsDialog
from src.model.weather_monitor import MAX_CONSECUTIVE_ERRORS, WeatherMonitor
from src.utils.weather_parsing import report_type_label
from tests.support import inline_worker

METAR = report_type_label("metar")
ATIS = report_type_label("vatatis")


class Connection:
    """Always connected; never asked for anything in these tests."""

    def is_connected(self):
        return True

    def send_info_request(self, info_type, icao):
        return f"{icao} REPORT"


@pytest.fixture
def monitor(logger, frame):
    """A monitor watching two reports, listed EGKK first (sorted by ICAO)."""
    monitor = WeatherMonitor(logger, Connection(), worker=inline_worker(logger))
    monitor._parent = frame
    monitor.subscribe("EGKK", "metar")
    monitor.subscribe("EGLL", "vatatis")
    return monitor


@pytest.fixture
def stopped():
    """What the window's stop helper was asked to stop, in order."""
    return []


@pytest.fixture
def subscriptions(dialog, monitor, stopped):
    return dialog(
        WeatherSubscriptionsDialog,
        monitor,
        lambda icao, info_type: stopped.append((icao, info_type)),
    )


def entries(dlg):
    return [dlg.subscription_list.GetString(i) for i in range(dlg.subscription_list.GetCount())]


def test_the_list_names_every_watched_report(subscriptions):
    assert entries(subscriptions) == [
        f"{METAR} EGKK, not yet checked",
        f"{ATIS} EGLL, not yet checked",
    ]
    assert subscriptions.subscription_list.GetSelection() == 0


def test_stop_updating_hands_the_selected_report_to_the_window(subscriptions, stopped, monitor):
    subscriptions.subscription_list.SetSelection(1)

    subscriptions.on_stop(None)

    assert stopped == [("EGLL", "vatatis")]
    # The dialog announces nothing itself: the window's helper unsubscribes
    # and says so, and the list follows the monitor from there.
    assert monitor.count() == 2


def test_the_list_follows_the_monitor(subscriptions, monitor):
    monitor.unsubscribe("EGLL", "vatatis")
    assert entries(subscriptions) == [f"{METAR} EGKK, not yet checked"]

    monitor.unsubscribe("EGKK", "metar")

    assert entries(subscriptions) == []
    assert subscriptions.stop_button.IsEnabled() is False
    assert subscriptions.stop_all_button.IsEnabled() is False
    assert subscriptions.check_button.IsEnabled() is False


def test_a_report_dropped_after_repeated_failures_leaves_the_list(subscriptions, monitor):
    """It used to stay listed until the dialog was reopened."""
    for _ in range(MAX_CONSECUTIVE_ERRORS):
        monitor._on_result("EGLL", "vatatis", None, "timeout")

    assert entries(subscriptions) == [f"{METAR} EGKK, not yet checked"]


def test_a_checked_report_shows_when_it_was_checked(subscriptions, monitor):
    monitor._on_result("EGKK", "metar", "EGKK 261150Z 24010KT Q1013", None)

    assert entries(subscriptions)[0].startswith(f"{METAR} EGKK, last checked ")


def test_the_selection_survives_a_refresh(subscriptions, monitor):
    subscriptions.subscription_list.SetSelection(1)

    monitor._on_result("EGKK", "metar", "EGKK 261150Z 24010KT Q1013", None)

    assert subscriptions.subscription_list.GetSelection() == 1


def test_stop_all_asks_first_and_then_hands_over_every_report(subscriptions, stopped, message_boxes):
    message_boxes.answer = wx.YES

    subscriptions.on_stop_all(None)

    assert message_boxes.captions == ["Confirm"]
    assert stopped == [("EGKK", "metar"), ("EGLL", "vatatis")]


def test_stop_all_declined_stops_nothing(subscriptions, stopped, message_boxes):
    message_boxes.answer = wx.NO

    subscriptions.on_stop_all(None)

    assert stopped == []


def test_a_closed_dialog_stops_listening(frame, monitor):
    dlg = WeatherSubscriptionsDialog(frame, monitor, lambda icao, info_type: None)
    assert len(monitor._listeners) == 1

    dlg.Destroy()

    assert monitor._listeners == []
