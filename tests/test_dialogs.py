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


def test_ticking_survives_a_correction_to_the_icao(dialog):
    """The tick was silently reverted by the next keystroke, so a typo fixed
    after ticking meant no subscription and nothing said about it."""
    weather = dialog(WeatherDialog, "metar", is_watched=lambda icao, kind: False)

    weather.icao_text.SetValue("EGKK")
    weather.auto_update_checkbox.SetValue(True)
    weather.on_auto_update_toggled(None)
    weather.icao_text.SetValue("EGLL")

    assert weather.get_weather_details() == ("EGLL", "metar", True)


def test_unticking_survives_a_correction_to_the_icao(dialog):
    """Unticking is how updates are stopped, so it has to stick too."""
    watched = {("EGLL", "metar")}
    weather = dialog(
        WeatherDialog, "metar", is_watched=lambda icao, kind: (icao, kind) in watched
    )

    weather.icao_text.SetValue("EGLL")
    assert weather.auto_update_checkbox.GetValue() is True

    weather.auto_update_checkbox.SetValue(False)
    weather.on_auto_update_toggled(None)
    weather.icao_text.SetValue("EGLL")

    assert weather.get_weather_details() == ("EGLL", "metar", False)
