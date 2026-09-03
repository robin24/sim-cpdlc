"""Tests for the message list view and its response context menu."""

import pytest
import wx

from tests.support import answerable, uplink
from src.gui.message_view import MessageView
from src.model.message_manager import MessageManager

STATION = "LSAG"


@pytest.fixture
def panel(frame):
    """A panel to build the view on, torn down with the shared frame."""
    return wx.Panel(frame)


def build_view(panel, logger, manager, station):
    view = MessageView(
        panel, logger, manager, lambda *_: None, answerable(station)
    )
    # PopupMenu runs a nested modal loop, which would hang the test. Shadowing
    # it records that a menu would have been shown.
    panel.popped = []
    panel.PopupMenu = panel.popped.append
    return view


def test_message_list_is_single_selection(panel, logger):
    """GetFirstSelected is only unambiguous when one row can be selected."""
    view = MessageView(panel, logger, MessageManager(logger), None, answerable())

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


def test_the_weather_menu_hands_back_the_report_it_was_opened_on(panel, logger):
    """The report text is what seeds change detection when updates are turned
    back on, so the menu has to pass it along with the key. Without it the next
    check treats the report already on screen as new and announces it again.
    """
    manager = MessageManager(logger)
    text = "EGLL 261150Z 24010KT Q1013"
    message_id = manager.add_weather_message(text, "EGLL", "metar")

    toggled = []
    view = MessageView(
        panel,
        logger,
        manager,
        lambda *_: None,
        answerable(STATION),
        on_toggle_weather_updates=lambda *args: toggled.append(args),
        is_weather_watched=lambda *_: False,
    )
    panel.PopupMenu = lambda menu: [
        panel.ProcessEvent(
            wx.CommandEvent(wx.wxEVT_MENU, item.GetId())
        )
        for item in menu.GetMenuItems()
    ]
    view.add_message(message_id)
    view.message_list.Select(0)
    view.on_context_menu(None)

    assert toggled == [("EGLL", "metar", text)]


def test_the_response_menu_offers_every_response_and_fires_the_chosen_one(panel, logger):
    """The menu is destroyed as soon as it closes, so its items are captured
    inside the fake PopupMenu; the second item is chosen from there. TODOS
    item 2: the per-item bindings must be gone once the menu has closed, or a
    reused id would fire a stale response."""
    manager = MessageManager(logger)
    acknowledged = []
    view = MessageView(
        panel, logger, manager, lambda mid, resp: acknowledged.append((mid, resp)), answerable(STATION)
    )
    message_id = manager.add_message(uplink(STATION, 4))
    shown = {}

    def choose_second(menu):
        shown["labels"] = [item.GetItemLabelText() for item in menu.GetMenuItems()]
        shown["ids"] = [item.GetId() for item in menu.GetMenuItems()]
        panel.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, shown["ids"][1]))

    panel.PopupMenu = choose_second
    view.add_message(message_id)
    view.message_list.Select(0)

    view.on_context_menu(None)

    assert shown["labels"] == ["Respond: WILCO", "Respond: UNABLE", "Respond: STANDBY"]
    assert acknowledged == [(message_id, "UNABLE")]

    panel.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, shown["ids"][1]))
    assert acknowledged == [(message_id, "UNABLE")], "binding survived the menu"
