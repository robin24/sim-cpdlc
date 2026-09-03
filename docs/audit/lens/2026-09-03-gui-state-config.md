# Sim-CPDLC audit — GUI logic, state consistency, configuration/packaging, input validation, accessibility, code quality

Read-only audit of `C:\Claude\sim-cpdlc` at commit `9c06458` (main, 2026-09-03). Every file under `src/`, `app.py`, `tests/`, the project/packaging files and `hoppie_connector` 0.2.1 (`__init__.py`, `API.py`, `Messages.py`, `Utilities.py`, `CPDLC.py`, `Responses.py`) were read in full. Regex and validation claims below were confirmed by running the pure functions with the review venv interpreter (Python 3.14, wxPython 4.2.5 msw / wxWidgets 3.2.9); nothing GUI-side was launched.

No finding in this lens rises to Critical or High: the state machine is mostly sound, and the earlier review items in TODOS.md and the PR-24 spec are fixed as claimed (including the "out of scope" items for `check_now()`, the weather-interval clamp, the fixture window leak and the per-report request methods, all closed by later commits). The remaining "out of scope" duplication items (hand-rolled guards, four near-identical `CpdlcSession` senders) are still open and listed under Info.

---

## Medium

### M1. After an automatic reconnection fails, the File menu still says "Disconnect" and there is no "Connect" to reach
- **Severity**: Medium — the status bar tells the user to reconnect, but the only menu entry is labelled the opposite; for an NVDA user that is a dead end unless they guess.
- **Confidence**: Confirmed
- **Location(s)**: `src/controller/polling_controller.py:182-196`, `src/gui/main_window.py:307-314`, `:341-342`, `:397-398`, `src/model/connection_manager.py:347-350`; also `polling_controller.py:69, 90-107, 205-217`
- **What is wrong**: `PollingController.on_poll_timer` handles the reconnection-failure branch entirely on its own: it sets the status text, stops the timer, and `attempt_reconnection()` has already set `cnx = None`. Nothing notifies `MainWindow`, and `menu_item_connect` is relabelled only inside `on_connect`/`on_disconnect`. The item therefore keeps the label "&Disconnect" and help text "Disconnect from the CPDLC network" while `is_connected()` is False. Because `on_connect_or_disconnect` dispatches on `is_connected()`, activating "Disconnect" actually opens the Connect dialog, so recovery is possible but only by doing the opposite of what the menu says. Secondary: `_reported_failure` is never reset by `start()`, so the first successful poll after the manual reconnect overwrites "Connected as X." with "Connection restored.".
- **Failure scenario**: Link drops → three failed polls → "Connection problem (3/3) - retrying..." → reconnection fails → status "Connection lost. Reconnect to continue." → user opens File: entries are Disconnect / Settings / Check for Updates / About / Exit. A screen-reader user hearing "Disconnect" has no reason to activate it; a sighted user sees a contradiction. If they do activate it, the Connect dialog appears.
- **Evidence**:
  ```python
  # polling_controller.py:191-196
  self.logger.error("Reconnection failed")
  self._set_status("Connection lost. Reconnect to continue.")
  self.stop()
  # main_window.py:341 (only place the label becomes Disconnect) / :397 (only place it becomes Connect again)
  self.menu_item_connect.SetItemLabel("&Disconnect")
  ```
- **Suggested fix direction**: Give `PollingController` an `on_connection_lost` callback (or have it call a `MainWindow._on_connection_lost()` that resets the menu label/help, stops the weather monitor, and adds a SYSTEM message), and reset `_reported_failure` in `start()`. Alternatively derive the label from `is_connected()` in an `EVT_UPDATE_UI` handler.

### M2. A LOGOFF that fails to send during Disconnect/Exit is silently ignored, and the session's logon state is never reset across a disconnect/reconnect
- **Severity**: Medium — the app tells the user "you will be logged off", proceeds without saying it could not, and afterwards routes requests and offers response menus for a station it is not connected to.
- **Confidence**: Confirmed
- **Location(s)**: `src/gui/main_window.py:379-386`, `:1084-1087`, `:316-347` (`on_connect` never touches `cpdlc_session`), `src/model/cpdlc_session.py:116-141` (`logoff` leaves `current_station` on failure), `:27-28, 100-101, 435-436` (`pending_logon_*` cleared only by acceptance), `src/model/connection_manager.py:256-271` (clears its own fields only)
- **What is wrong**: `on_disconnect` calls `send_logoff_message()` and inspects `success` only to decide whether to log the sent text; a `False` result (the common case when the reason for disconnecting is a dead link) produces no dialog, no SYSTEM message, and `current_station` stays set. `ConnectionManager.disconnect()` is careful to clear everything `connect()` set, but there is no equivalent for `CpdlcSession`: `current_station`, `pending_logon_min/station` and `callsign` survive the disconnect and the next `connect()`. `is_logged_on()` then reports True on a fresh connection.
- **Failure scenario**: Logged on to EDDF, link dies → user chooses File > Disconnect → confirmation says "you will be logged off from this station" → LOGOFF send raises `HoppieError` → silently dropped → "Disconnected from CPDLC network." → later File > Connect as a different callsign or on the other network → status "Connected as X." but Requests > Altitude change is accepted and transmitted to EDDF (`send_altitude_change_request` only checks `current_station` and `is_connected()`), the context menu on old EDDF uplinks still offers WILCO/UNABLE, and the next Disconnect/Exit confirmation again claims "logged on to EDDF". Same for `on_close` (1084-1087), where the failure is invisible in the log too because only `cpdlc_session` logs it.
- **Evidence**:
  ```python
  # main_window.py:379-382
  if self.cpdlc_session.is_logged_on():
      success, message = self.cpdlc_session.send_logoff_message()
      if success and message:
          self._add_custom_message(message)
  # cpdlc_session.py:130-134 — failure path returns before current_station is cleared
  except HoppieError as exc:
      ...
      return False, str(exc)
  ```
