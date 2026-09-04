"""Tests for the validation the request dialogs apply before they will submit.

The OK button is the guard: a dialog that lets an incomplete request through
sends malformed text to a controller.
"""

import pytest
import wx

from src.gui.dialogs import ConnectDialog, PDCDialog, WeatherDialog


@pytest.fixture
def dialog(frame):
    """Builds a dialog and destroys it, whatever the test does to it."""
    built = []

    def build(factory, *args, **kwargs):
        instance = factory(frame, *args, **kwargs)
        built.append(instance)
        return instance

    yield build
    for instance in built:
        instance.Destroy()


def _fire_auto_update_toggle(weather):
    """Check or uncheck the auto-update box the way a user actually does.

    Calling on_auto_update_toggled() directly would keep passing even if
    the Bind() that wires it to the checkbox were deleted, silently
    bringing back the reverting-checkbox bug the handler exists to prevent.
    """
    checkbox = weather.auto_update_checkbox
    event = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, checkbox.GetId())
    event.SetEventObject(checkbox)
    checkbox.GetEventHandler().ProcessEvent(event)


# --- weather ------------------------------------------------------------------


def test_a_weather_request_needs_a_full_icao_code(dialog):
    weather = dialog(WeatherDialog)

    weather.icao_text.SetValue("egl")
    assert weather.ok_button.IsEnabled() is False

    weather.icao_text.SetValue("egll")
    assert weather.ok_button.IsEnabled() is True


def test_a_weather_request_reports_the_code_in_upper_case(dialog):
    weather = dialog(WeatherDialog)

    weather.icao_text.SetValue("egll")

    assert weather.get_weather_details() == ("EGLL", "vatatis", False)


def test_checking_survives_a_correction_to_the_icao(dialog):
    """The check was silently reverted by the next keystroke, so a typo fixed
    after checking meant no subscription and nothing said about it."""
    weather = dialog(WeatherDialog, is_watched=lambda icao, kind: False)

    weather.icao_text.SetValue("EGKK")
    weather.auto_update_checkbox.SetValue(True)
    _fire_auto_update_toggle(weather)
    weather.icao_text.SetValue("EGLL")

    assert weather.get_weather_details() == ("EGLL", "vatatis", True)


def test_unchecking_survives_a_correction_to_the_icao(dialog):
    """Unchecking is how updates are stopped, so it has to stick too."""
    watched = {("EGLL", "vatatis"), ("EGKK", "vatatis")}
    weather = dialog(
        WeatherDialog, is_watched=lambda icao, kind: (icao, kind) in watched
    )

    weather.icao_text.SetValue("EGLL")
    assert weather.auto_update_checkbox.GetValue() is True

    weather.auto_update_checkbox.SetValue(False)
    _fire_auto_update_toggle(weather)
    weather.icao_text.SetValue("EGKK")

    assert weather.get_weather_details() == ("EGKK", "vatatis", False)


# --- SimBrief fills the Connect and PDC dialogs in after they open -------------


class RecordingFetch:
    """Stands in for MainWindow._fetch_simbrief: keeps the callback so the test can answer later."""

    def __init__(self, configured=True):
        self.configured = configured
        self.on_done = None

    def __call__(self, on_done):
        if not self.configured:
            return False
        self.on_done = on_done
        return True


def test_the_connect_dialog_opens_before_simbrief_answers(frame):
    """The fetch used to run inside the constructor, freezing the app for up
    to ten seconds before the dialog appeared."""
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    try:
        assert dialog.simbrief_status.GetLabel() == "Fetching SimBrief flight plan..."
        assert dialog.callsign_text.GetValue() == ""

        fetch.on_done({"atc": {"callsign": "BAW123"}})

        assert dialog.callsign_text.GetValue() == "BAW123"
        assert dialog.simbrief_status.GetLabel() == "Callsign taken from your SimBrief flight plan."
    finally:
        dialog.Destroy()


def test_a_failed_simbrief_fetch_is_shown_in_the_dialog_not_a_message_box(frame, message_boxes):
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    try:
        fetch.on_done(None)

        assert dialog.simbrief_status.GetLabel() == "Could not fetch flight plan from SimBrief."
        assert message_boxes.calls == []
    finally:
        dialog.Destroy()


def test_a_plan_without_a_callsign_is_told_apart_from_a_failed_fetch(frame):
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    try:
        fetch.on_done({"atc": {}})

        assert dialog.simbrief_status.GetLabel() == "Your SimBrief flight plan has no callsign."
        assert dialog.callsign_text.GetValue() == ""
    finally:
        dialog.Destroy()


def test_a_simbrief_answer_after_the_dialog_closed_is_ignored(frame):
    """The pilot may press OK or Cancel before SimBrief answers."""
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    dialog.Destroy()

    fetch.on_done({"atc": {"callsign": "BAW123"}})


def test_without_a_simbrief_id_the_connect_dialog_says_nothing(frame):
    dialog = ConnectDialog(frame, fetch_simbrief=RecordingFetch(configured=False))
    try:
        assert dialog.simbrief_status.GetLabel() == ""
    finally:
        dialog.Destroy()


def test_the_pdc_dialog_fills_its_fields_from_simbrief(frame):
    fetch = RecordingFetch()
    dialog = PDCDialog(frame, fetch_simbrief=fetch)
    try:
        assert dialog.simbrief_status.GetLabel() == "Fetching SimBrief flight plan..."

        fetch.on_done(
            {
                "origin": {"icao_code": "EGLL"},
                "destination": {"icao_code": "LIMC"},
                "aircraft": {"icao_code": "A339"},
            }
        )

        assert (
            dialog.origin_icao_text.GetValue(),
            dialog.destination_icao_text.GetValue(),
            dialog.aircraft_text.GetValue(),
        ) == ("EGLL", "LIMC", "A339")
        assert dialog.simbrief_status.GetLabel() == "Flight plan loaded from SimBrief."
    finally:
        dialog.Destroy()


def test_a_failed_simbrief_fetch_is_laid_out_in_the_pdc_dialog(frame):
    """The failure text is longer than the empty label the dialog was fitted
    around; without a re-layout it ran past the dialog's right edge."""
    fetch = RecordingFetch()
    dialog = PDCDialog(frame, fetch_simbrief=fetch)
    try:
        fetch.on_done(None)

        assert dialog.simbrief_status.GetLabel() == "Could not fetch flight plan from SimBrief."
        label_right = dialog.simbrief_status.GetPosition().x + dialog.simbrief_status.GetSize().width
        assert label_right <= dialog.GetClientSize().width
    finally:
        dialog.Destroy()


def test_a_flight_plan_without_the_fields_is_not_reported_as_loaded(frame):
    fetch = RecordingFetch()
    dialog = PDCDialog(frame, fetch_simbrief=fetch)
    try:
        fetch.on_done({"general": {}})

        assert dialog.simbrief_status.GetLabel() == "Could not read the flight plan from SimBrief."
        assert dialog.origin_icao_text.GetValue() == ""
    finally:
        dialog.Destroy()


def test_a_simbrief_answer_after_the_pdc_dialog_closed_is_ignored(frame):
    fetch = RecordingFetch()
    dialog = PDCDialog(frame, fetch_simbrief=fetch)
    dialog.Destroy()

    fetch.on_done({"origin": {"icao_code": "EGLL"}})
