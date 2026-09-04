"""Integration tests that build the real MainWindow.

MainWindow.__init__ wires the menus, the message view and the weather monitor
together. A handler renamed without its menu entry, or a weather report that
loses the tag its context menu acts on, shows up here rather than as a dead
menu item in the shipped application.

Distinct from test_main_window_wiring.py, which runs _init_ui alone on a
stripped-down frame; this builds the whole window.
"""

import os
import sys

import pytest
import wx

import src.gui.main_window as mw
from src.config import DEFAULT_CONFIG, MESSAGE_SOUND_FILENAME, save_config
from src.gui.dialogs import WeatherDialog, WeatherSubscriptionsDialog
from src.model.message_manager import WeatherReport
from src.model.weather_monitor import WeatherSubscription
from src.utils.weather_parsing import report_type_label
from tests.support import FakeConnectionManager, FakeSimConnectManager

# Which handler each menu item must fire. Every handler is replaced on the
# class before the window is built, so the Bind() calls in _init_menu pick up
# the recorders; posting the item's command event then shows which one ran.
MENU_BINDINGS = {
    "File": {
        "Connect": "on_connect_or_disconnect",
        "Settings": "on_settings",
        "Check for Updates": "on_check_updates",
        "About": "on_about",
        "Exit": "on_exit",
    },
    "Requests": {
        "PDC": "on_pdc_request",
        "Logon": "on_logon",
        "Logoff": "on_logoff",
        "Altitude change": "on_altitude_change",
        "Direct to": "on_direct_request",
        "Speed change": "on_speed_request",
        "When can we expect": "on_when_can_we_expect",
        "Telex message": "on_telex",
        "ATIS and Weather request": "on_weather_request",
        "Automatic weather updates": "on_weather_subscriptions",
    },
}

MENU_TITLES = list(MENU_BINDINGS)


@pytest.fixture
def build_window(logger, wx_app, isolated_config, message_boxes):
    """A factory for the real window, kept offline and non-modal.

    The isolated config file is written first, so _check_first_launch() finds
    it and shows no welcome dialog, and the update check is switched off
    unless a test turns it on through the overrides, so nothing reaches
    GitHub. Every window built here is destroyed at teardown.
    """
    built = []

    def build(**overrides):
        # Writing the config file first keeps _check_first_launch() from
        # asking anything at all; the message_dialogs recorder is the safety
        # net if that ever stops being true.
        assert save_config({**DEFAULT_CONFIG, "auto_check_updates": False, **overrides})
        window = mw.MainWindow(None, "Sim-CPDLC test", logger)
        window.Hide()
        # A real SimConnectManager would try to reach a running MSFS; swap in
        # the fake so a CONTACT uplink through this window tunes nothing.
        window.simconnect_manager = FakeSimConnectManager()
        built.append(window)
        return window

    yield build
    for window in built:
        window.worker.shutdown(timeout=1)
        window.weather_monitor.clear()
        window.weather_monitor.shutdown()
        window.Destroy()


@pytest.fixture
def window(build_window):
    return build_window()


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

    assert labels == list(MENU_BINDINGS["Requests"])


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


def _recorder(name, fired):
    def handler(self, event):
        fired.append(name)

    return handler


def test_every_menu_item_fires_its_own_handler(build_window, monkeypatch):
    """A deleted or mis-targeted Bind() shows up as a dead or wrong menu item;
    checking that the methods merely exist could not see either."""
    fired = []
    for names in MENU_BINDINGS.values():
        for name in names.values():
            monkeypatch.setattr(mw.MainWindow, name, _recorder(name, fired))
    window = build_window()
    menu_bar = window.GetMenuBar()

    observed = {}
    for menu_index in range(menu_bar.GetMenuCount()):
        title = menu_bar.GetMenuLabel(menu_index).replace("&", "")
        for item in menu_bar.GetMenu(menu_index).GetMenuItems():
            if item.IsSeparator():
                continue
            fired.clear()
            window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, item.GetId()))
            observed.setdefault(title, {})[item.GetItemLabelText()] = (
                fired[0] if len(fired) == 1 else list(fired)
            )

    assert observed == MENU_BINDINGS


# --- guards -------------------------------------------------------------------


def test_a_request_needing_a_connection_is_refused_and_the_user_is_told(window, message_boxes):
    assert window._require_connection("test") is False
    assert message_boxes.captions == ["Not Connected"]


def test_the_real_window_never_reaches_the_simulator(window):
    """A CONTACT uplink through this fixture must tune the fake, not MSFS."""
    assert isinstance(window.simconnect_manager, FakeSimConnectManager)