- **Suggested fix direction**: Add `CpdlcSession.reset()` (clear `current_station`, `pending_logon_*`, restart `cpdlc_min_counter`) and call it from `on_disconnect` after the LOGOFF attempt and from `on_connect` before `set_callsign`. In `on_disconnect`, surface a failed LOGOFF as a SYSTEM message ("Could not send LOGOFF to EDDF: …") so the user knows ATC was not told.

### M3. README says Python 3.7+, but the pinned `hoppie-connector` requires Python 3.12+
- **Severity**: Medium — the only prerequisite stated for the documented "Install from Source" path is wrong by five minor versions; the install fails before the app can start.
- **Confidence**: Confirmed
- **Location(s)**: `README.md:28-30`, `requirements.txt:1`, `app.py:63`, `.github/workflows/tests.yml:21`, `.github/workflows/build-and-release.yml:24`
- **What is wrong**: `hoppie_connector-0.2.1.dist-info/METADATA` declares `Requires-Python: >=3.12`, and its source uses `str | None` (3.10), `match` (3.10), `enum.StrEnum`, `typing.Self`, `datetime.UTC` (all 3.11). `app.py` also relies on `threading.excepthook` (3.8). CI runs on 3.13. On Python < 3.12 `pip install -r requirements.txt` reports "No matching distribution found for hoppie-connector==0.2.1".
- **Failure scenario**: A user on Python 3.9–3.11 follows README steps 1–3 and gets a pip resolution error with no hint that the README's version claim is the cause.
- **Evidence**: `README.md:30`: `- Python 3.7 or higher`; METADATA: `Requires-Python: >=3.12`.
- **Suggested fix direction**: State "Python 3.12 or higher" (matching what CI tests), and consider adding a `python_requires`-style check at the top of `app.py` that prints a clear message.

### M4. A source checkout identifies itself as version 0.1.0, so every launch shows a bogus "update available" dialog whose "Yes" closes the app
- **Severity**: Medium — happens on every start of the documented source install (until the user finds and disables auto-check); the affirmative answer terminates the program.
- **Confidence**: Confirmed
- **Location(s)**: `src/config.py:14-15`, `src/utils/update_checker.py:25, 112-125, 143-150`, `.github/workflows/build-and-release.yml:40-41`, `sim-cpdlc.iss:5`, `version_info.txt:9-10, 34, 39`
- **What is wrong**: `APP_VERSION = "0.1.0"` is what is checked in, and it is "0.1.0" at every tag from v2.0.0 to v2.1.2 (verified with `git show <tag>:src/config.py`); `update_version.py` rewrites it only inside the release workflow, and the change is never committed back. The three checked-in version strings also disagree with each other (config 0.1.0, `.iss` 0.3.1, `version_info.txt` 0.1.0) and with the latest release tag v2.1.2. `packaging.version.parse("2.1.2") > parse("0.1.0")` is True, so `_is_newer_version` always fires for anyone running `python app.py`.
- **Failure scenario**: `git clone` → `python app.py` → after a few seconds "A new version of Sim-CPDLC is available! Current version: 0.1.0 / Latest version: 2.1.2" → Yes → browser opens the release page and `wx.CallAfter(self.parent.Close)` closes the app the user just started. About dialog shows 0.1.0, so bug reports from source users carry a useless version.
- **Evidence**: `config.py:15`: `APP_VERSION = "0.1.0"`; `update_checker.py:150`: `wx.CallAfter(self.parent.Close)`.
- **Suggested fix direction**: Make the tag the single source of truth and commit the bump (release workflow commits `update_version.py` output, or the maintainer runs it before tagging), or derive `APP_VERSION` from `git describe` when not frozen and skip the auto-check when the version is a development one. Keep the three strings identical in the tree.

### M5. Dialogs validate on stripped text but return unstripped text, so an invisible leading/trailing space passes the OK gate and then fails with a confusing error
- **Severity**: Medium — affects the most common flows (Logon, Telex, PDC, Connect); the stray space is exactly what a screen-reader user cannot see, and the resulting message contradicts the dialog that just accepted the input.
- **Confidence**: Confirmed (library rejects `" EDDF"`/`"EDDF "`: `Invalid TO station name`; `on_logon` rejects with its own message)
- **Location(s)**: `src/gui/dialogs/logon_dialog.py:44-60`, `telex_dialog.py:52-74`, `pdc_dialog.py:137-171`, `connect_dialog.py:167-214`, `settings_dialog.py:171-186`; consumer `src/gui/main_window.py:418-428`
- **What is wrong**: Every `on_text_change` calls `.strip()` before checking length/emptiness, but the `get_*_details()` methods return `GetValue().upper()` (or raw `GetValue()`) without stripping. `hoppie_connector` validates station names with `^[A-Z0-9]{3,8}$` (Utilities.py:4) so any whitespace is fatal at send time. The Logon dialog is the worst case: "EDDF " enables OK, then `on_logon` measures `len(station) != 4` on the unstripped value and shows "Station name must be exactly 4 characters long." even though the user typed four letters. Settings saves logon codes with surrounding whitespace, which then makes every connection fail with the server's "invalid logon" until the user notices.
- **Failure scenario**: Requests > Logon, type "EDDF" followed by an accidental space, OK is enabled, press Enter → "Invalid Station Name: must be exactly 4 characters long". Telex: recipient "EDDF " → "Failed to send telex message to EDDF : Invalid TO station name." PDC: origin " EDDF" → "Failed to send PDC request to  EDDF: Invalid TO station name." Connect: callsign "DLH123 " → "Connection failed: Invalid FROM station name".
- **Evidence**:
  ```python
  # logon_dialog.py:48 vs :60
  if len(self.station_text.GetValue().strip()) == 4:
  ...
  return self.station_text.GetValue().upper()
  ```
