"""Tests for the validation the request dialogs apply before they will submit.

The OK button is the guard: a dialog that lets an incomplete request through
sends malformed text to a controller.
"""

import pytest

from src.gui.dialogs import (
    ConfirmRequestDialog,
    EmergencyDialog,
    HeadingRequestDialog,
    WeatherDialog,
)


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


# --- heading ------------------------------------------------------------------


def test_a_heading_request_needs_a_heading(dialog):
    heading = dialog(HeadingRequestDialog)

    assert heading.ok_button.IsEnabled() is False


def test_a_heading_is_padded_to_three_digits(dialog):
    """FANS headings are three digits, so 70 has to go out as 070."""
    heading = dialog(HeadingRequestDialog)

    heading.degrees_text.SetValue("70")

    assert heading.get_heading() == "070"
    assert heading.ok_button.IsEnabled() is True


def test_a_heading_above_360_is_refused(dialog):
    heading = dialog(HeadingRequestDialog)

    heading.degrees_text.SetValue("400")

    assert heading.ok_button.IsEnabled() is False


# --- confirm ------------------------------------------------------------------


def test_a_confirm_request_defaults_to_the_assigned_level(dialog):
    confirm = dialog(ConfirmRequestDialog)

    assert confirm.get_message() == "CONFIRM ASSIGNED LEVEL"


def test_a_confirm_request_follows_the_selected_type(dialog):
    confirm = dialog(ConfirmRequestDialog)

    confirm.type_choice.SetSelection(1)

    assert confirm.get_message() == "CONFIRM ASSIGNED SPEED"


# --- emergency ----------------------------------------------------------------


def test_an_emergency_defaults_to_the_lesser_of_the_two(dialog):
    """MAYDAY has to be chosen deliberately, never landed on by accident."""
    emergency = dialog(EmergencyDialog)

    assert emergency.get_emergency_details()[0] is False


def test_an_emergency_needs_both_fuel_and_souls(dialog):
    emergency = dialog(EmergencyDialog)

    emergency.fuel_text.SetValue("0230")
    assert emergency.ok_button.IsEnabled() is False

    emergency.souls_text.SetValue("212")
    assert emergency.ok_button.IsEnabled() is True
