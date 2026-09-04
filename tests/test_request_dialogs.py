"""What each request dialog lets through its OK button, and what it hands back.

hoppie_connector validates at send time with messages the pilot cannot act on
("invalid characters", "Invalid TO station name"), so the OK button has to be
the gate, and the getter has to return exactly the text that was validated:
stripped, upper-cased and zero-padded.
"""

import pytest
import wx

from src.gui.dialogs import (
    AltitudeChangeDialog,
    DirectRequestDialog,
    LogonDialog,
    SpeedRequestDialog,
    WhenCanWeDialog,
)
from src.model.cpdlc_elements import REASON_WEATHER

# Passes str.isdigit() and int(), but is not ASCII and the network rejects it.
ARABIC_INDIC_350 = "٣٥٠"
ARABIC_INDIC_82 = "٨٢"


def select(radio):
    """Pick a radio button the way a user does, so the bound handler runs."""
    radio.SetValue(True)
    event = wx.CommandEvent(wx.EVT_RADIOBUTTON.typeId, radio.GetId())
    event.SetEventObject(radio)
    radio.GetEventHandler().ProcessEvent(event)


# --- logon --------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("EDDF", True),
        ("eddf", True),
        (" EDDF ", True),
        ("KZ7X", True),
        ("EDD", False),
        ("EDDFX", False),
        ("ED F", False),
        ("ED-F", False),
        ("ÉDDF", False),
        ("", False),
    ],
)
def test_logon_accepts_exactly_four_letters_or_digits(dialog, typed, enabled):
    logon = dialog(LogonDialog)

    logon.station_text.SetValue(typed)

    assert logon.ok_button.IsEnabled() is enabled


def test_logon_returns_the_station_stripped_and_upper_cased(dialog):
    """"EDDF " passed the old length check and failed at send time."""
    logon = dialog(LogonDialog)

    logon.station_text.SetValue(" eddf ")

    assert logon.get_logon_details() == "EDDF"


# --- altitude -----------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("350", True),
        ("50", True),
        (" 350 ", True),
        ("5", False),
        ("3500", False),
        ("+350", False),
        ("3_50", False),
        ("35.0", False),
        (ARABIC_INDIC_350, False),
        ("", False),
    ],
)
def test_altitude_accepts_two_or_three_ascii_digits(dialog, typed, enabled):
    """int() took "3_50" and "+350", which went out as REQUEST FL3_50."""
    altitude = dialog(AltitudeChangeDialog)

    altitude.altitude_text.SetValue(typed)

    assert altitude.ok_button.IsEnabled() is enabled


def test_altitude_is_returned_as_a_padded_flight_level(dialog):
    altitude = dialog(AltitudeChangeDialog)

    altitude.altitude_text.SetValue(" 50 ")

    assert altitude.get_altitude_details() == ("FL050", None)


def test_altitude_carries_the_chosen_reason(dialog):
    altitude = dialog(AltitudeChangeDialog)
    altitude.altitude_text.SetValue("350")

    select(altitude.reason_weather)

    assert altitude.get_altitude_details() == ("FL350", REASON_WEATHER)


# --- direct to ----------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("KONOL", True),
        ("konol", True),
        (" KONOL ", True),
        ("55N020W", True),
        ("5530N", True),
        ("DF", True),
        ("K", False),
        ("ABCDEFGH", False),
        ("KON-OL", False),
        ("KON OL", False),
        ("ÅBCD", False),
        ("", False),
    ],
)
def test_direct_to_accepts_two_to_seven_letters_or_digits(dialog, typed, enabled):
    """Oceanic fixes such as 55N020W were refused by the letters-only rule."""
    direct = dialog(DirectRequestDialog)

    direct.fix_text.SetValue(typed)

    assert direct.ok_button.IsEnabled() is enabled