- **Suggested fix direction**: Strip in every getter (and in `SettingsDialog.get_settings`), or normalise once in the dialogs' `EVT_TEXT` handler. `on_logon`'s length re-check then becomes redundant.

### M6. SimBrief is fetched synchronously inside the Connect and PDC dialog constructors, freezing the GUI (up to 10 s) before the dialog even appears
- **Severity**: Medium — a blind user gets silence for up to 10 s after choosing Connect, with no indication anything is happening; it repeats on every open of either dialog.
- **Confidence**: Confirmed
- **Location(s)**: `src/gui/dialogs/connect_dialog.py:56-90`, `pdc_dialog.py:47-106`, `src/utils/simbrief.py:28-32` (`timeout=10`); related: `src/utils/update_checker.py:38-40, 53-78, 97` (manual check, synchronous, 5 s), `src/gui/main_window.py:734` (manual weather request, synchronous, 15 s)
- **What is wrong**: `get_latest_ofp()` performs a blocking `requests.get` from `__init__`, before `ShowModal`. While it runs, the main window does not repaint and NVDA reports nothing. The automatic weather path already uses a worker thread for the same class of call, so the synchronous manual weather request and the synchronous manual update check are inconsistent with it. (Polls/sends being synchronous with the 15 s `NETWORK_TIMEOUT` is documented design and not counted here, but it means a dead link can freeze the UI for 15 s per poll during an outage.)
- **Failure scenario**: SimBrief slow or unreachable (or a wrong user id producing a slow 4xx) → File > Connect → no dialog, no sound, no focus change for up to 10 s → then a "Could not fetch flight plan from SimBrief." warning box → then the Connect dialog.
- **Evidence**: `connect_dialog.py:62`: `ofp_data = get_latest_ofp(simbrief_userid)` inside `__init__`.
- **Suggested fix direction**: Show the dialog first and fill the callsign/ICAO fields from a worker thread via `wx.CallAfter` (disable OK or show "Fetching SimBrief…" in the meantime), or cache the OFP per session. Same pattern for the manual update check and manual weather request.

---

## Low

### L1. Altitude dialog validates with `int()`, which accepts `+350`, `3_50`, full-width/Arabic digits and unpadded two-digit levels
- **Severity**: Low — malformed input reaches the wire in one case and produces confusing library errors in others; needs unusual typing.
- **Confidence**: Confirmed (run: `int("3_50") == 350`, library accepts `REQUEST FL3_50`, rejects `FL+350` and `FL٣٥٠`)
- **Location(s)**: `src/gui/dialogs/altitude_change_dialog.py:72-85, 94-98`
- **What is wrong**: `int(altitude)` tolerates a sign, underscores and any Unicode decimal digits; the raw text is then prefixed with "FL". `CpdlcMessage` allows underscores (`[A-Z0-9\.\_\@ ]`), so `3_50` is transmitted as `REQUEST FL3_50`, while `format_list_text` strips underscores for display, so the pilot's own message list shows `REQUEST FL350`. `+350`/Unicode digits pass the dialog and fail in the library with "Message contains invalid characters". Two-digit levels are sent as `FL50` rather than `FL050`.
- **Failure scenario**: Type "3_50" (or paste) → OK enabled → controller receives `REQUEST FL3_50`; the sender sees `REQUEST FL350` locally and cannot tell what went wrong.
- **Evidence**: `altitude_change_dialog.py:79`: `fl = int(altitude) if altitude else 0`
- **Suggested fix direction**: Validate with a regex `^\d{2,3}$` on ASCII digits (`str.isascii() and str.isdigit()`), and zero-pad to three digits.

### L2. Direct-to dialog rejects legitimate fixes containing digits, while accepting non-ASCII letters the library rejects
- **Severity**: Low — blocks a valid request class (lat/long or alphanumeric waypoints) but the pilot can fall back to a telex.
- **Confidence**: Confirmed (`"55N020W".isalpha()` False; `"ÄBCDE".isalpha()` True; library accepts `REQUEST DIRECT TO 55N020W`, rejects `ÄBCDE`)
- **Location(s)**: `src/gui/dialogs/direct_request_dialog.py:28-30, 62-68`
- **What is wrong**: `2 <= len(fix) <= 5 and fix.isalpha()` excludes oceanic lat/long positions (`55N020W`, `5230N`), alphanumeric terminal waypoints (`DF123`, `OM25L`) and anything longer than five characters, none of which the CPDLC element or the library forbids; `isalpha()` meanwhile admits Unicode letters that fail at send time.
- **Failure scenario**: Oceanic flight wants "REQUEST DIRECT TO 55N020W" → OK never enables → no way to send it except free-text telex.
- **Evidence**: `direct_request_dialog.py:65`: `if 2 <= len(fix) <= 5 and fix.isalpha():`
- **Suggested fix direction**: Accept `^[A-Z0-9]{2,7}$` (ASCII) and update the helper text.

### L3. Speed / When-can-we dialogs use `str.isdigit()`, which admits non-ASCII digits; Speed dialog's Mach and knots branches are identical
- **Severity**: Low — edge input; the library error is at least shown.
- **Confidence**: Confirmed (`"٣٠٠".isdigit()` True)
- **Location(s)**: `src/gui/dialogs/speed_request_dialog.py:88-106`, `when_can_we_dialog.py:113-117`
- **What is wrong**: Unicode digits pass validation and fail in `CpdlcMessage`; the Mach/knots branches (95-106) contain the same check twice, so the comment "Mach: 2-3 digits" vs "Knots: 2-3 digits" documents a distinction the code does not make. Mach `820` is accepted and sent as `REQUEST M820`.
- **Evidence**: `speed_request_dialog.py:91`: `if not speed.isdigit():`
- **Suggested fix direction**: `speed.isascii() and speed.isdigit()`; collapse the branches; consider `0\d\d` for Mach.

