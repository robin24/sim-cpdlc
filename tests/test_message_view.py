"""Tests for the message list view and its response context menu."""

import pytest
import wx

from conftest import uplink
from src.gui.message_view import MessageView
from src.model.message_manager import MessageManager

STATION = "LSAG"


@pytest.fixture
def panel():
    app = wx.App()
    frame = wx.Frame(None)
    yield wx.Panel(frame)
    frame.Destroy()
    app.Destroy()


def build_view(panel, logger, manager, station):
    view = MessageView(
        panel, logger, manager, lambda *_: None, lambda: station
    )
    # PopupMenu runs a nested modal loop, which would hang the test. Shadowing
    # it records that a menu would have been shown.
    panel.popped = []
    panel.PopupMenu = panel.popped.append
    return view


def test_message_list_is_single_selection(panel, logger):
    """GetFirstSelected is only unambiguous when one row can be selected."""
    view = MessageView(panel, logger, MessageManager(logger), None, lambda: "")

    assert view.message_list.GetWindowStyleFlag() & wx.LC_SINGLE_SEL


def test_no_menu_for_a_message_from_another_station(panel, logger):
    manager = MessageManager(logger)
    view = build_view(panel, logger, manager, "EDGG")
    message_id = manager.add_message(uplink("EDYY", 4))
    view.add_message(message_id)
    view.message_list.Select(0)

    view.on_context_menu(None)

    assert panel.popped == []


def test_menu_shown_for_a_message_from_the_current_station(panel, logger):
    manager = MessageManager(logger)
    view = build_view(panel, logger, manager, STATION)
    message_id = manager.add_message(uplink(STATION, 4))
    view.add_message(message_id)
    view.message_list.Select(0)

    view.on_context_menu(None)

    assert len(panel.popped) == 1