def test_direct_to_returns_the_fix_stripped_and_upper_cased(dialog):
    direct = dialog(DirectRequestDialog)

    direct.fix_text.SetValue(" 55n020w ")

    assert direct.get_direct_details() == ("55N020W", None)


def test_direct_to_helper_text_names_the_rule(dialog):
    direct = dialog(DirectRequestDialog)

    assert direct.helper_text.GetLabel() == "2-7 letters or digits, e.g. KONOL or 55N020W"


# --- speed --------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("82", True),
        ("082", True),
        (" 82 ", True),
        ("8", False),
        ("0820", False),
        ("0.82", False),
        (ARABIC_INDIC_82, False),
        ("", False),
    ],
)
def test_mach_accepts_two_or_three_ascii_digits(dialog, typed, enabled):
    speed = dialog(SpeedRequestDialog)

    speed.speed_text.SetValue(typed)

    assert speed.ok_button.IsEnabled() is enabled


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("300", True),
        ("250", True),
        ("30", False),
        ("3000", False),
        ("+300", False),
        ("", False),
    ],
)
def test_knots_need_exactly_three_ascii_digits(dialog, typed, enabled):
    """The knots branch used to be a copy of the Mach branch, so M820 went out."""
    speed = dialog(SpeedRequestDialog)
    select(speed.radio_knots)

    speed.speed_text.SetValue(typed)

    assert speed.ok_button.IsEnabled() is enabled


def test_switching_the_speed_type_re_checks_the_value(dialog):
    speed = dialog(SpeedRequestDialog)
    speed.speed_text.SetValue("82")
    assert speed.ok_button.IsEnabled() is True

    select(speed.radio_knots)

    assert speed.ok_button.IsEnabled() is False
    assert speed.helper_text.GetLabel() == "Enter speed in knots, 3 digits (e.g. 300)"


def test_mach_is_returned_padded_to_three_digits(dialog):
    speed = dialog(SpeedRequestDialog)

    speed.speed_text.SetValue(" 82 ")

    assert speed.get_speed_details() == ("082", True, None)


def test_knots_are_returned_as_typed(dialog):
    speed = dialog(SpeedRequestDialog)
    select(speed.radio_knots)

    speed.speed_text.SetValue("300")

    assert speed.get_speed_details() == ("300", False, None)


# --- when can we expect -------------------------------------------------------


def test_a_request_without_a_value_is_ready_at_once(dialog):
    when = dialog(WhenCanWeDialog)

    assert when.ok_button.IsEnabled() is True
    assert when.value_text.IsShown() is False
    assert when.get_message_text() == "WHEN CAN WE EXPECT HIGHER LEVEL"


def test_choosing_a_type_with_a_value_shows_the_field_and_waits_for_it(dialog):
    when = dialog(WhenCanWeDialog)

    select(when.radios[3])

    assert when.value_text.IsShown() is True
    assert when.ok_button.IsEnabled() is False


@pytest.mark.parametrize(
    "index, typed, enabled, text",
    [
        (3, "50", True, "WHEN CAN WE EXPECT CLIMB TO FL050"),
        (3, " 350 ", True, "WHEN CAN WE EXPECT CLIMB TO FL350"),
        (3, "5", False, None),
        (3, "+350", False, None),
        (4, "100", True, "WHEN CAN WE EXPECT DESCENT TO FL100"),
        (4, ARABIC_INDIC_350, False, None),
        (5, "82", True, "WHEN CAN WE EXPECT M082"),
        (5, "0820", False, None),
        (6, "300", True, "WHEN CAN WE EXPECT 300K"),
        (6, "30", False, None),
    ],
)
def test_a_request_with_a_value_applies_the_rule_for_its_type(dialog, index, typed, enabled, text):
    when = dialog(WhenCanWeDialog)
    select(when.radios[index])

    when.value_text.SetValue(typed)

    assert when.ok_button.IsEnabled() is enabled
    if enabled:
        assert when.get_message_text() == text
