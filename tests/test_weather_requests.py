"""The manual weather request through the window: the dialog closes at once,
the report or the error arrives from the worker."""

import wx

import src.gui.main_window as mw
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeConnectionManager,
    inline_worker,
    make_main_window,
)


class FakeWeatherDialog:
    """Stands in for WeatherDialog: answers OK with fixed details, never shows."""

    details = ("EGLL", "metar", True)

    def __init__(self, parent, is_watched=None):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_weather_details(self):
        return self.details

    def Destroy(self):
        pass


def build(logger, monkeypatch, details=("EGLL", "metar", True), connection=None):
    monkeypatch.setattr(mw, "WeatherDialog", FakeWeatherDialog)
    monkeypatch.setattr(FakeWeatherDialog, "details", details)
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock(), worker=inline_worker(logger))
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def test_the_report_arrives_after_the_dialog_has_closed(logger, monkeypatch):
    window, manager = build(logger, monkeypatch)

    window.on_weather_request(None)

    assert window.status_texts == ["Requesting METAR for EGLL..."]
    assert rows(manager) == []

    window.worker.run_pending()

    assert rows(manager)[0][0] == "METAR"
    assert "EGLL REPORT FOR metar" in rows(manager)[0][1]
    assert window.status_texts[-1] == "METAR for EGLL received."


def test_a_report_is_only_watched_once_it_has_been_fetched(logger, monkeypatch):
    window, manager = build(logger, monkeypatch)

    window.on_weather_request(None)
    assert window.weather_monitor.subscriptions == {}

    window.worker.run_pending()

    assert window.weather_monitor.subscriptions == {("EGLL", "metar"): "EGLL REPORT FOR metar"}
    assert rows(manager)[-1] == ("SYSTEM", "Now watching METAR EGLL for changes")


def test_unchecking_the_box_stops_updates_before_the_request_goes_out(logger, monkeypatch):
    window, manager = build(logger, monkeypatch, details=("EGLL", "metar", False))
    window.weather_monitor.subscribe("EGLL", "metar")

    window.on_weather_request(None)

    assert window.weather_monitor.subscriptions == {}
    assert rows(manager) == [("SYSTEM", "Stopped automatic updates for METAR EGLL")]


def test_a_failed_request_is_reported_when_it_fails(logger, monkeypatch, message_boxes):
    from hoppie_connector import HoppieError

    window, manager = build(
        logger, monkeypatch, connection=FakeConnectionManager(raise_with=HoppieError("no data"))
    )

    window.on_weather_request(None)
    assert message_boxes.calls == []

    window.worker.run_pending()

    assert message_boxes.captions == ["Error"]
    assert "Failed to retrieve METAR for EGLL: no data." in message_boxes.calls[0][0]
    assert window.status_texts[-1] == "Could not retrieve METAR for EGLL."
    assert window.weather_monitor.subscriptions == {}
