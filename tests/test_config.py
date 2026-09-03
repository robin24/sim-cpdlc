"""Tests for reading configuration safely.

load_config fills in missing keys but validates neither type nor range, so a
hand-edited or downgrade-written file reaches the application as-is.
"""

from src.config import (
    DEFAULT_WEATHER_INTERVAL_MINUTES,
    MAX_WEATHER_INTERVAL_MINUTES,
    MIN_WEATHER_INTERVAL_MINUTES,
    weather_interval_minutes,
)


def test_a_configured_interval_is_used_as_given():
    assert weather_interval_minutes({"weather_update_interval": 10}) == 10


def test_a_missing_interval_falls_back_to_the_default():
    assert weather_interval_minutes({}) == DEFAULT_WEATHER_INTERVAL_MINUTES


def test_an_interval_below_the_minimum_is_clamped():
    """Zero would start a wx.Timer that fires as fast as the event loop
    allows, re-requesting every watched report continuously."""
    assert weather_interval_minutes({"weather_update_interval": 0}) == (
        MIN_WEATHER_INTERVAL_MINUTES
    )


def test_an_interval_above_the_maximum_is_clamped():
    assert weather_interval_minutes({"weather_update_interval": 5000}) == (
        MAX_WEATHER_INTERVAL_MINUTES
    )


def test_a_non_numeric_interval_falls_back_to_the_default():
    """A string would make the minutes-to-milliseconds multiply build a
    60000-character string and crash wx.Timer.Start()."""
    for value in ("5", None, [], 3.5):
        assert weather_interval_minutes({"weather_update_interval": value}) == (
            DEFAULT_WEATHER_INTERVAL_MINUTES
        ), value
