"""The hermetic fixtures: nothing a test builds may reach outside the test.

Every fixture checked here is autouse, so these tests document guarantees the
whole suite relies on.
"""

import webbrowser
from pathlib import Path

import pytest
import requests
import wx

from src import config as config_module
from src.config import DEFAULT_CONFIG, load_config, save_config
from src.gui.dialogs import ConnectDialog


def test_the_config_file_is_a_temporary_one(isolated_config, tmp_path):
    assert Path(config_module.CONFIG_FILE) == tmp_path / "config.json"
    assert Path(isolated_config) == tmp_path / "config.json"


def test_saving_the_config_writes_only_the_temporary_file(isolated_config):
    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "42"}) is True

    assert Path(isolated_config).exists()
    assert load_config()["simbrief_userid"] == "42"


def test_network_access_is_refused():
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.get("https://example.invalid/")
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.post("https://example.invalid/")


def test_opening_a_browser_is_refused():
    with pytest.raises(RuntimeError, match="network access in a test"):
        webbrowser.open("https://example.invalid/")


def test_message_boxes_are_recorded_and_answered_without_showing(message_boxes):
    message_boxes.answer = wx.NO

    assert wx.MessageBox("Sure?", "Confirm", wx.YES_NO) == wx.NO
    assert message_boxes.calls == [("Sure?", "Confirm", wx.YES_NO)]
    assert message_boxes.captions == ["Confirm"]


def test_the_connect_dialog_never_reaches_simbrief(frame, no_simbrief, message_boxes):
    """With a SimBrief id configured the dialog fetches the flight plan in its
    constructor and warns when that fails; both must stay inside the test."""
    save_config({**DEFAULT_CONFIG, "simbrief_userid": "189007"})

    dialog = ConnectDialog(frame)
    try:
        assert no_simbrief == ["189007"]
        assert message_boxes.captions == ["SimBrief"]
    finally:
        dialog.Destroy()