def test_the_real_window_listens_to_its_polling_controller(window):
    """The link, unreadable and tick callbacks are how a lost link, a dropped
    uplink and an unanswered logon reach the message list at all, and the
    worker is where every poll runs. The session and the weather monitor send
    through the same worker."""
    controller = window.polling_controller

    assert controller.link_callback == window._on_link_change
    assert controller.unreadable_callback == window._on_unreadable_messages
    assert controller.tick_callback == window._on_poll_tick
    assert controller.worker is window.worker
    assert window.cpdlc_session.worker is window.worker
    assert window.weather_monitor.worker is window.worker


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
    window.weather_monitor.subscribe("EGLL", "vatatis")
    dialog = WeatherDialog(window, is_watched=window._is_weather_watched)

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


# --- the report type is not remembered ----------------------------------------


def test_the_weather_dialog_always_opens_on_atis(window):
    """ATIS is what most requests are for, and the last type used is not
    carried over, so the dialog starts there every time."""
    dialog = WeatherDialog(window, is_watched=window._is_weather_watched)

    try:
        assert dialog.get_weather_details()[1] == "vatatis"
    finally:
        dialog.Destroy()


# --- open dialogs are counted --------------------------------------------------


def test_every_dialog_is_counted_while_it_is_open(window, monkeypatch):
    """The update prompt waits for _modal_depth to reach zero, so every dialog
    the window opens must be counted while ShowModal runs; a handler that
    bypassed _show_dialog would let the prompt pop over its dialog (audit M-5)."""
    depths = []

    def counted_show_modal(dialog):
        depths.append(window._modal_depth)
        return wx.ID_CANCEL

    # Every dialog class is a Python subclass of wx.Dialog, so one patch
    # covers them all.
    monkeypatch.setattr(wx.Dialog, "ShowModal", counted_show_modal)
    window.connection_manager = FakeConnectionManager()
    window.cpdlc_session.connection_manager = window.connection_manager
    window.cpdlc_session.handle_logon_accepted("EDYY")
    window.weather_monitor.subscribe("EGLL", "metar")

    window.on_connect()
    for handler in (
        window.on_settings,
        window.on_pdc_request,
        window.on_logon,
        window.on_altitude_change,
        window.on_direct_request,
        window.on_speed_request,
        window.on_when_can_we_expect,
        window.on_telex,
        window.on_weather_request,
        window.on_weather_subscriptions,
    ):
        handler(None)

    assert len(depths) == 11
    assert all(depth >= 1 for depth in depths)
    assert window._modal_depth == 0


def test_the_about_box_is_counted_while_it_is_open(window, monkeypatch):
    """wx.adv.AboutBox is not a wx.Dialog, so the ShowModal patch above never
    sees it; the update prompt must still wait for it."""
    depths = []
    monkeypatch.setattr(mw, "show_about_dialog", lambda parent: depths.append(window._modal_depth))

    window.on_about(None)

    assert depths == [1]
    assert window._modal_depth == 0


# --- the automatic update check ------------------------------------------------


def test_the_automatic_update_check_is_skipped_when_running_from_source(build_window, monkeypatch):
    """A developer running from a checkout is not a user to tell about
    releases, and the check would hit GitHub on every start."""
    checks = []
    monkeypatch.setattr(mw.UpdateChecker, "check", lambda self, on_done: checks.append(on_done))
    monkeypatch.delattr(sys, "frozen", raising=False)

    build_window(auto_check_updates=True)

    assert checks == []


def test_the_automatic_update_check_runs_in_a_packaged_build(build_window, monkeypatch):
    checks = []
    monkeypatch.setattr(mw.UpdateChecker, "check", lambda self, on_done: checks.append(on_done))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    window = build_window(auto_check_updates=True)

    assert checks == [window._on_auto_update_check]


# --- settings -------------------------------------------------------------------


class FakeSettingsDialog:
    """Stands in for SettingsDialog: answers OK with auto-tune off and a 7-minute weather interval."""

    def __init__(self, *args, **kwargs):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_settings(self):
        return ("", "", "", False, False, 7)

    def Destroy(self):
        pass


def test_saving_settings_refreshes_the_auto_tune_cache(window, monkeypatch):
    """The CONTACT path reads the cached flag rather than the config file on
    every uplink, so Settings has to refresh it."""
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)
    assert window._auto_tune_com1 is True

    window.on_settings(None)

    assert window._auto_tune_com1 is False


def test_saved_settings_apply_the_weather_interval_at_once(window, monkeypatch, message_boxes):
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)

    window.on_settings(None)

    assert window.weather_monitor.interval_ms == 7 * 60000
    assert message_boxes.calls[-1][:2] == (
        "Settings saved. The weather interval applies now; logon codes apply to the next connection.",
        "Settings Saved",
    )


def test_a_failed_save_changes_nothing(window, monkeypatch, message_boxes):
    """The session and the file must agree: a setting the file did not take
    is not applied for the rest of the session either."""
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)
    monkeypatch.setattr(mw, "save_config", lambda config: False)
    interval_before = window.weather_monitor.interval_ms

    window.on_settings(None)

    assert window.weather_monitor.interval_ms == interval_before
    assert window._auto_tune_com1 is True
    assert message_boxes.captions[-1] == "Error"


