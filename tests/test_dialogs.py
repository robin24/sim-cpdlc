"""Tests for the validation the request dialogs apply before they will submit.

The OK button is the guard: a dialog that lets an incomplete request through
sends malformed text to a controller.
"""

import pytest

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
