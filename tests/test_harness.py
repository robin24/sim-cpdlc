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
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeConnectionManager, inline_worker, make_main_window


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
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.request("GET", "https://example.invalid/")
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.Session().get("https://example.invalid/")


def test_opening_a_browser_is_refused():
    with pytest.raises(RuntimeError, match="network access in a test"):
        webbrowser.open("https://example.invalid/")


def test_message_boxes_are_recorded_and_answered_without_showing(message_boxes):
    message_boxes.answer = wx.NO

    assert wx.MessageBox("Sure?", "Confirm", wx.YES_NO) == wx.NO
    assert message_boxes.calls == [("Sure?", "Confirm", wx.YES_NO)]
    assert message_boxes.captions == ["Confirm"]


def test_the_simbrief_fetch_never_leaves_the_test(logger, no_simbrief):
    """With a SimBrief id configured the window fetches the flight plan on the
    worker; the lookup must land on the fake, and the dialog must be told."""
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    window = make_main_window(
        logger, session, MessageManager(logger), config={"simbrief_userid": "189007"}
    )
    answers = []

    assert window._fetch_simbrief(answers.append) is True
    window.worker.run_pending()

    assert no_simbrief == ["189007"]
    assert answers == [None]


def test_without_a_simbrief_id_nothing_is_fetched(logger, no_simbrief):
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    window = make_main_window(logger, session, MessageManager(logger))

    assert window._fetch_simbrief(lambda ofp: None) is False
    assert window.worker.pending() == 0
    assert no_simbrief == []


def test_a_first_launch_asks_through_the_recorder_not_a_real_dialog(
    logger, wx_app, isolated_config, message_dialogs
):
    """With no config file, MainWindow.__init__ writes the defaults and asks
    whether to set them up; both must stay inside the test."""
    import src.gui.main_window as mw

    window = mw.MainWindow(None, "Sim-CPDLC test", logger)
    try:
        assert message_dialogs.captions == ["Welcome to Sim-CPDLC"]
        assert Path(isolated_config).exists()
    finally:
        window.worker.shutdown(timeout=1)
        window.weather_monitor.shutdown()
        window.Destroy()
