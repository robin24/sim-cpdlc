# Sim-CPDLC test-suite audit: test quality and coverage gaps

Repo: `C:\Claude\sim-cpdlc` at `9c06458` (main). Read-only audit; nothing in the repo was modified and the suite was not run (only `--collect-only`: 135 tests across 14 files).

Method: every file under `tests/` and `src/` plus `app.py`, `pytest.ini`, `tests/README.md`, `.github/workflows/tests.yml`, `requirements*.txt`, `TODOS.md`, the PR-24 spec, and `hoppie_connector` 0.2.1 (`__init__.py`, `API.py`, `Messages.py`, `Responses.py`, `CPDLC.py`, `Utilities.py`) were read in full. Claims marked *Confirmed* were checked either by reading both sides of the call or with small non-GUI Python snippets against the venv interpreter (Python 3.14.6, wxPython 4.2.5, requests 2.32.5, no `SimConnect` package installed).

Facts established by snippet that the findings rely on:

- The developer's real config exists at `C:\Users\robin\AppData\Local\Sim-CPDLC\Sim-CPDLC\config.json`, with `simbrief_userid` **set** and `auto_tune_com1: True` (only booleans were inspected).
- `conftest.uplink(sender, min_value, text, rr)` builds `/data2/<min>//<rr>/<text>`: the MRN is always `None`.
- `TelexMessage` has no `get_mrn`, and `extract_message_content("LOGON ACCEPTED")` returns the text unchanged.
- `format_message_text("...FL360@@REPORT LEVEL@_@THEN.@CONTACT")` returns `'CLIMB TO AND MAINTAIN FL360N/AREPORT LEVEL\nTHEN.\nCONTACT'`.
- `extract_contact_frequency("MONITOR 121.5")` returns `None`; `"CONTACT LANGEN RADAR 137.000"` returns `None`; `"CONTACT TOWER 118.10 WHEN READY"` returns `118.1`.

---

## 1. Findings

### HIGH

#### H1. The only end-to-end acknowledgement test throws away the response requirement and the own MIN it was written to protect

- **Severity:** High  **Confidence:** Confirmed
- **Location:** `tests/test_acknowledge_path.py:21-28`; production `src/model/cpdlc_session.py:226-233`; history `TODOS.md:66-74` (item 21, rated HIGH, "DONE").
- **What is wrong:** `test_wilco_is_sent_with_the_senders_own_min_as_mrn` unpacks the recorded frame as `recipient, _own_min, _rr, text, mrn` and asserts only `(recipient, text, mrn)`. The RR value (`RR.NO.value == "N"`) and the client's own MIN are deliberately discarded. No other test in the suite observes the RR of an acknowledgement (`test_downlink_requests.py` never sends one; `test_connection_manager.py` never sends a CPDLC frame at all).
- **Why it matters:** TODOS item 21 records that acknowledgements used to go out as `NE` and that "some ATC clients may not correctly process acknowledgements sent with `NE`". That fix has no regression test: reverting line 230 to `RR.NOT_REQUIRED.value` passes the whole suite. An unregistered WILCO is the single worst silent failure a CPDLC client can have. The own-MIN is equally unguarded: sending the ack with the *uplink's* MIN instead of the session counter would also pass.
- **Evidence:**
  ```python
  recipient, _own_min, _rr, text, mrn = connection.sent[-1]
  assert (recipient, text, mrn) == (STATION, "WILCO", 53)
  ```
- **Fix direction:** Assert the full frame: `connection.sent[-1] == (STATION, 1, RR.NO.value, "WILCO", 53)` (the session counter starts at 1 in `build()`), and add one test through the real `HoppieConnector` with a fake `requests.get` that captures `params["packet"]` and asserts the literal `/data2/1/53/N/WILCO`.

#### H2. Hermeticity is per-test patchwork, not a fixture boundary: the real config file, `save_config`, SimBrief and SimConnect are each one unpatched call away

- **Severity:** High  **Confidence:** Confirmed (mechanisms); no *current* test trips them
- **Locations:**
  - `tests/test_main_window.py:60-64` (`window` fixture patches `_check_first_launch`, `load_config`, `wx.MessageBox` only)
  - `tests/test_dialogs.py:13-25` (`dialog` fixture patches nothing)
  - `tests/conftest.py:94-115` (`make_main_window` patches nothing)
  - `src/config.py:19-28` (import-time `os.makedirs` of the real user data dir; `CONFIG_FILE` bound to the real path)
  - `src/gui/main_window.py:242,279` (`on_settings` reads via patched `load_config` but writes via **unpatched** `save_config`), `:1010` (`load_config()` on every uplink from the current station), `:1017` (`self.simconnect_manager.set_com1_standby_mhz`)
  - `src/gui/dialogs/connect_dialog.py:27,62,79-90`, `src/gui/dialogs/pdc_dialog.py:27,53,95-106` (real `load_config()` then live `get_latest_ofp()` then a modal `wx.MessageBox` on failure)
- **What is wrong:** Nothing redirects `src.config.CONFIG_FILE` to a temp path. Consequently:
  1. Every test run creates the real `%LOCALAPPDATA%\Sim-CPDLC\Sim-CPDLC` directory at import time (benign, but it is a real-environment side effect on every developer and CI machine).
  2. `window` fixture: `save_config` is not patched. The first test that drives `on_settings` (with `ShowModal` stubbed to `wx.ID_OK`) will `os.replace` the developer's real `config.json` with the patched defaults, wiping both logon codes and the SimBrief id. The fixture gives no warning.
  3. `dialog` fixture: `ConnectDialog(frame)` or `PDCDialog(frame)` reads the developer's real config, and because `simbrief_userid` **is** set on this machine, performs a live HTTPS request to simbrief.com (10 s timeout) and, on any failure, opens a **modal** `wx.MessageBox` that hangs the run. `tests/README.md:22` says this file covers "each request dialog", which invites exactly these tests.
  4. `make_main_window`: a HANDOVER, LOGOFF or CONTACT uplink from the current station reaches line 1010 and reads the developer's real config; with `auto_tune_com1: True` (the developer's actual value) and a frequency in the text, line 1017 dereferences `self.simconnect_manager`, which the fixture never sets. Through the real `window` fixture the same message would call the real `SimConnectManager`, which on a machine with MSFS running would retune COM1 standby in the live simulator.
- **Why it matters:** The task definition of High includes "a fixture that can corrupt the developer's real environment or reach the network". Each of these is a confirmed capability of an existing fixture, guarded only by the absence of a test, and the README actively steers contributors toward writing the tests that would trigger 2 and 3.
- **Evidence:** `tests/test_main_window.py:61-63`
  ```python
  monkeypatch.setattr(mw, "load_config", lambda: {**DEFAULT_CONFIG, "auto_check_updates": False})
  ```
  and `src/gui/main_window.py:279` `if save_config(config):` with no corresponding patch anywhere in `tests/`. `grep -n "save_config\|CONFIG_FILE" tests/*.py` returns nothing.
