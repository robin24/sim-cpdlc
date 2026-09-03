"""Tests for reading configuration safely.

load_config fills in missing keys but validates neither type nor range, so a
hand-edited or downgrade-written file reaches the application as-is.
"""

import os
from pathlib import Path

from src.config import (
    DEFAULT_CONFIG,
    DEFAULT_WEATHER_INTERVAL_MINUTES,
    MAX_WEATHER_INTERVAL_MINUTES,
    MIN_WEATHER_INTERVAL_MINUTES,
    load_config,
    save_config,
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


# --- reading and writing the file ---------------------------------------------


def test_a_missing_file_yields_a_fresh_copy_of_the_defaults(isolated_config):
    loaded = load_config()

    assert loaded == DEFAULT_CONFIG
    assert loaded is not DEFAULT_CONFIG


def test_missing_keys_are_filled_in_and_present_ones_kept(isolated_config):
    Path(isolated_config).write_text('{"hoppie_logon_code": "ABC"}')

    loaded = load_config()

    assert loaded["hoppie_logon_code"] == "ABC"
    assert set(loaded) == set(DEFAULT_CONFIG)


def test_invalid_json_yields_the_defaults(isolated_config):
    Path(isolated_config).write_text("{not json")

    assert load_config() == DEFAULT_CONFIG


def test_only_a_mapping_can_be_saved(isolated_config):
    assert save_config("nope") is False


def test_a_saved_config_round_trips(isolated_config):
    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "42"}) is True

    assert load_config()["simbrief_userid"] == "42"


def test_a_failed_write_leaves_the_previous_file_and_no_temp_file_behind(
    isolated_config, monkeypatch
):
    """TODOS item 5: the write is atomic. A PermissionError from os.replace is
    what Windows raises when the file is open elsewhere."""
    save_config({**DEFAULT_CONFIG, "simbrief_userid": "before"})

    def refuse(src, dst):
        raise PermissionError(13, "file in use", dst)

    monkeypatch.setattr(os, "replace", refuse)

    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "after"}) is False
    assert load_config()["simbrief_userid"] == "before"
    assert [path.name for path in Path(isolated_config).parent.iterdir()] == ["config.json"]
