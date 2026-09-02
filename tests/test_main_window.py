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
from src.model.weather_monitor import WeatherSubscription

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
        "ATIS and Weather request",
        "Automatic weather updates",
    ]


def _mnemonic(label):
    """Return the access-key letter a wx label declares with '&', if any.

    wx escapes a literal ampersand as "&&", which is not a mnemonic.

    Args:
        label: A wx item or menu label, e.g. "&Connect" or "Log&off\tCTRL+O".

    Returns:
        str: The upper-cased mnemonic letter, or None if the label declares
            none.
    """
    index = 0
    while index < len(label) - 1:
        if label[index] == "&":
            if label[index + 1] == "&":
                index += 2
                continue
            return label[index + 1].upper()
        index += 1
    return None


def _colliding_mnemonics(labels):
    """Group labels by mnemonic letter, keeping only letters more than one claims.

    Args:
        labels: Iterable of wx item or menu labels.

    Returns:
        dict: {letter: [label, ...]} for every letter two or more labels
            declare as their mnemonic.
    """
    by_letter = {}
    for label in labels:
        letter = _mnemonic(label)
        if letter is not None:
            by_letter.setdefault(letter, []).append(label)
    return {letter: found for letter, found in by_letter.items() if len(found) > 1}


def test_no_mnemonic_collides_within_a_menu_or_the_menu_bar(window):
    """GetItemLabelText() strips '&', so it cannot see two items fighting over
    the same access key - one of them silently loses single-key keyboard
    access, which is exactly the kind of thing an NVDA user relies on.
    """
    menu_bar = window.GetMenuBar()

    for menu_index in range(menu_bar.GetMenuCount()):
        menu = menu_bar.GetMenu(menu_index)
        labels = [item.GetItemLabel() for item in menu.GetMenuItems()]
        collisions = _colliding_mnemonics(labels)
        title = menu_bar.GetMenuLabel(menu_index)
        assert collisions == {}, f"{title!r} menu: colliding mnemonic(s) {collisions}"

    top_level_labels = [
        menu_bar.GetMenuLabel(index) for index in range(menu_bar.GetMenuCount())
    ]
    collisions = _colliding_mnemonics(top_level_labels)
    assert collisions == {}, f"Menu bar: colliding mnemonic(s) {collisions}"


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


def test_the_checkbox_mirrors_the_live_subscription_state(window):
    """Opening the dialog always unchecked would misreport what is happening,
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


# --- the notification chime ---------------------------------------------------


def chimes(window, monkeypatch):
    """Record every notification sound the window would play."""
    played = []
    monkeypatch.setattr(window, "_play_message_sound", lambda: played.append(None))
    return played


def test_a_report_the_pilot_asked_for_arrives_quietly(window, monkeypatch):
    """The chime means something arrived unprompted. A report the pilot just
    requested is already on their screen, so announcing it is noise."""
    played = chimes(window, monkeypatch)

    window._add_weather_message("EGLL 261150Z 24010KT Q1013", "EGLL", "metar")

    assert played == []


def test_a_changed_report_announces_itself(window, monkeypatch):
    """A report that changed while the pilot was busy is the whole point of
    automatic updates, so that one has to chime."""
    played = chimes(window, monkeypatch)
    subscription = WeatherSubscription("EGLL", "metar")

    window._on_weather_update(
        subscription, "EGLL 261250Z 26015KT Q1012", "METAR EGLL"
    )

    assert len(played) == 1


# --- toggling updates off and on again ----------------------------------------


def test_re_enabling_updates_does_not_repeat_the_report_on_screen(window):
    """Turning updates off and back on for a report the pilot is looking at
    must not announce it again: nothing changed while it was off."""
    text = "EGLL 261150Z 24010KT Q1013"
    window._add_weather_message(text, "EGLL", "metar")
    window.weather_monitor.subscribe("EGLL", "metar", initial_text=text)

    window._on_toggle_weather_updates("EGLL", "metar", text)
    window._on_toggle_weather_updates("EGLL", "metar", text)

    before = window.message_view.message_list.GetItemCount()
    window.weather_monitor._on_result("EGLL", "metar", text, None)

    assert window.message_view.message_list.GetItemCount() == before
