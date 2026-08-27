"""Offline smoke test for the new Sim-CPDLC features."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import sys

logging.disable(logging.CRITICAL)

failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got:  {got!r}\n          want: {want!r}")
        failures.append(label)


def check_true(label, condition):
    check(label, bool(condition), True)


# ---------------------------------------------------------------- session
print("\n== CPDLC message formats ==")

from src.model.cpdlc_session import CpdlcSession


class FakeConnection:
    def __init__(self):
        self.sent = []
        self.connected = True

    def is_connected(self):
        return self.connected

    def send_cpdlc(self, recipient, min_value, rr, message, mrn=None):
        self.sent.append({"to": recipient, "min": min_value, "rr": rr, "msg": message})

    def send_info_request(self, info_type, icao):
        return f"{icao} REPORT FOR {info_type}"


def new_session():
    connection = FakeConnection()
    session = CpdlcSession(logging.getLogger("test"), connection)
    session.set_callsign("BAW123")
    session.current_station = "EGGX"
    return session, connection


session, conn = new_session()
check("heading request", session.send_heading_request("270")[1],
      "REQUEST HEADING 270")
check("heading rr", conn.sent[-1]["rr"], "Y")
check("heading recipient", conn.sent[-1]["to"], "EGGX")

session, conn = new_session()
session.send_query("CONFIRM ASSIGNED LEVEL")
check("confirm query text", conn.sent[-1]["msg"], "CONFIRM ASSIGNED LEVEL")
check("confirm query rr is Y", conn.sent[-1]["rr"], "Y")

session, conn = new_session()
_, msg = session.send_emergency(True, "0230", "212", "BIKF", "DCT", "ENGINE FAILURE")
check(
    "mayday text",
    msg,
    "MAYDAY MAYDAY MAYDAY\n0230 OF FUEL REMAINING AND 212 SOULS ON BOARD\n"
    "DIVERTING TO BIKF VIA DCT\nENGINE FAILURE",
)
check("pan pan text", session.send_emergency(False)[1], "PAN PAN PAN")
check("cancel emergency", session.send_cancel_emergency()[1], "CANCEL EMERGENCY")

# MIN counter must advance once per message.
session, conn = new_session()
session.send_heading_request("270")
session.send_heading_request("280")
check("MIN counter advances", [s["min"] for s in conn.sent], [1, 2])

# Precondition guards.
session, conn = new_session()
session.current_station = ""
check("no station is refused", session.send_heading_request("270"), (False, None))
session, conn = new_session()
conn.connected = False
check("no connection is refused", session.send_heading_request("270"), (False, None))

session, conn = new_session()
check("weather request", session.request_weather("metar", "EGLL"),
      (True, "EGLL REPORT FOR metar"))

# --------------------------------------------------------- weather monitor
print("\n== Weather monitor change detection ==")

import wx

from src.model.weather_monitor import WeatherMonitor


class ScriptedConnection:
    def __init__(self, reports):
        self.reports = reports
        self.calls = 0

    def is_connected(self):
        return True

    def send_info_request(self, info_type, icao):
        value = self.reports[min(self.calls, len(self.reports) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


app = wx.App()
frame = wx.Frame(None)

updates = []
scripted = ScriptedConnection(
    [
        "EGLL ATIS INFORMATION K RWY 27R",
        "EGLL ATIS INFO KILO RUNWAY 27R",   # reworded, same letter
        "EGLL ATIS INFORMATION L RWY 09L",  # new letter
    ]
)
monitor = WeatherMonitor(
    logging.getLogger("test"),
    scripted,
    on_update=lambda sub, text, desc: updates.append(desc),
)
monitor._parent = frame
monitor.subscribe("EGLL", "vatatis")

# Drive the result path directly, which is what the worker thread posts back.
monitor._on_result("EGLL", "vatatis", scripted.send_info_request("vatatis", "EGLL"), None)
check("first report announced", len(updates), 1)
monitor._on_result("EGLL", "vatatis", scripted.send_info_request("vatatis", "EGLL"), None)
check("reworded same-letter ATIS is silent", len(updates), 1)
monitor._on_result("EGLL", "vatatis", scripted.send_info_request("vatatis", "EGLL"), None)
check("new ATIS letter announced", len(updates), 2)
check("announcement text", updates[-1], "ATIS EGLL information L")

# METAR compares on text, so an amended report is announced.
metar_updates = []
metar_monitor = WeatherMonitor(
    logging.getLogger("test"),
    scripted,
    on_update=lambda sub, text, desc: metar_updates.append(desc),
)
metar_monitor._parent = frame
metar_monitor.subscribe("EGLL", "metar", initial_text="EGLL 261150Z 24010KT Q1013")
metar_monitor._on_result("EGLL", "metar", "EGLL 261150Z  24010KT  Q1013", None)
check("initial_text suppresses a repeat", len(metar_updates), 0)
metar_monitor._on_result("EGLL", "metar", "EGLL 261220Z 26015KT Q1012", None)
check("changed METAR announced", len(metar_updates), 1)

# Repeated failures drop the subscription.
errors = []
failing = WeatherMonitor(
    logging.getLogger("test"),
    scripted,
    on_error=lambda sub, err: errors.append(err),
)
failing._parent = frame
failing.subscribe("ZZZZ", "metar")
for _ in range(5):
    failing._on_result("ZZZZ", "metar", None, "no data")
check("subscription dropped after repeated failures", failing.count(), 0)
check("error callback fired once", len(errors), 1)

check("unsubscribe works", monitor.unsubscribe("EGLL", "vatatis"), True)
check("unsubscribe twice is a no-op", monitor.unsubscribe("EGLL", "vatatis"), False)

# Disconnecting and reconnecting must leave the monitor running again.
lifecycle = WeatherMonitor(logging.getLogger("test"), scripted, interval_ms=60000)
lifecycle.start(frame)
check_true("monitor running after start", lifecycle._timer.IsRunning())
lifecycle.stop()
check_true("monitor stopped after stop", not lifecycle._timer.IsRunning())
lifecycle.start(frame)
check_true("monitor running again after restart", lifecycle._timer.IsRunning())
check_true("restart clears the shutdown flag", not lifecycle._shutting_down)
lifecycle.shutdown()
check("shutdown destroys the timer", lifecycle._timer, None)

# ------------------------------------------------------------ polling rate
print("\n== Polling rate ==")

from src.controller.polling_controller import PollingController


class AlwaysConnected:
    def is_connected(self):
        return True


poller = PollingController(logging.getLogger("test"), AlwaysConnected())
poller.start(frame)

# Hoppie asks for 45-75s, randomly timed, rising to 20s while a reply is due.
draws = [poller.next_interval() for _ in range(2000)]
check_true("idle polls stay within 45-75s", all(45000 <= d <= 75000 for d in draws))
check_true("idle polls are actually randomised", len(set(draws)) > 100)
check_true("idle average is about 60s", 57000 < sum(draws) / len(draws) < 63000)

poller.set_active_polling()
check("active mode polls every 20s", set(poller.next_interval() for _ in range(20)), {20000})
check_true("active mode is flagged", poller.is_active_mode())

poller.last_activity_time -= 400  # 400 seconds of quiet
poller.check_polling_timeout()
check_true("quiet period ends active mode", not poller.is_active_mode())
check_true("and returns to the randomised band", 45000 <= poller.next_interval() <= 75000)

poller.stop()
check_true("stop halts the timer", not poller.is_running())
poller._schedule_next()
check_true("a stopped poller does not reschedule itself", not poller.is_running())

# ------------------------------------------------------- reason wording
print("\n== Reason wording ==")

from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER

session, conn = new_session()
check(
    "performance reason uses the full standard wording",
    session.send_altitude_change_request("FL350", REASON_AIRCRAFT_PERFORMANCE)[1],
    "REQUEST FL350 DUE TO AIRCRAFT PERFORMANCE",
)
check(
    "weather reason unchanged",
    session.send_direct_request("MALOT", REASON_WEATHER)[1],
    "REQUEST DIRECT TO MALOT DUE TO WEATHER",
)

# ---------------------------------------------------------------- dialogs
print("\n== Dialogs ==")

from src.gui.dialogs import (
    ConfirmRequestDialog,
    EmergencyDialog,
    HeadingRequestDialog,
    WeatherDialog,
)

dlg = WeatherDialog(frame, "metar")
dlg.icao_text.SetValue("egll")
check_true("weather OK enabled at 4 chars", dlg.ok_button.IsEnabled())
check("weather details", dlg.get_weather_details(), ("EGLL", "metar", False))
dlg.icao_text.SetValue("egl")
check_true("weather OK disabled at 3 chars", not dlg.ok_button.IsEnabled())
dlg.Destroy()

dlg = HeadingRequestDialog(frame)
check_true("heading OK disabled when empty", not dlg.ok_button.IsEnabled())
dlg.degrees_text.SetValue("70")
check("heading padded to three digits", dlg.get_heading(), "070")
check_true("heading OK enabled", dlg.ok_button.IsEnabled())
dlg.degrees_text.SetValue("400")
check_true("heading OK disabled above 360", not dlg.ok_button.IsEnabled())
dlg.Destroy()

dlg = ConfirmRequestDialog(frame)
check("confirm defaults to level", dlg.get_message(), "CONFIRM ASSIGNED LEVEL")
dlg.type_choice.SetSelection(1)
check("confirm speed", dlg.get_message(), "CONFIRM ASSIGNED SPEED")
dlg.Destroy()

dlg = EmergencyDialog(frame)
check("emergency defaults to pan pan", dlg.get_emergency_details()[0], False)
dlg.fuel_text.SetValue("0230")
check_true("emergency OK disabled with only fuel", not dlg.ok_button.IsEnabled())
dlg.souls_text.SetValue("212")
check_true("emergency OK enabled with fuel and souls", dlg.ok_button.IsEnabled())
dlg.Destroy()

frame.Destroy()

print("\n" + "=" * 60)
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("All smoke tests passed.")