# --- bundled files -------------------------------------------------------------


def test_the_sound_is_found_from_any_working_directory(monkeypatch, tmp_path):
    """python C:\\...\\app.py run from another folder used to warn that the
    sound was missing, because the lookup went through the working directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)

    path = mw.resource_path(os.path.join("assets", MESSAGE_SOUND_FILENAME))

    assert os.path.isfile(path)


def test_a_frozen_build_looks_in_the_unpacked_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert mw.resource_path("assets/message.wav") == os.path.join(
        str(tmp_path), "assets/message.wav"
    )


def test_the_window_loads_its_sound_from_another_working_directory(build_window, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    window = build_window()

    assert window.new_message_sound is not None


# --- stopping automatic weather updates ------------------------------------------


def test_stopping_updates_from_the_subscriptions_dialog_is_announced(window):
    """The dialog's Stop button used to remove the row silently, while the
    other two stop paths add a SYSTEM row and set the status text."""
    window.weather_monitor.subscribe("EGLL", "vatatis")
    label = report_type_label("vatatis")

    window._stop_weather_updates("EGLL", "vatatis")

    assert window.weather_monitor.count() == 0
    row = last_row(window)
    assert window.message_view.message_list.GetItemText(row, 0) == "SYSTEM"
    assert window.message_view.message_list.GetItemText(row, 1) == (
        f"Stopped automatic updates for {label} EGLL"
    )
    assert window.GetStatusBar().GetStatusText() == f"Stopped watching {label} EGLL."


def test_the_subscriptions_dialog_stops_reports_through_the_window(window, monkeypatch):
    opened = []

    class FakeSubscriptionsDialog:
        def __init__(self, parent, weather_monitor, on_stop):
            opened.append((weather_monitor, on_stop))

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass

    monkeypatch.setattr(mw, "WeatherSubscriptionsDialog", FakeSubscriptionsDialog)
    window.weather_monitor.subscribe("EGLL", "vatatis")

    window.on_weather_subscriptions(None)

    assert opened == [(window.weather_monitor, window._stop_weather_updates)]


def test_stop_all_through_the_real_dialog_stops_and_announces_every_report(window, message_boxes):
    """The real dialog wired to the real window: Stop all must clear every
    subscription, empty the dialog's own list, and announce each report
    through the window so it reads the same as a stop from the context menu."""
    window.weather_monitor.subscribe("EGKK", "metar")
    window.weather_monitor.subscribe("EGLL", "vatatis")

    dlg = WeatherSubscriptionsDialog(window, window.weather_monitor, window._stop_weather_updates)
    try:
        message_boxes.answer = wx.YES

        dlg.on_stop_all(None)

        assert window.weather_monitor.count() == 0
        assert dlg.subscription_list.GetCount() == 0

        count = window.message_view.message_list.GetItemCount()
        metar_row, atis_row = count - 2, count - 1
        assert window.message_view.message_list.GetItemText(metar_row, 0) == "SYSTEM"
        assert window.message_view.message_list.GetItemText(metar_row, 1) == (
            f"Stopped automatic updates for {report_type_label('metar')} EGKK"
        )
        assert window.message_view.message_list.GetItemText(atis_row, 0) == "SYSTEM"
        assert window.message_view.message_list.GetItemText(atis_row, 1) == (
            f"Stopped automatic updates for {report_type_label('vatatis')} EGLL"
        )
    finally:
        dlg.Destroy()


# --- the logon gate ---------------------------------------------------------------


@pytest.mark.parametrize(
    "handler, action",
    [
        ("on_logoff", "log off"),
        ("on_altitude_change", "request an altitude change"),
        ("on_direct_request", "request a direct routing"),
        ("on_speed_request", "request a speed change"),
        ("on_when_can_we_expect", "send a when-can-we-expect inquiry"),
    ],
)
def test_a_request_without_a_logon_is_refused_with_one_message(window, message_boxes, handler, action):
    """Five handlers hand-rolled the same box with three different wordings."""
    window.connection_manager = FakeConnectionManager()
    window.cpdlc_session.connection_manager = window.connection_manager

    getattr(window, handler)(None)

    assert message_boxes.calls == [
        (f"You must be logged on to a station to {action}.", "Not Logged On", wx.OK | wx.ICON_INFORMATION)
    ]


def test_logoff_is_refused_without_a_connection_before_the_logon_is_even_checked(window, message_boxes):
    """on_logoff only checked _require_logon, unlike every other station
    action, which checks _require_connection first too. A fresh window's real
    connection manager is not connected, so this must stop at the connection
    gate and never get as far as asking whether we are logged on."""
    window.on_logoff(None)

    assert message_boxes.calls == [
        ("You must be connected to the CPDLC network to log off.", "Not Connected", wx.OK | wx.ICON_INFORMATION)
    ]