- **Fix direction:** One autouse fixture in `conftest.py`: `monkeypatch.setattr(src.config, "CONFIG_FILE", str(tmp_path / "config.json"))` (both `load_config` and `save_config` read the module global at call time, and `_check_first_launch`'s local `from src.config import CONFIG_FILE` also binds at call time, so this covers all three); `monkeypatch.setattr("src.utils.simbrief.get_latest_ofp", ...)` at the two dialog import sites (they import the name, so patch `src.gui.dialogs.connect_dialog.get_latest_ofp` and `...pdc_dialog.get_latest_ofp`); and an autouse `requests.get/post` guard that raises if reached without an explicit `serving()` patch. Give `make_main_window` a `FakeSimConnectManager` and an explicit config dict.

### MEDIUM

#### M1. `make_main_window` can only exercise one of the five branches of `_on_message_received`; three session-state transitions have no test at all

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/conftest.py:94-115`; `src/gui/main_window.py:919-1027`.
- **Attributes each branch touches, and what the fixture provides:**

  | Branch (lines) | MainWindow attributes touched | Fixture state | Tested? |
  |---|---|---|---|
  | `CURRENT ATC/ATS UNIT` filter (926-934) | `logger` | OK | **No** |
  | `LOGON ACCEPTED` (956-965) | `cpdlc_session`, `SetStatusText`, `logger` | OK | Yes (`test_logon_status.py`) |
  | `HANDOVER XXXX` from current station (968-1000) | `cpdlc_session` (logoff+logon+callsign), `message_manager`, `message_view`, `polling_controller`, `SetStatusText`, `logger`, then **module-level `load_config()` (real file)** at 1010 | Works, but reads the developer's real config | **No** |
  | `LOGOFF` from current station (1003-1007) | `cpdlc_session`, `SetStatusText`, `logger`, then real `load_config()` | Works, same caveat | **No** |
  | CONTACT/MONITOR auto-tune (1009-1027) | real `load_config()`, **`simconnect_manager` (never set by fixture)**, `SetStatusText`, `logger` | `AttributeError` | **No** (untestable as-is) |
  | message from a non-current station that is not `LOGON ACCEPTED` | nothing after `add_message` | OK | No (trivial) |

  `_on_acknowledge_message` (1029-1064): unknown id and success paths touch only fixture-provided attributes and are tested; the **failure path (1058-1064) calls `wx.MessageBox`**, which is neither patched nor backed by a `wx.App` in `test_acknowledge_path.py` (those tests do not request `wx_app`), so "a failed acknowledgement is reported to the user" is untestable through this fixture and is untested.

  Attributes the fixture never sets: `connection_manager`, `simconnect_manager`, `weather_monitor`, `update_checker`, `menu_item_connect`, `menu_item_logoff`, `panel`.
- **Why it matters:** HANDOVER is the automatic re-logon to the next sector; a regression there strands the pilot without a station mid-flight. The LOGOFF branch decides whether the context menu keeps offering WILCO to a station that has dropped you. TODOS item 23 (exact matching so `LOGOFF NOT REQUIRED...` does not log off) has no regression test.
- **Fix direction:** Extend `make_main_window` with `window.simconnect_manager = FakeSimConnectManager()` (records `set_com1_standby_mhz` calls) and patch `src.gui.main_window.load_config` to return a supplied dict; then add the branch tests listed in section 3.

#### M2. `test_every_menu_item_has_a_handler` cannot detect the failure its module docstring promises to catch

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_main_window.py:1-10, 22-40, 177-182`; `src/gui/main_window.py:219-235`.
- **What is wrong:** The docstring says "A handler renamed without its menu entry ... shows up here rather than as a dead menu item". The test only checks `callable(getattr(window, name))` for a hand-maintained list. Deleting any `self.Bind(wx.EVT_MENU, ...)` line (a genuinely dead menu item) passes, because the method still exists. Renaming a handler *and* its Bind passes production but fails the test spuriously. The comment "wx does not expose which handler a menu item is bound to" is not a blocker: `test_message_view.py:80-85` already drives menus by posting `wx.CommandEvent(wx.wxEVT_MENU, item.GetId())` through `ProcessEvent`, and the same technique works on the frame with each handler monkeypatched to a recorder.
- **Fix direction:** For every item in every menu, monkeypatch the expected handler with a recorder, `window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, item.GetId()))`, and assert exactly one recorder fired. This also removes the duplicated `MENU_HANDLERS` list.

#### M3. The MRN check on LOGON ACCEPTED is never exercised, and `test_logon_status.py` mislabels the MIN as the MRN

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_logon_status.py:15-16`; `tests/conftest.py:46-48`; `tests/test_cpdlc_session.py:17,27,37,46`; production `src/model/cpdlc_session.py:426-431`; `TODOS.md:89-92` (item 24).
- **What is wrong:** `_logon_accepted_from(station, mrn)` passes `mrn` as `uplink`'s `min_value`, so the message on the wire is `/data2/1//NE/LOGON ACCEPTED` (MIN 1, **MRN None**). `_on_message_received` therefore always calls `handle_logon_accepted(sender, mrn=None)`, which skips the MRN comparison. In `test_cpdlc_session.py` every call uses either `mrn=None` or `mrn=1` against `pending_logon_min == 1`, so the rejecting branch (`mrn != self.pending_logon_min`, lines 427-431) is never entered by any test. Real traffic is `/data2/1/1/NE/LOGON ACCEPTED`.
- **Why it matters:** Item 24 is marked DONE with no test; the one helper whose name says "mrn" does not set one. A future refactor could drop the MRN check unnoticed, and the status-bar tests would still pass.
- **Fix direction:** Give `uplink` an `mrn=None` keyword and forward it to `CpdlcMessage`; rewrite `_logon_accepted_from` to send `min=1, mrn=<pending MIN>`; add `handle_logon_accepted("EDDF", mrn=2)` with pending MIN 1 → `False`.

#### M4. Three of the six response-requirement rows are untested, including the two TODOS item 22 changed

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_message_manager.py:93-109` (covers `ROGER`, `NOT_REQUIRED`; `WILCO_UNABLE` elsewhere); production `src/model/message_manager.py:56-61`; `TODOS.md:76-82`.
- **What is wrong:** `RR.YES → ["YES","NO"]`, `RR.NO → []` and `RR.AFFIRM_NEGATIVE → ["AFFIRM","NEGATIVE","STANDBY"]` have no test. Item 22 says the previous code offered only `YES` for `Y` and wrongly offered `NO` for `N`; the fix has no regression test.
- **Fix direction:** One parametrised test over all six `CpdlcResponseRequirement` members asserting the exact list.

#### M5. `PollingController` reconnection branch and `_report_connection_state` are unreachable by every test fake

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_polling_controller.py:85-102,149-153,184-200` (all fakes hard-code `poll_failed() → False`, `should_attempt_reconnection() → False`); production `src/controller/polling_controller.py:137-140, 182-196, 205-217`.
- **What is wrong:** Untested: the not-connected tick that stops the timer (137-140); the "Connection problem (n/3) - retrying..." and "Connection restored." status texts (205-217); reconnection success → "Reconnected." and failure → "Connection lost. Reconnect to continue." followed by `stop()` (182-196); `_set_status` when the parent lacks `SetStatusText`. `test_a_poll_that_raises_still_schedules_the_next_one` proves the `finally` runs, but nothing proves the *deliberate* stop after a failed reconnection still ends polling (the comment at 144-146 says it should).
- **Why it matters:** TODOS item 1 (Critical) was "polling can silently stop while the status bar still reads Connected". The status texts asserted nowhere are the only signal a screen-reader user gets (`README.md`: NVDA+End on the status bar).
- **Fix direction:** A `FailingConnection` fake with settable `poll_failed`/`failure_count`/`should_attempt_reconnection`/`attempt_reconnection` and a parent recording `SetStatusText`; assert the exact texts and `is_running()` after each outcome.

#### M6. Context-menu tests assert that *a* menu popped, not what it offers or that its items fire the right response

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_message_view.py:49-58`; production `src/gui/message_view.py:146-165`; `TODOS.md:11` (item 2, Critical: handler accumulation).
- **What is wrong:** `test_menu_shown_for_a_message_from_the_current_station` asserts `len(panel.popped) == 1`. The stored object is a `wx.Menu` that `on_context_menu` destroys immediately afterwards, so nothing about its labels (`"Respond: WILCO"` ...) is or can be checked. The per-item lambda default-argument capture (`resp=response, mid=message_id`) and the post-popup `Unbind` (the fix for item 2) are unverified: a stale binding that fires the wrong response for a reused id would pass. The weather-menu test (61-90) shows the right pattern (drive each item through `ProcessEvent` inside the fake `PopupMenu`) but the CPDLC menu never got it.
- **Fix direction:** In the fake `PopupMenu`, capture `[item.GetItemLabelText() for item in menu.GetMenuItems()]` and assert `["Respond: WILCO","Respond: UNABLE","Respond: STANDBY"]`; fire the second item and assert `on_acknowledge` received `(message_id, "UNABLE")`; after `on_context_menu` returns, re-post the same event id and assert no second acknowledgement.

#### M7. The weather monitor's real threading path is only exercised by accident, and the cycle it starts is never awaited

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_weather_monitor.py:1-7, 32-36, 185-193`; production `src/model/weather_monitor.py:244-317`.
- **What is wrong:** The module docstring says the tests "drive the result path directly", which is true for `_on_result`. `_run_cycle`/`_fetch_worker`/`_post_result`/`_post_cycle_finished` are reached only by `test_check_now_says_a_cycle_started`, which asserts `check_now() is True` and returns while a real daemon thread is still running against `ScriptedConnection`. That thread calls `self._parent.IsBeingDeleted()` off the GUI thread and posts two `wx.CallAfter`s that are flushed (if at all) by the `wx_app` teardown's `SafeYield`, after `frame.Destroy()` has been queued. Nothing asserts the `announced` result of the cycle; the `_cycle_running` re-entrancy guard, the `_shutting_down` break, and the `_REQUEST_SPACING_SECONDS` pacing are untested. Also untested: `set_interval` (`weather_monitor.py:135-145`), `subscribe` on an existing key re-seeding `text`/`signature` (166-173), and `error_count` reset after a success (348) — the property that four failures, a success and four more failures must **not** drop the subscription. `test_repeated_failures_drop_the_subscription` (129-144) cannot tell `MAX_CONSECUTIVE_ERRORS == 5` from `== 1`.
- **Fix direction:** Make the worker deterministic: monkeypatch `threading.Thread` with a stub whose `start()` runs the target synchronously and `wx.CallAfter` with a direct call (or collect and replay), then assert `announced`, `_cycle_running` back to `False`, and that a second `check_now()` during a cycle returns `False`. Add the three unit tests named above and assert `count() == 1` after four failures.

#### M8. Every session-level failure path is unreachable because `FakeConnectionManager` never raises, and most downlinks are never formatted

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/conftest.py:51-71`; `tests/test_downlink_requests.py` (7 tests, 2 message formats); production `src/model/cpdlc_session.py:95-97,130-134,189-191,234-236,260-262,293-295,334-336,363-365,390-392,488-490`.
- **What is wrong:** Ten `except HoppieError: return False, str(exc)` branches and every corresponding `"Failed to send ..."` `wx.MessageBox` in `main_window.py` are uncovered. Untested formats: `logon` (`REQUEST LOGON`, `RR.YES`, counter reset to 1, pending state), `logoff` (`LOGOFF`, `RR.NOT_REQUIRED`, station cleared), `send_speed_request` (`REQUEST M082` vs `REQUEST 300K`), `send_when_can_we_expect` (passthrough), `send_telex`, `send_pdc_request` (`REQUEST PREDEP CLEARANCE <callsign> <type> TO <dest> AT <origin> STAND <n> ATIS <x>`, plus the `not self.callsign` precondition). `tests/README.md:23` claims "The exact text of every downlink the client can send"; the file's own docstring claims "the wire format" but asserts only the message element, never MIN/MRN/RR.
- **Fix direction:** Give `FakeConnectionManager` an optional `raise_with=HoppieError(...)`; add one literal-text test per send method (section 3) and one connector-level test capturing the real `packet` param.

#### M9. Nine of the ten dialogs have no test, and one of them cannot be built by the `dialog` fixture at all

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_dialogs.py` (WeatherDialog only); `src/gui/dialogs/telex_dialog.py:28` (`parent.get_current_station()` — a bare `wx.Frame` raises `AttributeError`); `tests/README.md:22`.
- **What is wrong:** LogonDialog (4-char rule, TODOS 17), PDCDialog (TODOS 15), AltitudeChangeDialog (10..600, TODOS 16, `FL` prefix), DirectRequestDialog (2-5 alpha), SpeedRequestDialog (Mach padding `82 → 082`; note it also accepts two-digit knots, producing `REQUEST 30K`, which a test would have flagged), WhenCanWeDialog (value field show/hide and the five text formats), TelexDialog, ConnectDialog (which logon code is sent when the field is hidden — a credential-routing decision, `connect_dialog.py:205-212`), SettingsDialog (`get_settings` round trip and SpinCtrl bounds), WeatherSubscriptionsDialog (stop / stop-all / check-now / plural text). Three of the low-numbered TODOS "DONE" items are dialog validation fixes with no regression test.
- **Fix direction:** Parametrised OK-button tests per dialog (set value → assert `ok_button.IsEnabled()`), plus `get_*_details()` literal assertions; give TelexDialog a `parent` stub with `get_current_station`; build ConnectDialog/PDCDialog only under the H2 config/SimBrief guards.

#### M10. `load_config` / `save_config` are untested

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_config.py` (only `weather_interval_minutes`); production `src/config.py:41-92`; `TODOS.md:21` (item 5, atomic write, "DONE").
- **What is wrong:** Missing-key back-fill, invalid-JSON fallback, IOError fallback, non-dict rejection, the temp-file-then-`os.replace` atomicity and the temp-file cleanup on failure have no test. These functions hold the logon codes; a regression corrupts or loses credentials.
- **Fix direction:** Redirect `CONFIG_FILE` to `tmp_path` (see H2) and test each branch; for atomicity, monkeypatch `os.replace` to raise and assert the original file is intact and no `*.tmp` remains.

#### M11. Four utility modules are entirely untested, two of them screen-reader- or simulator-facing

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `src/utils/frequency_parser.py` (0 tests), `src/utils/message_formatting.py` (0 direct tests), `src/utils/simconnect_manager.py` (0), `src/utils/update_checker.py` (0), `src/utils/simbrief.py` (0; `src/utils/test_simbrief.py` is a live-API script, excluded by `testpaths`).
- **What is wrong / evidence:** `format_message_text` and `format_list_text` produce `FL360N/AREPORT` for `FL360@@REPORT` (the `N/A` substitution has no surrounding spaces) and `LEVEL  THEN` (double space) — behaviour nobody has pinned, and this text is what NVDA reads. `extract_contact_frequency` decides what gets tuned into the simulator radio; the regex's range check, `ON`/`MHZ` handling, the `MONITOR 121.5` (no unit name) miss and multi-line messages are all unasserted. `SimConnectManager.set_com1_standby_mhz` has a retry that resets a module global; `UpdateChecker._is_newer_version` and the `IsBeingDeleted` guard from TODOS item 3 (Critical) are untested.
- **Fix direction:** Pure-function tests for the parsers/formatters (table-driven); fake `SimConnect` module in `sys.modules` for the manager; fake `requests.get` returning a GitHub JSON body for the checker.

#### M12. A TELEX whose body is `LOGON ACCEPTED`, `LOGOFF` or `HANDOVER XXXX` drives session state, and no test guards against it

- **Severity:** Medium  **Confidence:** Plausible (production defect surfaced by the audit; the code path is confirmed, exploitation depends on network behaviour)
- **Location:** `src/gui/main_window.py:946-1007`; `tests/` (no negative test).
- **What is wrong:** The session-state branches gate on `hasattr(message, "get_packet_content") and hasattr(message, "get_from_name")`, which `TelexMessage` satisfies. `extract_message_content` passes telex text through unchanged, so a telex reading `LOGON ACCEPTED` from any station calls `handle_logon_accepted(sender, mrn=None)` (the MRN check is skipped because telexes have no `get_mrn`) and, with no logon pending, sets `current_station` and announces "Logged on to X". Any network participant can send a telex to a callsign.
- **Fix direction:** Add `isinstance(message, CpdlcMessage)` to the gate; add tests that a telex with each of the three texts leaves `current_station` and `status_texts` unchanged.

#### M13. `test_context_menu_follows_the_session_after_a_handover` never opens a context menu

- **Severity:** Medium  **Confidence:** Confirmed
- **Location:** `tests/test_main_window_wiring.py:44-58`.
- **What is wrong:** After `Select(0)` the test calls `message_manager.needs_acknowledgement(message_id, station)` directly with `station = message_view.get_current_station()`. `on_context_menu` is never invoked, so the test would pass if the view stopped consulting `get_current_station` entirely. It restates `test_message_manager.py::test_a_message_from_another_station_offers_no_responses` one layer up; the first test in the file already proves the `get_current_station` wiring.
- **Fix direction:** Shadow `PopupMenu` on `window.panel` as `test_message_view.py` does, call `window.message_view.on_context_menu(None)` before and after the handover, and assert the popup count goes 1 → 0.

### LOW

#### L1. Assertions weaker than their names

- **Severity:** Low  **Confidence:** Confirmed
- `tests/test_acknowledge_path.py:56` — `assert window.status_texts != []` for "tells the user"; the exact text `"Could not send response: message unavailable."` is available.
- `tests/test_connection_manager.py:367` — `assert seen["timeout"] is not None`; should be `== NETWORK_TIMEOUT`.
- `tests/test_connection_manager.py:335-342, 354-367` — information-request tests never assert the request params (`type == "inforeq"`, `to == "SERVER"`, `packet == "metar EDDF"` / `"vatatis EDDF"`); the wire keyword is asserted only via `report_type_packet` in `test_weather_parsing.py`, not on the actual request.
- `tests/test_weather_monitor.py:150-154` — `test_unsubscribing_stops_the_updates` asserts the return value and count, never that a subsequent delivery is silent.
- `tests/test_main_window.py:188-189` — `_require_connection` returns False, but with `wx.MessageBox` stubbed to a no-op nothing checks the user was told (capture the args instead of discarding them).
- `tests/test_main_window.py:299-309` — `_on_weather_update` test asserts one chime; the status text `"New METAR EGLL"` and the new list row are not asserted.

#### L2. The timeout tests permanently wrap `requests.post` for the rest of the session

- **Severity:** Low  **Confidence:** Confirmed
- **Location:** `tests/test_connection_manager.py:408-438`; `src/model/connection_manager.py:47-58`.
- **What is wrong:** Both tests monkeypatch only `requests.get`. `install_request_timeout(7)` also wraps the genuine `requests.post` and tags it `_default_timeout_applied`; monkeypatch restores only `get`, so `requests.post` stays a 7-second-default wrapper for every later test and the real `install_request_timeout()` can never apply to `post` in-process again. Harmless today because every later `post` is re-patched, but it is a global mutation escaping its test.
- **Fix direction:** Monkeypatch `requests.post` too (or have both tests use `serving`).

#### L3. CI and environment robustness

- **Severity:** Low  **Confidence:** Confirmed unless noted
- `.github/workflows/tests.yml` has no `timeout-minutes` and the suite has no `pytest-timeout`; any unstubbed `ShowModal`/`wx.MessageBox` (H2, M1) hangs the job for GitHub's 6-hour default.
- The test job installs the whole `requirements.txt`, including `pyinstaller==6.20.0`, which tests do not need (pip cache mitigates).
- The local venv used for this audit diverges from the pins: `requests 2.32.5` (pinned `2.33.1`), `packaging 26.0` (pinned `26.2`), and neither `SimConnect` nor `pyinstaller` installed. A local green run is therefore not evidence the pinned CI set resolves and passes; verify the two pins exist on PyPI (*Plausible*: I could not check without network). `SimConnect>=0.4.26` is unbounded above.
- The suite is Windows-only by design and cannot run headless on Linux without Xvfb; that is documented, but the README's "need a desktop session" also means a GitHub Windows runner is required (it works there).
- `wx.App(clearSigInt=True)` per test resets SIGINT to default, so Ctrl-C during a run kills the process without pytest's teardown (cosmetic).

#### L4. `tests/README.md` is out of date and overclaims

- **Severity:** Low  **Confidence:** Confirmed
- Table lists 12 files; `test_config.py` and `test_weather_parsing.py` are missing.
- Line 22 "The validation each request dialog applies" — only `WeatherDialog` is tested.
- Line 23 "The exact text of every downlink" — two message formats plus weather.
- Line 25 "handlers" — existence check only (M2).
- Line 21 "Session state and logon acceptance validation" — logon acceptance only.

#### L5. `from conftest import ...` depends on the default `prepend` import mode

- **Severity:** Low  **Confidence:** Confirmed
- **Location:** `tests/test_acknowledge_path.py:3`, `test_cpdlc_session.py:3`, `test_downlink_requests.py:10`, `test_logon_status.py:8`, `test_main_window_wiring.py:12`, `test_message_manager.py:3`, `test_message_view.py:6`, `test_polling_controller.py:7`.
- **What is wrong:** It works only because `tests/` has no `__init__.py` and pytest inserts the test file's directory on `sys.path`; `--import-mode=importlib`, a second `conftest.py` in a subdirectory, or running a single file from another cwd breaks it. pytest documents conftest as fixtures/hooks, not an import target.
- **Fix direction:** Move `uplink`, the fakes and `make_main_window` to `tests/support.py` (or `tests/helpers/`).

#### L6. The window-leak fix is not guarded, and the `wx.MessageBox` stub silently answers "No"

- **Severity:** Low  **Confidence:** Confirmed
- Commit `1360b20` measured zero live top-level windows after adding `wx.SafeYield()` to `wx_app` (`tests/conftest.py:34`), but no fixture asserts `wx.GetTopLevelWindows()` is empty at teardown, so the leak can return silently (e.g. a new module that builds its own `wx.App`, exactly what that commit fixed twice).
- One `wx.App` per test is officially "one App per process" territory in wxPython; it works today (135 tests collected, CI green) but is the first place to look if the suite starts failing only in full runs.
- `tests/test_main_window.py:64` stubs `wx.MessageBox` to return `None`; every `!= wx.YES` confirmation in `on_disconnect`, `on_logoff`, `_confirm_exit`, `on_stop_all` will silently take the cancel branch in any future test, which is a trap for "why does my disconnect test do nothing".

#### L7. Repository hygiene visible from the tests

- **Severity:** Low / Info  **Confidence:** Confirmed
- `src/config.py:28` creates the real user data directory on import (every test file imports it).
- `.pytest_cache` is not in `.gitignore` (one exists in the review worktree).
- `src/utils/latest_simbrief_ofp.json` (161 KB of a real OFP) is tracked and is overwritten by the manual `test_simbrief.py` script; the script's `test_` name is one `pytest src` away from being collected and hitting the live API.
- `MessageManager.get_weather_key` (`message_manager.py:164`) and `MessageView.clear` (`message_view.py:91`) have no callers in `src/` or `tests/`.

### INFO

- Near-duplicates: `test_main_window.py::test_a_subscribed_report_reads_as_watched` is subsumed by `test_the_context_menu_toggle_stops_and_restarts_updates`; `test_a_weather_request_reports_the_code_in_upper_case` (dialogs) and `test_the_weather_dialog_always_opens_on_atis` (main window) both pin the `vatatis` default; `test_a_poll_that_raises_still_schedules_the_next_one` and `test_a_dropped_message_is_logged_before_it_propagates` duplicate their whole setup. Layered repeats across `test_message_manager` / `test_message_view` / `test_main_window_wiring` for "other station → no responses" are acceptable, except M13.
- The `window` fixture calls the real `MainWindow.__init__`, which `Show(True)`s a frame before the fixture hides it; the sound path is resolved from the cwd (`main_window.py:56-64`), so running from anywhere but the repo root silently takes the "sound missing" branch (with the stubbed MessageBox). Both harmless, both worth knowing.
- `tests/test_polling_controller.py:38-49` is statistical (mean of 2000 uniform draws within ±3000 of 60000 ≈ 15σ); not a flake risk.

---

## 2. Coverage map

Legend: **Risk** is the consequence of an undetected regression in that item, for untested items only.

| Production module / behaviour | Tested by | Risk if untested |
|---|---|---|
| `app.py` `_install_exception_handlers`, `SimCpdlcApp.OnExceptionInMainLoop` | UNTESTED | Low |
| `config.py` `weather_interval_minutes` | `test_config.py::*` (5) | — |
| `config.py` `load_config` (back-fill / bad JSON / IOError) | UNTESTED | Medium |
| `config.py` `save_config` (atomic write, non-dict) | UNTESTED | Medium |
| `logging_setup.setup_logging` | UNTESTED | Low |
| `ConnectionManager.install_request_timeout` | `test_connection_manager.py::test_install_request_timeout_supplies_a_default`, `::test_an_explicit_timeout_still_wins` | — |
| `ConnectionManager.redact` / logon code never in error text | `::test_redact_removes_the_logon_code`, `::test_the_logon_code_never_reaches_the_error_text` | — |
| `_call` transport/protocol conversion, counters | `::test_message_validation_failures_surface_as_hoppie_error[3]`, `::test_a_bad_http_status_...`, `::test_an_unparseable_body_...`, `::test_a_local_os_error_...`, `::test_a_rejected_message_...` | — |
| `connect` / `_open` (ping verifies link, callsign validation) | `::test_connect_succeeds_...`, `::test_connect_fails_when_the_server_is_down`, `::test_connect_rejects_a_callsign_...` | — |
| `disconnect` clears state | `::test_disconnect_clears_everything_connect_set` | — |
| `disconnect` when not connected (no-op) | UNTESTED | Low |
| `poll` failure counting, unparseable body, reset on success | `::test_transport_failures_during_polling_...`, `::test_an_unparseable_poll_response_also_counts`, `::test_poll_reports_failure_without_raising`, `::test_a_successful_poll_clears_the_failure_state` | — |
| `poll` when not connected → `(None, None)` | UNTESTED | Low |
| `failure_count` / `poll_failed` / `should_attempt_reconnection` (send failures survive polls; no cnx) | `::test_send_failures_survive_a_successful_poll`, `::test_no_reconnection_without_a_live_connection` | — |
| `attempt_reconnection` success / server down | `::test_reconnection_succeeds_once_the_server_recovers`, `::test_reconnection_reports_failure_...` | — |
| `attempt_reconnection` with missing credentials → False | UNTESTED | Low |
| `send_cpdlc` (wire packet `/data2/MIN/MRN/RR/TEXT`, not-connected error) | UNTESTED at the HTTP layer | Medium |
| `send_telex` | `::test_message_validation_failures_...`, `::test_a_bad_http_status_...` | — |
| `_send_info_request` envelope unwrap / server error / timeout / not connected / own failure counter | `::test_an_information_request_unwraps_the_server_envelope[2]`, `::_reports_a_server_error[2]`, `::_sends_a_timeout`, `::_requires_a_connection`, `::test_a_failing_weather_request_does_not_trip_reconnection`, `::test_a_weather_request_that_recovers_clears_its_own_count` | — |
| `_send_info_request` "Unexpected response" branch (447-449); request params (`inforeq`, `packet`) | UNTESTED | Low |
| `send_info_request` empty body → `No METAR available` | UNTESTED | Low |
| `PollingController.next_interval` band / active | `test_polling_controller.py::test_idle_polls_are_spread_...`, `::test_active_mode_polls_at_the_fastest_rate_permitted` | — |
| `start` / `stop` / `_schedule_next` after stop | `::test_a_stopped_poller_does_not_reschedule_itself` | — |
| `on_poll_timer` callback raises → logged and still rescheduled | `::test_a_poll_that_raises_still_schedules_the_next_one`, `::test_a_dropped_message_is_logged_before_it_propagates` | — |
| `on_poll_timer` when not connected → stop | UNTESTED | Medium |
| `_report_connection_state` ("Connection problem (n/3)", "Connection restored.") | UNTESTED | High |
| Reconnection branch ("Reconnected." / "Connection lost..." + stop) | UNTESTED | High |
| `set_active_polling` deadline logic, mid-tick guard | `::test_repeated_activity_does_not_defer_a_pending_poll`, `::test_an_idle_poll_is_pulled_forward_...`, `::test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once` | — |
| `check_polling_timeout` | `::test_a_quiet_period_returns_to_the_randomised_band` | — |
| `should_increase_polling_rate` (acks, clearance) | `::test_a_bare_acknowledgement_does_not_speed_up_polling`, `::test_a_clearance_speeds_up_polling` | — |
| `should_increase_polling_rate` for `TelexMessage` → False | UNTESTED | Low |
| `CpdlcSession.logon` happy path, MIN reset, pending tracking | partially via `test_cpdlc_session.py`, `test_logon_status.py` (wire MIN/RR not asserted) | Medium |
| `logon` preconditions (not connected, bad length) / HoppieError | UNTESTED | Low / Medium |
| `logoff` / `send_logoff_message` | UNTESTED | Medium |
| `send_altitude_change_request` text, counter, preconditions | `test_downlink_requests.py::*` (5) | — |
| `send_acknowledgement` recipient/MRN | `test_acknowledge_path.py::test_wilco_is_sent_with_the_senders_own_min_as_mrn` | — |
| `send_acknowledgement` RR (`N`) and own MIN | UNTESTED (H1) | High |
| `send_acknowledgement` sender ≠ current station warning | UNTESTED | Low |
| `send_direct_request` | `test_downlink_requests.py::test_a_weather_reason_is_unchanged` | — |
| `send_speed_request` (Mach / knots) | UNTESTED | Medium |
| `send_when_can_we_expect` | UNTESTED | Low |
| `send_telex` (session) | UNTESTED | Low |
| `send_pdc_request` (text, callsign precondition) | UNTESTED | Medium |
| `request_weather` / `_request_info` | `test_downlink_requests.py::test_a_weather_request_*` | — |
| `handle_logon_accepted` station mismatch / unsolicited / invalid name | `test_cpdlc_session.py::*` (4) | — |
| `handle_logon_accepted` MRN mismatch → False | UNTESTED (M3) | Medium |
| `handle_station_logoff` current station | `test_main_window_wiring.py::test_context_menu_follows_...` | — |
| `handle_station_logoff` non-current station (warning only) | UNTESTED | Low |
| `MessageManager.add_message` / `add_custom_message` / `add_weather_message` | many | — |
| `add_message` with non-HoppieMessage → -1 | UNTESTED | Low |
| `get_cpdlc_addressing` | `test_message_manager.py::test_get_cpdlc_addressing_*` (3) | — |
| Display/detail: `WeatherReport` | `::test_a_weather_report_reaches_the_reader_without_separators`, `test_main_window.py::test_a_weather_message_is_tagged_...` | — |
| Display/detail: `CpdlcMessage` (`format_list_text`/`format_message_text`) | UNTESTED | Medium |
| Display/detail: `TelexMessage`; custom without sender ("SYSTEM"); unknown id | UNTESTED | Low |
| Display/detail: custom with sender, list flattened | `test_main_window.py::test_a_multi_line_message_is_flattened_...` | — |
| `mark_acknowledged` / `needs_acknowledgement` / STANDBY / reused MIN / other station | `test_message_manager.py::*` (8) | — |
| `RESPONSES_BY_REQUIREMENT`: `WU`, `R`, `NE` | `test_message_manager.py::test_a_reused_min_...`, `::test_a_roger_message_...`, `::test_a_message_needing_no_response_...` | — |
| `RESPONSES_BY_REQUIREMENT`: `AN`, `Y`, `N` | UNTESTED (M4) | Medium |
| `WeatherMonitor.subscribe` new (+`initial_text`) / `unsubscribe` / `is_subscribed` / `count` | `test_weather_monitor.py::*`, `test_main_window.py::*` | — |
| `subscribe` existing key re-seeds text/signature | UNTESTED | Medium |
| `get_subscriptions` ordering; `clear` | UNTESTED (clear used in teardown only) | Low |
| `start` / `stop` / `shutdown` | `::test_the_monitor_can_be_stopped_and_started_again` | — |
| `set_interval` | UNTESTED | Medium |
| `check_now` guards (stopped / no subscriptions / started) | `::test_check_now_says_*` (3) | — |
| `_run_cycle` cycle-running guard, not-connected guard | UNTESTED | Low |
| `_fetch_worker` / `_post_result` / `_post_cycle_finished` (thread path) | incidental only (M7) | Medium |
| `_on_result` first / same letter / new letter / METAR text / error drop | `::test_the_first_report_is_announced` ... `::test_repeated_failures_drop_the_subscription` | — |
| `_on_result` error_count reset after success; unsubscribed in flight | UNTESTED | Medium / Low |
| `weather_parsing.*` (types, letters, D-ATIS, formatters, signatures) | `test_weather_parsing.py::*` (17) | — |
| `MessageView` single-selection, add_message, other-station no menu, weather menu callback | `test_message_view.py::*` (4) | — |
| `on_context_menu` item labels / binding / Unbind cleanup | UNTESTED (M6) | Medium |
| `on_message_selected` → detail pane text | UNTESTED | Medium |
| `on_context_menu` with no selection; `add_message` unknown id; `clear` | UNTESTED | Low |
| `MainWindow._init_ui` / `_init_menu` shape, mnemonics, station wiring | `test_main_window.py::test_the_menu_bar_*`, `::test_the_requests_menu_*`, `::test_no_mnemonic_collides_*`, `test_main_window_wiring.py::test_init_ui_wires_*` | — |
| Menu item → handler binding | UNTESTED (M2: existence only) | Medium |
| `on_connect` (dialog result → connect → start polling+weather → status/menu label) | UNTESTED | High |
| `on_disconnect` (confirm, logoff first, stop timers, clear subscriptions, menu label) | UNTESTED | High |
| `on_logon` / `on_logoff` | UNTESTED | Medium |
| `on_altitude_change` / `on_direct_request` / `on_speed_request` / `on_when_can_we_expect` / `on_telex` / `on_pdc_request` | UNTESTED | Medium |
| `_require_connection` False branch | `test_main_window.py::test_a_request_needing_a_connection_is_refused_while_disconnected` | — |
| `on_weather_request` (unsubscribe-on-uncheck, subscribe-on-success, failure box) | UNTESTED | Medium |
| `on_weather_subscriptions` | UNTESTED | Low |
| `on_settings` (+ `set_interval`, `save_config`) | UNTESTED | Medium |
| `on_check_updates` / `on_about` / `on_exit` | UNTESTED | Low |
| `_on_weather_update` chime | `::test_a_changed_report_announces_itself`, `::test_a_report_the_pilot_asked_for_arrives_quietly` | — |
| `_on_weather_error` | UNTESTED | Low |
| `_add_weather_message` / `_is_weather_watched` / `_on_toggle_weather_updates` / `_add_custom_message` | `test_main_window.py::*` | — |
| `_on_message_received`: `CURRENT ATC/ATS UNIT` filter | UNTESTED | Medium |
| `_on_message_received`: `LOGON ACCEPTED` accepted / rejected | `test_logon_status.py::*` (2) | — |
| `_on_message_received`: `HANDOVER` | UNTESTED (M1) | High |
| `_on_message_received`: `LOGOFF` from current station (and exact-match negatives) | UNTESTED (M1) | Medium |
| `_on_message_received`: CONTACT/MONITOR auto-tune, `auto_tune_com1` off, SimConnect failure status | UNTESTED (M1; blocked by fixture) | Medium |
| `_on_acknowledge_message` success / STANDBY / unknown id / custom id | `test_acknowledge_path.py::*` (5) | — |
| `_on_acknowledge_message` send failure → MessageBox | UNTESTED (blocked by fixture) | Medium |
| `on_close` / `_confirm_exit` (veto, logoff on exit, shutdown order) | UNTESTED | Medium |
| `_check_first_launch` | UNTESTED (patched out) | Low |
| `WeatherDialog` (ICAO rule, upper-case, checkbox latch, mirrors watched state, ATIS default) | `test_dialogs.py::*` (4), `test_main_window.py::test_the_checkbox_mirrors_*`, `::test_the_weather_dialog_always_opens_on_atis` | — |
| `LogonDialog`, `AltitudeChangeDialog`, `DirectRequestDialog` | UNTESTED | Low |
| `PDCDialog`, `SpeedRequestDialog`, `WhenCanWeDialog`, `ConnectDialog`, `SettingsDialog`, `WeatherSubscriptionsDialog`, `TelexDialog` | UNTESTED (M9) | Medium |
| `about_dialog.show_about_dialog` | UNTESTED | Low |
| `utils.frequency_parser.extract_contact_frequency` | UNTESTED | Medium |
| `utils.message_formatting.extract_message_content` | indirect only (no direct assertion) | Low |
| `utils.message_formatting.format_list_text` / `format_message_text` | UNTESTED | Medium |
| `utils.simconnect_manager.SimConnectManager` | UNTESTED | Medium |
| `utils.update_checker.UpdateChecker` | UNTESTED | Low |
| `utils.simbrief.get_latest_ofp` | UNTESTED (live script only) | Low |

---

## 3. Recommended new tests (prioritised)

1. **Acknowledgement frame is complete** (`test_acknowledge_path.py`): after WILCO, `connection.sent[-1] == (STATION, 1, RR.NO.value, "WILCO", 53)`; a second ack uses own MIN 2. Then one test through the real `HoppieConnector` with a capturing `requests.get`: `params["packet"] == "/data2/1/53/N/WILCO"`.
2. **Hermetic conftest** (autouse): `CONFIG_FILE` → `tmp_path`; `requests.get/post` guard that raises unless a test installs `serving()`; SimBrief `get_latest_ofp` patched at both dialog import sites; assert `wx.GetTopLevelWindows()` is empty after `wx_app` teardown. Assertion: a test that calls `save_config({})` leaves the real user data dir untouched.
3. **HANDOVER via the window** (`make_main_window` + fake simconnect + injected config): logged on to EDYY, receive `HANDOVER EDGG` → `session.get_current_station() == ""`, `connection.sent[-1] == ("EDGG", 1, "Y", "REQUEST LOGON", None)`, `status_texts == ["Logged off from EDYY.", "Pending logon to EDGG."]`, `polling_controller.active_calls == 1`. Negative: `HANDOVER EDGG` from a non-current station changes nothing.
4. **LOGOFF via the window**: `LOGOFF` from the current station clears the station and sets `"Logged off from EDYY."`; `LOGOFF` from another station and `LOGOFF NOT REQUIRED AT THIS TIME` from the current station both leave the station logged on (TODOS 23).
5. **CURRENT ATC UNIT filter**: `/data2/5//NE/CURRENT ATC UNIT@_@EDGG@_@RHEIN RADAR` from the current station → `message_view.added == []`, `message_manager.message_log == {}`, no status text; `CURRENT ATS UNIT` likewise.
6. **CONTACT/MONITOR auto-tune**: `CONTACT MARSEILLE CONTROL 133.325` from the current station with `auto_tune_com1: True` → fake simconnect received `133.325`; with `False` → nothing; with the fake returning False → `status_texts[-1] == "Auto-tune failed \u2014 set 133.325 manually"`; same message from a non-current station → nothing tuned.
7. **Telex bodies do not drive session state** (M12): `TelexMessage("EDGG","DLH123","LOGON ACCEPTED")` (and `LOGOFF`, `HANDOVER EDDF`) → `current_station` unchanged, `status_texts == []`.
8. **PollingController link reporting**: a fake whose `poll_failed()` is True and `failure_count()` is 2 → parent status `"Connection problem (2/3) - retrying..."`; then False → `"Connection restored."`; `should_attempt_reconnection()` True + `attempt_reconnection()` False → `"Connection lost. Reconnect to continue."` and `is_running() is False` even though `finally` ran; True → `"Reconnected."` and still running; `is_connected()` False on a tick → timer stopped, no poll.
9. **MRN validation**: `handle_logon_accepted("EDDF", mrn=2)` with pending MIN 1 → False, station `""`; via the window with a properly built `/data2/1/2/NE/LOGON ACCEPTED` → `status_texts == []`. Fix `uplink` to accept `mrn`.
10. **Response table completeness**: parametrise over all six `CpdlcResponseRequirement` members: `WU → [WILCO,UNABLE,STANDBY]`, `AN → [AFFIRM,NEGATIVE,STANDBY]`, `R → [ROGER,STANDBY]`, `Y → [YES,NO]`, `N → []`, `NE → []`.
11. **Context menu contents and cleanup** (`test_message_view.py`): labels `["Respond: WILCO","Respond: UNABLE","Respond: STANDBY"]`; firing item 2 calls `on_acknowledge(message_id, "UNABLE")`; re-posting the same id after the menu closed fires nothing (TODOS 2).
12. **Every downlink literally** (`test_downlink_requests.py`): `logon` → `("EGGX", 1, "Y", "REQUEST LOGON", None)` and counter back to 1 after prior sends; `logoff` → `("EGGX", n, "NE", "LOGOFF", None)` and station cleared; `send_speed_request("082", True)` → `REQUEST M082`, `("300", False)` → `REQUEST 300K`; `send_pdc_request` → exact upper-cased telex to the origin; `send_when_can_we_expect` passthrough; each with `FakeConnectionManager(raise_with=HoppieError("boom"))` → `(False, "boom")`.
13. **Weather monitor determinism**: with `threading.Thread` run synchronously and `wx.CallAfter` direct, `check_now()` on the `atis` fixture announces once; a second `check_now()` while `_cycle_running` → False; four errors then a success then four errors → `count() == 1`; `subscribe` on an existing key with new text updates `signature`; `set_interval(120000)` restarts a running timer with `GetInterval() == 120000`.
14. **Dialogs**: per-dialog OK-button tables (Logon 3/4/5 chars; Altitude 9/10/600/601/"abc"; Direct "A"/"AB"/"ABCDE"/"ABCDEF"/"AB1"; Speed Mach "8"/"82"/"082"/"0820", knots; WhenCanWe each type and `get_message_text` literals; PDC all-fields rule; Telex both fields with a `get_current_station` stub parent), `SettingsDialog.get_settings` round trip, `ConnectDialog.get_connection_details` returns the saved code for the selected network when the field is hidden and the typed code otherwise (with `load_config` patched).
15. **`load_config` / `save_config`** on `tmp_path`: back-fill of a missing key, invalid JSON → defaults, non-dict → False, `os.replace` failure leaves the original intact and no `.tmp` behind.
16. **`frequency_parser` table**: the ten cases in the preamble, plus a multi-line message and `136.990` / `137.000` at the boundary; **`message_formatting` table** pinning `@@`, `_`, punctuation-joining and the `/data2/19/1/NE/` prefix strip.
17. **`on_connect` / `on_disconnect` / `on_close`** through the real `window` fixture with `ConnectDialog.ShowModal` stubbed to `ID_OK` and `get_connection_details` stubbed, `connection_manager.connect` faked, `wx.MessageBox` stubbed to `wx.YES`, and `wx.MilliSleep` patched: polling and weather timers start/stop, menu label flips, status texts and system messages appear, `send_logoff_message` is sent before disconnect when logged on, `_confirm_exit` vetoes on "No".
18. **Menu binding** (replaces M2's list): post `wxEVT_MENU` for each item and assert the intended handler recorder fired once.
19. **`on_message_selected`**: selecting a row puts `get_message_detail_text` into `message_detail` (the pane NVDA reads).
20. **`UpdateChecker._is_newer_version`** and `_check_in_background` not calling `wx.CallAfter` when `parent.IsBeingDeleted()` (TODOS 3); **`SimConnectManager.set_com1_standby_mhz`** with a fake `SimConnect` module: Hz conversion `134.750 → 134750000`, retry after `send_event` failure, False when import fails.

---

## 4. Things I checked that are fine

- **No current test reaches the network or writes the real config.** Every `hoppie_connector` call in `test_connection_manager.py` goes through `serving()`/explicit monkeypatches of both `requests.get` and `requests.post`; `connected()` patches both before `connect()`; the `.invalid` TLD is used for the timeout tests. The `window` fixture's `auto_check_updates: False` keeps `UpdateChecker` off its thread; `_check_first_launch` is patched so no `save_config`; `HeadlessMainWindow` and `make_main_window` skip `__init__` entirely; only `WeatherDialog` (which does not read config) is ever constructed. `test_logon_status.py` never reaches line 1010 because `LOGON ACCEPTED` takes the earlier branch.
- **`test_connection_manager.py` is a genuinely good boundary test.** Faking `requests` rather than the connector keeps the library's own validators and parsers in the path (verified against `Messages.py:146-149,635-640`, `API.py:46-47`, `Responses.py:197-199`), so the ValueError/ConnectionError/HTTPError conversions, the OSError pass-through (`FileNotFoundError` is not in `TRANSPORT_ERRORS`), the send-vs-poll-vs-info counters and the credential redaction are all exercised for real.
- **The pytest-run-controller tests are real.** `test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once` correctly shadows `_schedule_next` on the instance, stops the one-shot to reproduce `IsRunning() == False`, and would catch removal of the guard at `polling_controller.py:715`. The deadline tests cannot flake (a 20 s deadline cannot be further than 20 s away).
- **`test_dialogs.py::_fire_auto_update_toggle`** drives a real `wx.EVT_CHECKBOX` through `ProcessEvent`, so deleting the `Bind` at `weather_dialog.py:91` is caught, as commit `611f422` intended.
- **`test_the_weather_menu_hands_back_the_report_it_was_opened_on`** is the model for menu tests: it fires each item through `ProcessEvent` and verifies the closure captured the right report.
- **`test_message_manager.py::test_a_reused_min_does_not_suppress_a_later_message`** is a precise regression test for the ID-keyed acknowledgement set.
- **`test_weather_parsing.py`** covers the registry, D-ATIS designator, NATO spelling, time-group stripping and both formatters with literal expectations; `test_the_dialog_offers_every_report_type` correctly ties `REPORT_ORDER` to `REPORT_TYPES`.
- **Mnemonic-collision test** reads `GetItemLabel()` (keeps `&`) and handles `&&`; it is a real accessibility guard.
- **Fixture teardown order** is sound: `dialog` → `frame` → `wx_app`; `frame.Destroy()` is queued before `wx.SafeYield()` runs in `wx_app`, and commit `1360b20` records that this brought the live-window count to zero. The `logger` fixture resets handlers each test, so the `caplog.handler` attached in `test_a_dropped_message_is_logged_before_it_propagates` does not leak.
- **`pytest.ini`** correctly scopes collection to `tests/` (the live-API script under `src/utils/` is excluded) and `pythonpath = .` makes `import src...` work without installing the package.
- **CI workflow** picks the right OS for a wxPython suite, pins Python 3.13, caches pip on both requirements files, and runs on push to `main` and on every PR. `SimConnect>=0.4.26` is a pure-Python package bundling its DLL and installs on the Windows runner without a simulator present.
- **`hoppie_connector` objects the tests build are realistic**: station names satisfy `^[A-Z0-9]{3,8}$`, message bodies satisfy `[A-Z0-9\.\_\@ ]+`, and `RR` members are the real `CpdlcResponseRequirement` enum, so `get_packet_content()` on every fixture message is a legal Hoppie packet.