### L4. `_check_first_launch` posts `on_settings` before the collaborators it uses exist; correct today only by event-loop ordering
- **Severity**: Low — currently safe on the normal path; fragile.
- **Confidence**: Plausible (whether the pending event can run inside the native missing-sound `wx.MessageBox` at :88 was not verified; if it can, the first-launch settings save raises `AttributeError: weather_monitor` and the settings are not saved)
- **Location(s)**: `src/gui/main_window.py:79, 82-89, 115-123, 237-296 (278), 1125-1161 (1158)`
- **What is wrong**: `__init__` calls `_check_first_launch()` (which does `wx.CallAfter(self.on_settings, None)`) before `_init_ui()`, before `update_checker`, and before `self.weather_monitor` is created; `on_settings` dereferences `self.weather_monitor` at :278. It works because `wx.CallAfter` posts to the app's pending queue (verified in `wx.core.CallAfter`) which is drained by `MainLoop`, after `__init__` returns. The welcome dialog is also parented to a frame that has no menu, status bar or size yet and is not shown.
- **Failure scenario**: First launch from a checkout run outside the repo root (see L7) → welcome dialog → Yes → sound-missing message box → if pending events are dispatched inside that native loop, Settings opens and "Save" crashes with `AttributeError` reported by the unhandled-exception dialog; nothing saved.
- **Evidence**: `main_window.py:79` `self._check_first_launch()` precedes `:117` `self.weather_monitor = WeatherMonitor(...)`.
- **Suggested fix direction**: Move `_check_first_launch()` to the end of `__init__` (after `Show`), or construct the model/controller objects before it.

### L5. Settings: the new weather interval is applied to the running monitor before the save is known to succeed
- **Severity**: Low — only diverges when `save_config` fails; then the running value and the file disagree until restart.
- **Confidence**: Confirmed
- **Location(s)**: `src/gui/main_window.py:277-292`
- **What is wrong**: `self.weather_monitor.set_interval(...)` at :278 runs before `save_config(config)` at :279; on failure the user is told "Failed to save settings" but the interval has already changed for the session, and the message "Settings saved successfully. The new settings will be used for future operations" is slightly misleading in the success case too (the interval takes effect immediately, the codes only on the next Connect, `auto_tune_com1` on the next message).
- **Suggested fix direction**: Apply runtime changes inside the `if save_config(config):` branch; word the confirmation accordingly.

### L6. `load_config`/`save_config` log the whole config — both logon codes included — at DEBUG, and the config is re-read from disk on every message
- **Severity**: Low — no leak at the default INFO level, but it undermines the `redact()` policy the rest of the code follows, and one flip of the log level (there is no setting for it, so a developer edit) writes credentials into the rotating log.
- **Confidence**: Confirmed
- **Location(s)**: `src/config.py:52, 85`; `src/gui/main_window.py:1010` (also `:98, :242`, `connect_dialog.py:27`, `pdc_dialog.py:27`); `src/model/connection_manager.py:61-73` (the redaction policy)
- **What is wrong**: `logger.debug(f"Loaded config: {config}")` / `f"Saved config: {config}"` include `sayintentions_logon_code` and `hoppie_logon_code`. `_on_message_received` calls `load_config()` (disk read + that debug line) for every message from the current station just to read one boolean.
- **Suggested fix direction**: Log only the key names or a redacted copy; cache `auto_tune_com1` on the window and refresh it when Settings is saved.

### L7. `resource_path()` resolves relative to the current working directory in development mode
- **Severity**: Low — only affects source runs started from another directory; produces a startup warning box every time and no notification sound.
- **Confidence**: Confirmed by reading
- **Location(s)**: `src/gui/main_window.py:56-64, 82-89`; `README.md:43-46`
- **What is wrong**: `base_path = os.path.abspath(".")` when not frozen; `python C:\path\to\sim-cpdlc\app.py` from elsewhere (shortcut, IDE run configuration, scheduler) cannot find `assets/message.wav`.
- **Suggested fix direction**: Use the directory of `app.py` (`os.path.dirname(os.path.abspath(sys.argv[0]))` or a module-relative path) as the development base.

### L8. Stopping a subscription from the "Automatic weather updates" dialog gives no confirmation message, unlike the other two stop paths
- **Severity**: Low — feedback inconsistency that lands hardest on screen-reader users.
- **Confidence**: Confirmed
- **Location(s)**: `src/gui/dialogs/weather_subscriptions_dialog.py:131-157`; compare `src/gui/main_window.py:728-732, 886-891`
- **What is wrong**: `on_stop`/`on_stop_all` call `unsubscribe()`/`clear()` and refresh the list; the context-menu and request-dialog paths add a "Stopped automatic updates for METAR EGLL" SYSTEM message and set the status bar. From the dialog, the only evidence is that the list entry vanished (or the dialog is left open with an empty list after Stop all).
- **Suggested fix direction**: Route the dialog's stop actions through the same `MainWindow._on_toggle_weather_updates`-style helper, or pass a callback that adds the SYSTEM message.

