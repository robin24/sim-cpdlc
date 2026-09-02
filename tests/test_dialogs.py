"""Tests for the validation the request dialogs apply before they will submit.

The OK button is the guard: a dialog that lets an incomplete request through
sends malformed text to a controller.
"""

import pytest
import wx

from src.gui.dialogs import WeatherDialog


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
    weather = dialog(WeatherDialog, "metar")

    weather.icao_text.SetValue("egl")
    assert weather.ok_button.IsEnabled() is False

    weather.icao_text.SetValue("egll")
    assert weather.ok_button.IsEnabled() is True


def test_a_weather_request_reports_the_code_in_upper_case(dialog):
    weather = dialog(WeatherDialog, "metar")

    weather.icao_text.SetValue("egll")

    assert weather.get_weather_details() == ("EGLL", "metar", False)


def test_checking_survives_a_correction_to_the_icao(dialog):
    """The check was silently reverted by the next keystroke, so a typo fixed
    after checking meant no subscription and nothing said about it."""
    weather = dialog(WeatherDialog, "metar", is_watched=lambda icao, kind: False)

    weather.icao_text.SetValue("EGKK")
    weather.auto_update_checkbox.SetValue(True)
    _fire_auto_update_toggle(weather)
    weather.icao_text.SetValue("EGLL")

    assert weather.get_weather_details() == ("EGLL", "metar", True)


def test_unchecking_survives_a_correction_to_the_icao(dialog):
    """Unchecking is how updates are stopped, so it has to stick too."""
    watched = {("EGLL", "metar"), ("EGKK", "metar")}
    weather = dialog(
        WeatherDialog, "metar", is_watched=lambda icao, kind: (icao, kind) in watched
    )

    weather.icao_text.SetValue("EGLL")
    assert weather.auto_update_checkbox.GetValue() is True

    weather.auto_update_checkbox.SetValue(False)
    _fire_auto_update_toggle(weather)
    weather.icao_text.SetValue("EGKK")

    assert weather.get_weather_details() == ("EGKK", "metar", False)
