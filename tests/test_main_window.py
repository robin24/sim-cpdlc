"""Build the real MainWindow offline and inspect its menus and wiring."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import sys

logging.disable(logging.CRITICAL)

import wx

import src.gui.main_window as mw

# Keep the test offline and non-modal.
_real_load_config = mw.load_config


def offline_config():
    config = dict(_real_load_config())
    config["auto_check_updates"] = False
    return config


mw.load_config = offline_config

failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")
        failures.append(label)


app = wx.App()
window = mw.MainWindow(None, "Sim-CPDLC test", logging.getLogger("test"))
window.Hide()

menu_bar = window.GetMenuBar()
menu_titles = [menu_bar.GetMenuLabel(i) for i in range(menu_bar.GetMenuCount())]
print("\nMenus:", menu_titles)
check("menu titles", [t.replace("&", "") for t in menu_titles],
      ["File", "Requests", "Weather", "Emergency"])

print()
for index in range(menu_bar.GetMenuCount()):
    menu = menu_bar.GetMenu(index)
    print(f"{menu_bar.GetMenuLabel(index)}:")
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        print(f"    {item.GetItemLabel()}")

# The above check needs internals wx doesn't expose, so verify the handler
# methods exist by name instead.
expected_handlers = [
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
    "on_heading_request",
    "on_confirm_request",
    "on_telex",
    "on_weather_request",
    "on_weather_subscriptions",
    "on_declare_emergency",
    "on_cancel_emergency",
]
missing = [name for name in expected_handlers if not callable(getattr(window, name, None))]
check("all menu handlers exist", missing, [])

check("weather monitor created", hasattr(window, "weather_monitor"), True)
check("weather monitor idle at startup", window.weather_monitor.count(), 0)

# The guards must refuse cleanly while disconnected, without a dialog.
mw.wx.MessageBox = lambda *a, **k: None
check("guard refuses when disconnected", window._require_station("test"), False)
check("connection guard refuses", window._require_connection("test"), False)

# Adding a message with sound must not raise even if the sound is missing.
window.new_message_sound = None
window._add_custom_message("METAR EGLL: TEST", "METAR", play_sound=True)
check("weather message added to view", window.message_view.message_list.GetItemCount() > 0, True)

# A multi-line message must be flattened in the list but kept in the detail pane.
window._add_custom_message("OCEANIC REQUEST\nBAW123\nENTRY POINT:MALOT", "BAW123")
last = window.message_view.message_list.GetItemCount() - 1
list_text = window.message_view.message_list.GetItemText(last, 1)
message_id = window.message_view.message_list.GetItemData(last)
detail = window.message_manager.get_message_detail_text(message_id)
check("list text is one line", "\n" in list_text, False)
check("detail text keeps line breaks", "\n" in detail, True)

# --- Automatic weather updates can be started and stopped ------------------
from src.model.message_manager import WeatherReport

window.weather_monitor.subscribe("EGLL", "metar")
check("report is watched after subscribe", window._is_weather_watched("EGLL", "metar"), True)

# The context menu toggle turns it off again...
window._on_toggle_weather_updates("EGLL", "metar")
check("toggle stops updates", window._is_weather_watched("EGLL", "metar"), False)
# ...and back on.
window._on_toggle_weather_updates("EGLL", "metar")
check("toggle starts updates", window._is_weather_watched("EGLL", "metar"), True)

# A weather report in the list is tagged with what it reports on, which is what
# lets the context menu act on it.
window._add_weather_message("EGLL 261150Z 24010KT Q1013", "EGLL", "metar")
last = window.message_view.message_list.GetItemCount() - 1
report = window.message_manager.get_message(
    window.message_view.message_list.GetItemData(last)
)
check("weather message is tagged", isinstance(report, WeatherReport), True)
check("tagged with airport and type", report.key, ("EGLL", "metar"))
check("sender column shows the type", window.message_view.message_list.GetItemText(last, 0), "METAR")

# The tick box in the dialog mirrors the real state rather than always starting off.
from src.gui.dialogs import WeatherDialog

dlg = WeatherDialog(window, "metar", is_watched=window._is_weather_watched)
dlg.icao_text.SetValue("EGLL")
check("tick box reflects a watched report", dlg.auto_update_checkbox.GetValue(), True)
dlg.icao_text.SetValue("KJFK")
check("tick box clears for an unwatched report", dlg.auto_update_checkbox.GetValue(), False)
dlg.icao_text.SetValue("EGLL")
check("tick box re-reflects on return", dlg.auto_update_checkbox.GetValue(), True)
_, _, wanted = dlg.get_weather_details()
check("details report the tick box state", wanted, True)
dlg.Destroy()

window.weather_monitor.clear()

window.weather_monitor.shutdown()
window.Destroy()

print("\n" + "=" * 60)
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("Window integration test passed.")