### L9. Frequency parser requires a unit name between CONTACT/MONITOR and the frequency, and its DOTALL comment is wrong
- **Severity**: Low — auto-tune silently does nothing for a unit-less instruction; the message itself is still shown.
- **Confidence**: Plausible (whether either network emits "CONTACT 121.500" without a unit name was not verified; the regex behaviour was)
- **Location(s)**: `src/utils/frequency_parser.py:7-14`
- **What is wrong**: `.+?\s+` demands at least one token before the frequency, so `CONTACT 121.500` and `CONTACT 121.500 MHZ` return None (verified), while every realistic text with a unit name (`CONTACT MAASTRICHT 132.850 MHZ`, `MONITOR UNICOM 122.8`, `CONTACT LONDON CONTROL 127.425 WHEN READY`, 8.33 kHz `132.855`, `CLIMB TO FL350 CONTACT …`, two-frequency texts → first) parses correctly. The comment "DOTALL so \s+ matches newlines" is inaccurate: `\s` always matches newlines; DOTALL is what lets `.+?` span them. There is no unit test for this module.
- **Suggested fix direction**: Make the unit-name group optional (`(?:.+?\s+)?`) and add a `tests/test_frequency_parser.py` with the cases above.

### L10. Message list columns are auto-sized once, before any rows exist, and never resized
- **Severity**: Low — sighted users may see clipped Sender/Message cells; screen readers still get the full text.
- **Confidence**: Plausible (wxMSW behaviour of `LIST_AUTOSIZE` with zero rows not verified in a live window)
- **Location(s)**: `src/gui/message_view.py:56-62, 77-89`
- **What is wrong**: `InsertColumn(…, width=-1)` (`wx.LIST_AUTOSIZE`, verified value) is evaluated when the list is empty; `add_message` never calls `SetColumnWidth`, so the widths do not follow the content.
- **Suggested fix direction**: Use `LIST_AUTOSIZE_USEHEADER` for Sender, give Message a proportional width in an `EVT_SIZE` handler, or call `SetColumnWidth(1, wx.LIST_AUTOSIZE)` after inserting.

### L11. `@@` → `N/A` substitution is not space-padded, gluing words together
- **Severity**: Low — affects display/readability only, and only when `@@` occurs in CPDLC text.
- **Confidence**: Plausible (frequency of `@@` in real uplinks unknown; behaviour verified)
- **Location(s)**: `src/utils/message_formatting.py:25-30, 39-41`
- **What is wrong**: `"CLIMB TO@FL350@@REPORT LEVEL"` renders as `CLIMB TO FL350N/AREPORT LEVEL` in the list and `FL350N/AREPORT LEVEL` in the detail pane; NVDA reads "FL350N slash AREPORT".
- **Suggested fix direction**: Replace with `" N/A "` and collapse whitespace, or drop the substitution if it no longer corresponds to observed traffic.

### L12. `on_disconnect` blocks the GUI with `wx.MilliSleep(500)` for nothing and bumps polling just before stopping it; comment is misleading
- **Severity**: Low — half a second of frozen UI on every logged-on disconnect; no functional effect.
- **Confidence**: Confirmed
- **Location(s)**: `src/gui/main_window.py:383-386`
- **What is wrong**: `send_cpdlc` is synchronous (`requests.post` has returned before `logoff()` returns), so "Small delay to allow the message to be sent" describes nothing real; `set_active_polling()` immediately followed by `polling_controller.stop()` is a no-op pair.
- **Suggested fix direction**: Delete both lines and the comment.

### L13. Update dialog does not say that "Yes" closes the application
- **Severity**: Low — surprising, and mid-flight it triggers the exit path (the exit confirmation appears only if connected).
- **Confidence**: Confirmed
- **Location(s)**: `src/utils/update_checker.py:134-150`
- **What is wrong**: The prompt asks "Would you like to download the update now?"; on Yes it opens the browser and `wx.CallAfter(self.parent.Close)`. When not connected, the app closes with no further question.
- **Suggested fix direction**: Say so in the prompt ("…and close Sim-CPDLC?") or do not close; let the user finish.

### L14. Console log handler is dead weight in the windowed build (`sys.stderr` is None), while the SimBrief module's logger never reaches the file at all
- **Severity**: Low — diagnostics only, but it means the one place that knows *why* a SimBrief fetch failed writes nowhere.
- **Confidence**: Confirmed for the logger name (no handler on `src.utils.simbrief`, `propagate` to a root with no handlers → `logging.lastResort`, WARNING+ to stderr only); Plausible for `sys.stderr is None` under PyInstaller `console=False` (PyInstaller not installed in the review venv)
- **Location(s)**: `src/utils/simbrief.py:8, 46-60`, `src/logging_setup.py:12-27`, `src/gui/dialogs/connect_dialog.py:77-83`, `pdc_dialog.py:93-99`, `app.spec:59`
- **What is wrong**: `simbrief.py` is the only module using `logging.getLogger(__name__)`; `setup_logging` configures only "Sim-CPDLC". `fetch_ofp` swallows every exception and returns None, logging the reason (timeout, HTTP status, JSON error) to the orphan logger. The dialogs then log the uninformative "Failed to fetch SimBrief OFP data". In the frozen build `StreamHandler()` wraps `sys.stderr`, which is None for a windowed process, so every record also takes the `handleError` path silently.
- **Suggested fix direction**: `logging.getLogger("Sim-CPDLC")` in `simbrief.py` (or make it a child `"Sim-CPDLC.simbrief"`), and only add the console handler when `sys.stderr` is not None.

