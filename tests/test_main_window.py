"""Integration tests that build the real MainWindow.

MainWindow.__init__ wires the menus, the message view and the weather monitor
together. A handler renamed without its menu entry, or a weather report that
loses the tag its context menu acts on, shows up here rather than as a dead
menu item in the shipped application.

Distinct from test_main_window_wiring.py, which runs _init_ui alone on a
stripped-down frame; this builds the whole window.
"""

import pytest

import src.gui.main_window as mw
from src.config import DEFAULT_CONFIG
from src.gui.dialogs import WeatherDialog
from src.model.message_manager import WeatherReport

MENU_TITLES = ["File", "Requests"]

# wx does not expose which handler a menu item is bound to, so the menus are
# checked for shape and the handlers are checked for existence by name.
MENU_HANDLERS = [
    "on_connect_or_disconnect",
    "on_settings",
    "on_check_updates",
    "on_about",
    "on_exit",
    "on_pdc_request",
    "on_logon",
    "on_logoff",
    "on_altitude_change",
    "on_direct_request",
    "on_speed_request",
    "on_when_can_we_expect",
    "on_telex",
    "on_weather_request",
    "on_weather_subscriptions",
]


@pytest.fixture
def window(logger, wx_app, monkeypatch):
    """The real window, kept offline and non-modal.

    Three things in __init__ would otherwise stop a test run dead:

    - _check_first_launch() opens a welcome dialog and blocks on ShowModal
      whenever no config file exists, which is the case on any CI runner and
      any fresh machine. It also writes a config file into the real user data
      directory, which a test has no business doing.
    - the update check reaches the network.
    - a missing sound file, and the guards under test, open a message box.

    The config is stubbed to the defaults rather than read from disk, so the
    window under test does not vary with whatever the developer happens to
    have configured.
    """
    monkeypatch.setattr(mw.MainWindow, "_check_first_launch", lambda self: None)
    monkeypatch.setattr(
        mw, "load_config", lambda: {**DEFAULT_CONFIG, "auto_check_updates": False}
    )
    monkeypatch.setattr(mw.wx, "MessageBox", lambda *args, **kwargs: None)

    window = mw.MainWindow(None, "Sim-CPDLC test", logger)
    window.Hide()
    yield window
    window.weather_monitor.clear()
    window.weather_monitor.shutdown()
    window.Destroy()


def last_row(window):
    """Index of the most recently added row in the message list."""
    return window.message_view.message_list.GetItemCount() - 1


# --- menus --------------------------------------------------------------------


def test_the_menu_bar_carries_the_expected_menus(window):
    menu_bar = window.GetMenuBar()

    titles = [
        menu_bar.GetMenuLabel(index).replace("&", "")
        for index in range(menu_bar.GetMenuCount())
    ]

    assert titles == MENU_TITLES


def test_the_requests_menu_carries_every_request(window):
    """One Requests menu is enough at this scope, so everything the client can
    ask for has to be reachable from it."""
    menu_bar = window.GetMenuBar()
    requests = menu_bar.GetMenu(menu_bar.FindMenu("Requests"))

    labels = [item.GetItemLabelText() for item in requests.GetMenuItems()]

    assert labels == [
        "PDC",
        "Logon",
        "Logoff",
        "Altitude change",
        "Direct to",
        "Speed change",
        "When can we expect",
        "Telex message",
        "Weather request",
        "Automatic weather updates",
    ]


def test_every_menu_item_has_a_handler(window):
    missing = [
        name for name in MENU_HANDLERS if not callable(getattr(window, name, None))
    ]

    assert missing == []


# --- guards -------------------------------------------------------------------


def test_a_request_needing_a_connection_is_refused_while_disconnected(window):
    assert window._require_connection("test") is False


# --- the message list ---------------------------------------------------------


def test_a_message_reaches_the_list_even_without_a_sound(window):
    """The notification sound is optional, and a missing one must not swallow
    the message it was meant to announce."""
    window.new_message_sound = None
    before = window.message_view.message_list.GetItemCount()

    window._add_custom_message("METAR EGLL: TEST", "METAR", play_sound=True)

    assert window.message_view.message_list.GetItemCount() == before + 1


def test_a_multi_line_message_is_flattened_in_the_list_but_not_the_detail(window):
    """The list row is a summary; the detail pane is where the layout matters."""
    window._add_custom_message(
        "OCEANIC REQUEST\nBAW123\nENTRY POINT:MALOT", "BAW123"
    )

    row = last_row(window)
    list_text = window.message_view.message_list.GetItemText(row, 1)
    detail = window.message_manager.get_message_detail_text(
        window.message_view.message_list.GetItemData(row)
    )

    assert "\n" not in list_text
    assert "\n" in detail


def test_a_weather_message_is_tagged_with_what_it_reports_on(window):
    """The tag is what lets the context menu start updates for that report."""
    window._add_weather_message("EGLL 261150Z 24010KT Q1013", "EGLL", "metar")

    row = last_row(window)
    report = window.message_manager.get_message(
        window.message_view.message_list.GetItemData(row)
    )

    assert isinstance(report, WeatherReport)
    assert report.key == ("EGLL", "metar")
    assert window.message_view.message_list.GetItemText(row, 0) == "METAR"


# --- automatic weather updates ------------------------------------------------


def test_the_weather_monitor_starts_idle(window):
    assert window.weather_monitor.count() == 0


def test_a_subscribed_report_reads_as_watched(window):
    window.weather_monitor.subscribe("EGLL", "metar")

    assert window._is_weather_watched("EGLL", "metar") is True


def test_the_context_menu_toggle_stops_and_restarts_updates(window):
    window.weather_monitor.subscribe("EGLL", "metar")

    window._on_toggle_weather_updates("EGLL", "metar")
    assert window._is_weather_watched("EGLL", "metar") is False

    window._on_toggle_weather_updates("EGLL", "metar")
    assert window._is_weather_watched("EGLL", "metar") is True


def test_the_tick_box_mirrors_the_live_subscription_state(window):
    """Opening the dialog always unticked would misreport what is happening,
    so it has to follow the airport as it is typed."""
    window.weather_monitor.subscribe("EGLL", "metar")
    dialog = WeatherDialog(window, "metar", is_watched=window._is_weather_watched)

    try:
        dialog.icao_text.SetValue("EGLL")
        assert dialog.auto_update_checkbox.GetValue() is True

        dialog.icao_text.SetValue("KJFK")
        assert dialog.auto_update_checkbox.GetValue() is False

        dialog.icao_text.SetValue("EGLL")
        assert dialog.auto_update_checkbox.GetValue() is True
        assert dialog.get_weather_details()[2] is True
    finally:
        dialog.Destroy()