### L15. Personal SimBrief data and a live-API script are committed under `src/`
- **Severity**: Low — repository hygiene; the data is the maintainer's own but includes a real name, SimBrief user id and a complete OFP (164 KB), and the script overwrites it on run.
- **Confidence**: Confirmed
- **Location(s)**: `src/utils/latest_simbrief_ofp.json` (since the initial commit), `src/utils/test_simbrief.py:20, 42-47`, `pytest.ini:2-4`, `.gitignore`
- **What is wrong**: `test_simbrief.py` hard-codes user id `189007` and writes `latest_simbrief_ofp.json` next to itself; the JSON contains `crew.cpt = "ROBIN KIPP"`, `params.user_id`, `api_params.cpt`, full route/fuel data. `pytest.ini` exists partly to keep pytest from collecting the script. Neither file is used by the application.
- **Suggested fix direction**: Delete both (or move the script to `tools/` reading the id from an environment variable) and add `src/utils/latest_simbrief_ofp.json` to `.gitignore` if the script stays.

### L16. Packaging/requirements inconsistencies
- **Severity**: Low — none breaks the current release, but each is a latent surprise.
- **Confidence**: Confirmed
- **Location(s)**: `requirements.txt:2, 7`, `app.spec:11-18, 35`, `.gitignore:1-6`, `.github/workflows/build-and-release.yml`, `.github/dependabot.yml`
- **What is wrong**:
  - `pyinstaller==6.20.0` is in the *runtime* requirements, so every source user installs a build tool; conversely `pytest` is correctly split out.
  - `SimConnect>=0.4.26` is the only unpinned dependency (PyPI's latest is 0.4.26, verified), and it is absent from the review venv that otherwise satisfied `requirements.txt` — a build machine without it produces an installer in which auto-tune silently never works (`app.spec` bundles `SimConnect.dll` only `if os.path.isfile(_sc_dll)`, and PyInstaller only warns about a missing hidden import).
  - `.gitignore` lacks `installer/` (Inno's `OutputDir`), `.pytest_cache/`.
  - The release workflow does not run the test suite before building; `fetch-depth: 0` is unused; dependabot covers pip but not the GitHub Actions used.
- **Suggested fix direction**: Split `requirements-build.txt`, pin `SimConnect==0.4.26`, fail the build if the DLL is not found, extend `.gitignore`, add a `needs: test` job to the release workflow.

### L17. README describes behaviour the code does not have
- **Severity**: Low — documentation drift.
- **Confidence**: Confirmed
- **Location(s)**: `README.md:20, 84-91, 109-110, 149-158`; `tests/README.md:17-30`; `app.py:3`; `src/gui/dialogs/about_dialog.py:18`
- **What is wrong**:
  - "Requesting Altitude Changes … Select: Desired altitude, Climb or descent" — the dialog has no climb/descent choice; the message is `REQUEST FL350`.
  - "The report is added to the message list and the notification sound plays" — `_add_weather_message` defaults to `play_sound=False` for a requested report, and `test_a_report_the_pilot_asked_for_arrives_quietly` pins that.
  - "Automatic Reconnection: Handles connection issues gracefully" — one attempt after three failures, then polling stops and the user must reconnect by hand (see M1).
  - The tests table omits `test_config.py` and `test_weather_parsing.py`.
  - `app.py` docstring: "A simple CPDLC client for SayIntentions.ai" (Hoppie is the other half).
- **Suggested fix direction**: Align the README with the dialogs and the sound policy; regenerate the tests table.

### L18. Protocol-state handling is keyed on duck-typed text, so a TELEX whose body is "LOGON ACCEPTED", "HANDOVER XXXX" or "LOGOFF" can change the session
- **Severity**: Low — requires a station to send those exact words as free text; consequence is a wrong logon state.
- **Confidence**: Plausible
- **Location(s)**: `src/gui/main_window.py:926-928, 946-1007`
- **What is wrong**: The branch is gated on `hasattr(message, "get_packet_content") and hasattr(message, "get_from_name")`, which every `HoppieMessage` (telex, progress, ADS-C) satisfies; only `get_mrn` is conditional. A `TelexMessage("EDDF", …, "LOGON ACCEPTED")` therefore calls `handle_logon_accepted("EDDF", None)` and, with no logon pending, is accepted.
- **Suggested fix direction**: Gate the LOGON ACCEPTED / HANDOVER / LOGOFF handling on `isinstance(message, CpdlcMessage)` (already imported and currently unused); keep the auto-tune branch for telex if desired.

### L19. Logging on to a second station while logged on neither logs off the first nor updates state until acceptance, and restarts the MIN counter mid-dialogue
- **Severity**: Low — unusual pilot action; the status bar then says "Pending logon to B" while `is_logged_on()` still returns A.
- **Confidence**: Confirmed by reading
- **Location(s)**: `src/model/cpdlc_session.py:62-106` (`:85` resets `cpdlc_min_counter = 1`), `src/gui/main_window.py:404-449`
- **What is wrong**: `logon()` does not require `current_station` to be empty; it resets the MIN counter to 1 while the dialogue with the old station continues (an acknowledgement sent to the old station in the meantime would reuse MINs it has already seen), and if the new station never answers the app stays logged on to the old one under a "Pending logon" status. `pending_logon_*` is never expired.
- **Suggested fix direction**: Either send LOGOFF to the current station first (as the HANDOVER path effectively does) or ask for confirmation; clear `pending_logon_*` on user logoff/disconnect.

---

## Info (code quality; no direct user-visible effect)

### I1. Unused imports
- **Confidence**: Confirmed (AST scan)
- `src/gui/main_window.py:9-14`: `CpdlcMessage`, `CpdlcResponseRequirement as RR`, `HoppieMessage` (the `hasattr` checks in `_on_message_received` are what these would replace).
- `src/model/cpdlc_session.py:3-4`: `logging`, `Callable`.
- `src/controller/polling_controller.py:5`: `logging`.

### I2. Dead code and dead parameters
- `MessageManager.get_weather_key` (`src/model/message_manager.py:164-174`) has no caller.
- `PollingController.default_poll_interval` (`polling_controller.py:30, 41-42, 52`) is stored and never read; `DEFAULT_POLL_INTERVAL` is threaded from `config.py` through `main_window.py:110` for nothing, and the docstring "used only when a jitter range is not available" describes a path that cannot occur (`poll_interval_range` always falls back to the config band).
- `ConnectionManager.message_callback` (`connection_manager.py:94-116`) is never used.
- `poll_status` from `cnx.poll()` is discarded (`connection_manager.py:286-295`, `polling_controller.py:149`).
- `extract_atis_letter(text, icao=None)` keeps an ignored parameter (`weather_parsing.py:141-176`) — documented as "call-site compatibility", but all call sites are in-repo.
- `self.menu_item_logoff` (`main_window.py:185-188`) is an attribute only so it can be bound; the comment "Always enable both logon and logoff menu items" describes code that no longer exists.
- `is_running()` docstring aside, `PollingController.parent_window` is only read by `_set_status`, which duck-types `SetStatusText` (`:202`).

### I3. Duplication the PR-24 spec left open, still open
- Seven handlers hand-roll the "Not Connected" message box (`main_window.py:407-413, 495-501, 537-543, 574-580, 613-619, 663-669, 800-806`) though `_require_connection` (`:692-709`) exists and is used once; five hand-roll "Not Logged On" (`:503-509, 545-551, 582-588, 621-627` plus `on_logoff`).
- `CpdlcSession.send_altitude_change_request`, `send_direct_request`, `send_speed_request`, `send_when_can_we_expect` (`cpdlc_session.py:154-197, 264-368`) differ only in the message text; the guard/try/increment/return block is repeated four times.
- `_on_message_received` repeats the `hasattr`/`extract_message_content`/`@`-normalisation block twice (`main_window.py:926-934` and `:946-953`).
- `_check_first_launch` re-imports `os`, `load_config`, `save_config` inside the function (`main_window.py:1127-1128`); `os` is already a module import and the two functions are unused there. (Note this local import would also bypass the `mw.load_config` monkeypatch the tests rely on, were the method not stubbed entirely.)
- `SpeedRequestDialog.on_text_change` identical branches (see L3).

### I4. Indirection with no purpose
- `CpdlcSession.send_logoff_message` (`cpdlc_session.py:143-152`) is an alias "kept for backward compatibility" in an application with no external callers; both call sites (`main_window.py:380, 1085`) could call `logoff()`.
- `MainWindow.get_current_station` (`main_window.py:648-658`) wraps `cpdlc_session.get_current_station()` behind an `is_logged_on()` check that is by definition equivalent (`is_logged_on` is `bool(current_station)`); its only consumer is `TelexDialog`, which reaches into `parent.get_current_station()` (`telex_dialog.py:27-28`), coupling the dialog to the MainWindow API instead of taking the value as a constructor argument.
- `resource_path` is an instance method that never uses `self` (`main_window.py:56-64`).

### I5. `hasattr` duck typing where `isinstance` is available
- `main_window.py:926-928, 946-948, 958`; `polling_controller.py:202`. `HoppieMessage`/`CpdlcMessage` are imported in `main_window.py` for exactly this and unused (see L18 for the one behavioural consequence).

### I6. Inconsistent logger acquisition
- A logger is injected into models/controller/window; `ConnectDialog`, `PDCDialog`, `config.py`, `simconnect_manager.py`, `update_checker.py` fetch `logging.getLogger("Sim-CPDLC")`; `simbrief.py` uses `__name__` (the one that actually misbehaves, L14).

### I7. Accessibility conventions are applied unevenly
- Mnemonics (`&`) and `SetName` are used in `WeatherDialog` and `WeatherSubscriptionsDialog` and on the Settings spin control only; `Connect`, `Logon`, `PDC`, `Altitude`, `Direct`, `Speed`, `When can we`, `Telex`, `Settings` text fields rely on the preceding `StaticText` for their accessible name (works with NVDA on MSW, but is the implicit form).
- `ConnectDialog` creates `wx.RadioBox(label="")` with a separate "Select Network:" static text (`connect_dialog.py:35-45`), so the group itself has no accessible name.
- Helper texts use a hard-coded grey `wx.Colour(100, 100, 100)` (`altitude:40`, `direct:31`, `speed:43`, `when_can_we:50`), low contrast and unaffected by high-contrast themes.
- Accelerators reuse OS conventions: `CTRL+S` (Speed change; Save), `CTRL+W` (When can we; Close), `CTRL+O` (Logoff; Open) — `main_window.py:186-199`. Harmless (a dialog opens) but surprising.
- Menu mnemonic uniqueness is tested (`tests/test_main_window.py:156-174`), which is good; the same check is not applied inside dialogs.

### I8. Test coverage gaps in this lens
- No tests for `src/utils/frequency_parser.py` or `extract_message_content`; `tests/README.md` table omits two existing files.

### I9. Smaller code-quality notes
- `WeatherMonitor.stop()` sets `_shutting_down = True` (`weather_monitor.py:120-125`); the flag name suggests process exit but it also gates plain disconnects and `check_now()` — fine functionally, misleading to read.
- `WeatherMonitor._post_result`/`_post_cycle_finished` read `self._parent.IsBeingDeleted()` from the worker thread (`:302-313`); a flag read, benign, but it is wx state touched off the GUI thread.
- `app.py:103-105` calls `frame.on_exit(None)` after `MainLoop()` has returned on `KeyboardInterrupt`, when the frame may already be destroyed (`RuntimeError: wrapped C/C++ object … has been deleted`); unreachable in the windowed build.
- Dialog handlers have no `try/finally` (or `with` context manager) around `ShowModal … Destroy`, so a non-`HoppieError` exception between them (e.g. the `FileNotFoundError` that `test_a_local_os_error_is_not_disguised_as_a_network_failure` deliberately lets escape) leaks the dialog.
- Type hints: `add_custom_message(self, text: str, sender: str = None)` (`message_manager.py:126`) should be `Optional[str]`; `connection_manager.py` is untyped while `cpdlc_session.py` is fully typed.
- `about_dialog.py:19` copyright year is fixed at 2025.

---

## Things I checked that are fine

- **`global` after use in `simconnect_manager.set_com1_standby_mhz` (:76-93)**: valid Python — the name is not referenced earlier *in that function*, and a `global` statement applies to the whole function body; the module compiles (verified). Availability caching/reset logic and the two-attempt retry are coherent; `_warned_unavailable` prevents log spam.
- **First-launch flow**: on the normal path `wx.CallAfter(self.on_settings, None)` runs from `MainLoop`, after `__init__` has created `weather_monitor`; `save_config` creates the file before the settings dialog reads it; `on_settings` destroys its dialog on both branches (see L4 for the ordering fragility only).
- **Settings while connected**: `set_interval` stops/restarts the timer correctly; `weather_interval_minutes()` clamps type and range on every read (bool excluded); the SpinCtrl is bounded 1–60 and `SettingsDialog` passes an already-clamped initial value.
- **Exit paths**: `on_close` vetoes correctly when the user declines while connected; sends LOGOFF, stops polling, shuts the weather monitor down (timer destroyed), disconnects SimConnect, then `Skip()`s; `on_exit` → `Close()` → same path; the update checker's `Close` goes through the same confirmation when connected; background threads guard `IsBeingDeleted()` before `CallAfter`.
- **PollingController**: one-shot rescheduling in `finally`, `set_active_polling` only pulls a poll forward, reconnection-failure branch stops deliberately and `_schedule_next` respects `_stopped`; `should_increase_polling_rate` shares `CPDLC_RESPONSES` with `MessageManager`.
- **Connect → logon → handover → LOGOFF → logoff → disconnect (happy path)**: status bar, menu label, session station and weather monitor stay consistent; `LOGON ACCEPTED` validation against the pending station/MRN is right and unsolicited acceptances still work; HANDOVER regex operates on `@`-normalised text.
- **Message encodings**: `"sender: text"` is split on the *first* `": "`, so texts containing `": "` round-trip whenever the sender is non-empty; an empty sender is only possible with an empty callsign, which every caller prevents by requiring a connection (verified `MessageManager` behaviour for `("FUEL: 5000","DLH123")`, SYSTEM messages containing `": "`, and the theoretical empty-sender case). `WeatherReport` rows show label/`ICAO: text`, detail shows the `@`-split report; `add_message` drops nothing reachable.
- **Message types from `poll()`**: `TelexMessage`, `CpdlcMessage`, `ProgressMessage` and the ADS-C classes are all `HoppieMessage` subclasses with `get_from_name`/`get_packet_content`, so all display; only `CpdlcMessage` is answerable (`get_cpdlc_addressing`/`needs_acknowledgement` use `isinstance`); the library drops unparseable items with a warning rather than raising.
- **MessageView**: `LC_SINGLE_SEL`, `EVT_CONTEXT_MENU` (keyboard-reachable), popup handlers bound and unbound per menu (no accumulation), `SetItemData`/`GetItemData` with small ints, weather menu passes the on-screen text to seed change detection.
- **`extract_message_content` regex**: strips both `/data2/MIN/MRN/RR/` and `/data2/MIN//RR/` for every RR code the library emits (WU, AN, R, NE, N, Y); leaves non-CPDLC text untouched; handles `None`/`""`.
- **Frequency parser on realistic texts**: `CONTACT MAASTRICHT 132.850 MHZ`, `MONITOR UNICOM 122.8`, `CONTACT LONDON CONTROL 127.425 WHEN READY`, 8.33 kHz `132.855`, `CLIMB TO FL350 CONTACT …`, `… ON 128.250`, two frequencies (first wins), multi-line, HF (`8879`, `5.598` rejected), out-of-band `117.950`/`136.995` rejected, squawks not mistaken; the `@` separator is normalised by the caller before parsing (verified `CONTACT MAASTRICHT@132.850` → None only when unnormalised).
- **ATIS letter / signature**: D-ATIS designator, chained markers, NATO words, fallback with time group stripped — all behave as the tests claim; `format_report_text/line` remove `@`.
- **config.py**: atomic write via `mkstemp` + `os.replace`, tmp file removed on failure; `PermissionError` is caught by `except IOError` (alias of `OSError`); missing keys merged; import-time directory creation is a side effect but idempotent and needed by both config and logging.
- **Library limits surface**: 220-char/ASCII telex limits, station-name regex, invalid CPDLC characters all become `HoppieError` and reach an error dialog (with logon codes redacted).
- **Dialog `Destroy()`**: reached on every normal return path in every handler, including the early-return branch in `on_logon`.
- **WeatherDialog**: checkbox mirrors live subscription state until the user touches it; `on_weather_request` unsubscribes on an unchecked box regardless of fetch outcome and subscribes only after a successful fetch; ATIS is the deliberate default.
- **Packaging paths**: `app.spec` `datas=('assets/','assets')` matches `resource_path` under `_MEIPASS` in onedir mode; `sim-cpdlc.iss` copies `dist\Sim-CPDLC\_internal\*` (PyInstaller 6 layout); `OutputBaseFilename` matches the workflow's upload path; `update_version.py` regexes match the three files; tag `v*.*.*` → `${GITHUB_REF#refs/tags/v}` is correct; `version.parse(tag.lstrip("v"))` handles the `v` prefix.
- **The accepted WON'T FIX** (unbounded message log) is not reported.
