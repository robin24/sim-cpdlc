# Sim-CPDLC codebase audit — 2026-09-03

**Commit audited:** `9c06458` (main, clean tree).
**Baseline:** full test suite passes (135 tests, 1.2 s) using the wxPython venv under `.claude/worktrees/review-25-ceb148/.venv`.

## Scope and method

- Read in full: `app.py`, everything under `src/` (about 5,700 lines), everything under `tests/` (about 1,900 lines), README, TODOS, the PR-24 spec, `app.spec`, `sim-cpdlc.iss`, `version_info.txt`, `update_version.py`, requirements, CI workflows.
- Read in full: the source of `hoppie_connector` 0.2.1, the library every network call goes through. Several findings depend on its behaviour (ASCII-only decoding, a strict character whitelist for CPDLC text, per-message parse failures downgraded to Python warnings).
- Four independent review passes were run with separate lenses (threading and wx lifecycle, network and protocol, GUI/state/configuration/packaging, test suite). Their raw reports are listed in the appendix. Every finding below was cross-checked against the current code; findings marked **verified by execution** were reproduced with the real library in the loop, using in-process fakes for `requests.get`/`requests.post` (no network traffic, repo untouched).
- Items in `TODOS.md` and the PR-24 spec were re-checked; all are fixed as recorded, including the spec's "out of scope" list. The accepted WON'T FIX (unbounded message log) is not reported.

**Severity scale**

| Level | Meaning here |
|---|---|
| High | Silent loss of ATC communication, or the app becomes unusable for a screen-reader user under realistic conditions |
| Medium | Wrong behaviour a pilot would notice in normal use, wrong state that persists, or a latent fault that corrupts the developer's environment |
| Low | Edge cases, misleading feedback, robustness gaps, documentation and packaging drift |
| Info | Code quality with no user-visible effect |

**Confidence:** *Confirmed* = traced in code (and usually reproduced); *Plausible* = mechanism confirmed but the trigger frequency or a platform detail could not be measured.

---

## Summary

| ID | Sev | Area | Finding |
|---|---|---|---|
| H-1 | High | Network/protocol | Uplinks the library cannot parse are dropped with no trace, after the server marked them delivered |
| H-2 | High | Network/GUI | Polling stops for good after one failed automatic reconnection; only the status bar changes and the menu still says "Disconnect" |
| H-3 | High | Threading/UX | Every CPDLC network call, the SimBrief fetch and the manual update check block the GUI thread (15–60 s worst case) |
| M-1 | Medium | State | CPDLC session state is never reset on disconnect, failed reconnection or failed LOGOFF |
| M-2 | Medium | Network | One non-ASCII byte in a poll response loses every message in that poll and counts as a link failure |
| M-3 | Medium | Polling | An exception in the message callback discards the rest of the poll batch |
| M-4 | Medium | Network/GUI | A non-`HoppieError` during automatic reconnection leaves the state machine stuck and stacks one error dialog per tick |
| M-5 | Medium | Threading/UX | The update checker can pop over any modal dialog and closes the app on "Yes", from under an open dialog |
| M-6 | Medium | Network/weather | An empty weather envelope `{server info {}}` is returned as report text; bare `ok` is reported as an unexpected response |
| M-7 | Medium | Protocol | Manual logon while already logged on sends no LOGOFF and restarts the MIN counter mid-dialogue |
| M-8 | Medium | GUI | Dialogs validate stripped text but return it unstripped |
| M-9 | Medium | SimConnect | A failed `send_event` is reported as success; two SimConnect connection attempts per CONTACT on the GUI thread |
| M-10 | Medium | Release | Source checkouts identify as 0.1.0: every launch offers an "update", About and bug reports carry a useless version |
| M-11 | Medium | Tests | Fixtures are not hermetic: the real `config.json`, SimBrief and SimConnect are one call away |
| M-12 | Medium | Tests | The acknowledgement RR/MIN, the MRN check and half the response table have no regression tests |
| L-1 | Low | Polling | "Connection problem (n/3) - retrying..." shown after one failed *send*, until the next successful send |
| L-2 | Low | Protocol | A TELEX reading `LOGON ACCEPTED` / `LOGOFF` / `HANDOVER XXXX` drives CPDLC session state |
| L-3 | Low | Protocol | Logon lifecycle has no negative paths (exact match only, no rejection handling, pending state never expires) |
| L-4 | Low | Threading | Weather cycle has no deadline; an in-flight cycle survives reconnect and may mix credentials |
| L-5 | Low | Threading | Worker-thread `IsBeingDeleted()` guards do not work and can raise at exit |
| L-6 | Low | Logging | SimBrief diagnostics never reach the log file; the console handler is dead in the windowed build |
| L-7 | Low | GUI | Input validation gaps in the request dialogs |
| L-8 | Low | Security | Unredacted logon code survives in the exception chain; DEBUG logging prints both logon codes |
| L-9 | Low | GUI | `on_disconnect` sleeps 500 ms on the GUI thread for nothing and re-arms polling before stopping it |
| L-10 | Low | GUI | Settings applies the weather interval before the save succeeds |
| L-11 | Low | GUI | `resource_path` resolves against the current directory in development mode |
| L-12 | Low | Display | `@@` becomes `N/A` glued to neighbouring words; list columns never resized |
| L-13 | Low | GUI | `dlg.Destroy()` is skipped when anything raises between `ShowModal()` and the end of the handler |
| L-14 | Low | Lifecycle | Exception reporter opens a modal inside the failing handler; `OnExceptionInMainLoop` and the Ctrl+C branch are dead or wrong |
| L-15 | Low | Lifecycle | `_confirm_exit` ignores `CanVeto()`; first-launch prompt runs mid-`__init__` |
| L-16 | Low | GUI | Weather subscriptions dialog gives no confirmation on stop and can list stale entries |
| L-17 | Low | Protocol/parsing | Inforeq error text keeps braces; HANDOVER regex demands the exact form; frequency parser needs a unit name; every non-ack uplink extends active polling |
| L-18 | Low | Docs | README drift: Python 3.7 (3.12 required), climb/descent option, sound policy, "Automatic Reconnection", tests table |
| L-19 | Low | Packaging | pyinstaller in runtime requirements; SimConnect unpinned and its DLL optional; `.gitignore` gaps; release does not run tests |
| L-20 | Low | Hygiene | Personal SimBrief data and a live-API script committed under `src/` |
| L-21 | Low | Tests | Vacuous or weak tests; large untested areas; small fixture leaks |
| I-1..I-5 | Info | Quality | Unused imports, dead code, duplication, aliases, uneven accessibility conventions, misc |

---

## High

### H-1. Uplinks the library cannot parse are dropped with no trace, after the server has marked them delivered

- **Area:** Network/protocol. **Confidence:** Confirmed (mechanism, verified by execution); frequency on the live networks is Plausible.
- **Where:** `hoppie_connector/__init__.py:77-85` (`poll()`), `hoppie_connector/Messages.py:602,613,639-641` (`CpdlcMessage` whitelist `[A-Z0-9._@ ]`), `src/model/connection_manager.py:284-308`, `src/controller/polling_controller.py:149-176`, `app.spec:59` (`console=False`).
- **What is wrong:** `HoppieConnector.poll()` parses each item of the poll body and, on any `ValueError`, calls `warnings.warn(..., HoppieWarning)` and drops the item. The app never captures warnings (no `warnings.catch_warnings`, no `logging.captureWarnings`), and in the packaged build `sys.stderr` is `None`, so the warning goes nowhere. `ConnectionManager.poll()` sees a clean result, no counter moves, nothing is logged, nothing reaches the list. Hoppie marks messages as relayed when it serves them, so the message is gone for good.
- **What the library refuses (verified by execution):** CPDLC text containing any of `/ , : - ( )`, lowercase letters or a newline; telex longer than 220 characters or containing any non-ASCII character; unknown message types. A poll body with three items (`CLIMB TO FL350`, `QNH 1013 / TRL 70`, a 221-character telex) delivered one message and emitted two warnings; the app logged nothing.
- **Failure scenario:** Controller sends `CONTACT LANGEN 127.825 (SECONDARY 121.500)` or a free-text uplink with a slash or comma. The controller's client shows "delivered", waits for WILCO, escalates by voice or assumes non-compliance; the pilot never saw it.
- **Fix direction:** Wrap `self.cnx.poll` in `warnings.catch_warnings(record=True)` (filter `HoppieWarning`), log each dropped item at ERROR with sender and raw packet, and add a SYSTEM row with the notification sound ("Unreadable message from EDGG: …") so the pilot can ask by voice. Longer term, parse `cpdlc` items with a permissive fallback (the raw `{FROM cpdlc {packet}}` is available). Measuring how often this happens is easy: compare Hoppie's web message log for a flight with `sim-cpdlc.log`.

### H-2. Polling stops for good after one failed automatic reconnection, with no notification beyond the status bar; the menu still says "Disconnect"

- **Area:** Network/GUI. **Confidence:** Confirmed.
- **Where:** `src/controller/polling_controller.py:181-196` (reconnection branch, `stop()`), `:205-217` (`_report_connection_state`, status bar only), `src/model/connection_manager.py:327-350` (`attempt_reconnection` clears `cnx` on failure), `src/gui/main_window.py:341-342, 397-398` (the only places the Connect/Disconnect label changes).
- **What is wrong:** After `MAX_CONNECTION_FAILURES` (3) the controller calls `attempt_reconnection()` once, in the same tick, with no back-off. On failure `cnx` is cleared, the timer is stopped and nothing ever restarts it. Unlike connect and disconnect, this path adds no SYSTEM row and plays no sound; `_set_status` is the only output, which a screen-reader user must query by hand. `MainWindow` is never told: `menu_item_connect` keeps the label "&Disconnect" while `is_connected()` is false, so activating "Disconnect" opens the Connect dialog. `_reported_failure` is also never reset by `start()`, so the first good poll of the next session overwrites "Connected as X." with "Connection restored.". The weather monitor keeps ticking (and skipping) with its subscriptions intact. README promises "Automatic Reconnection: Handles connection issues gracefully".
- **Failure scenario:** During an active exchange (20 s polls) the router reboots for 70 s. Polls at 0, 20 and 40 s fail; the ping at 40 s fails; polling stops. The link is back at 70 s, the client never polls again; the controller's next uplink sits on the server; the pilot, who heard nothing, keeps waiting for a reply. In idle mode the same happens after a 2–4 minute outage.
- **Fix direction:** Keep polling with exponential back-off (for example 20 s → 60 s → 120 s capped) instead of stopping; treat `attempt_reconnection` as re-verification, not as terminal; give the controller an `on_connection_lost`/`on_reconnected` callback so the window can add a SYSTEM message, play the sound, and flip the menu label; reset `_reported_failure` in `start()`.

### H-3. Every CPDLC network call, the SimBrief fetch and the manual update check block the GUI thread

- **Area:** Threading/UX. **Confidence:** Confirmed (paths and timeout semantics); durations derived from the constants.
- **Where:** `src/config.py:147` (`NETWORK_TIMEOUT = 15`), `src/model/connection_manager.py:221-222, 286, 368-373, 388`, `src/controller/polling_controller.py:149, 186`, `src/gui/main_window.py:324, 380, 734, 986, 1017, 1085`, `src/gui/dialogs/connect_dialog.py:62`, `src/gui/dialogs/pdc_dialog.py:53`, `src/utils/simbrief.py:28-32` (10 s), `src/utils/update_checker.py:40, 97` (5 s).
- **What is wrong:** Only the automatic weather cycle runs on a worker thread. Connect/ping, every poll, every send, the manual weather request, the handover logon inside the poll tick, the SimConnect setup inside the poll tick, the SimBrief fetch inside two dialog constructors and the manual update check all block the wx main loop. A scalar `timeout=15` is a connect timeout plus a per-read timeout, not a total budget, so one call can take about 30 s (more for a trickling response; DNS is not bounded at all). While blocked, no timers fire, no `CallAfter` results are delivered, and UIA/MSAA queries from NVDA time out, so the user hears nothing.

  | Operation | Worst-case freeze |
  |---|---|
  | File > Connect with a SimBrief id set | ~20 s before the dialog appears, then ~30 s after OK |
  | Each poll tick during an outage | ~30 s out of every 20–75 s, then another ~30 s for the reconnection ping |
  | Poll tick that carries a HANDOVER | poll + synchronous logon, ~60 s |
  | Manual weather request / Exit or Disconnect while logged on | ~30 s |
  | Manual update check | ~10 s |

- **Failure scenario:** A server that accepts TCP and then goes silent freezes the UI for most of a two-to-four-minute stretch, ending in H-2. Keystrokes typed during the freeze are replayed onto whatever dialog appears next.
- **Fix direction:** Reuse the `WeatherMonitor` pattern (snapshot on the GUI thread, worker, `wx.CallAfter` back) for poll, send and connect, with a single outstanding request per kind and "Connecting…"/"Sending…" status text. If that is too large a change at once, first move the SimBrief fetch out of the dialog constructors, thread the manual weather request and the manual update check, and split the timeout into a short connect timeout and a total read budget.

---

## Medium

### M-1. CPDLC session state is never reset on disconnect, failed reconnection or failed LOGOFF

- **Area:** State. **Confidence:** Confirmed.
- **Where:** `src/model/cpdlc_session.py:24-28` (fields), `:108-141` (`logoff` leaves `current_station` set on failure), no reset method in the class; `src/gui/main_window.py:349-402` (`on_disconnect`), `:316-347` (`on_connect` only sets the callsign); `src/controller/polling_controller.py:182-196`.
- **What is wrong:** `ConnectionManager.disconnect()` clears its own fields, but `current_station`, `pending_logon_min/station` and `cpdlc_min_counter` survive a disconnect, a failed automatic reconnection and the next `connect()`, even under a different callsign or network. `on_disconnect` inspects the LOGOFF result only to decide whether to echo the text; a failed LOGOFF (the common case when the reason for disconnecting is a dead link) produces no dialog and no SYSTEM row.
- **Failure scenario:** Logged on to LSAG; the link drops; automatic reconnection fails. The user reconnects as a different flight. Status says "Connected as X." but `is_logged_on()` is still true: the Requests menu sends `REQUEST FL350` to LSAG with the old MIN sequence, old LSAG uplinks are answerable again from the context menu, and the exit confirmation talks about LSAG. Offline, `Requests > Logoff` only reports a send failure and cannot clear the state.
- **Note:** Hoppie logon state lives in the ATC client keyed by callsign, so keeping the station across a reconnect with the *same* callsign may be intended (see questions at the end).
- **Fix direction:** Add `CpdlcSession.reset()` (station, pending logon, MIN counter) and call it from `on_disconnect` after the LOGOFF attempt regardless of outcome, from the failed-reconnection path, and from `on_connect` when the callsign or network changes; surface a failed LOGOFF as a SYSTEM message.

### M-2. One non-ASCII byte in a poll response loses every message in that poll and counts as a link failure

- **Area:** Network. **Confidence:** Confirmed (verified by execution); whether the networks ever relay non-ASCII bytes is Plausible.
- **Where:** `hoppie_connector/API.py:50` (`response.content.decode('ascii')`), `src/model/connection_manager.py:136-143, 296-308`.
- **What is wrong:** The library decodes the whole body as ASCII before any per-message parsing. One `°`, `–` or umlaut in any telex/ATIS/free text raises `UnicodeDecodeError` (a `ValueError`) for the entire response. `_call` converts it to a protocol `HoppieError`; `poll()` logs "Poll error: 'ascii' codec can't decode…" and increments `connection_failures`. Reproduced: a body with a valid CLIMB instruction and a telex containing `°` returned `(None, None)`, `connection_failures` 1; the CLIMB was gone. Three such polls trigger H-2.
- **Fix direction:** The app cannot change the decode inside the library, but it can shadow `HoppieAPI.connect` on `HoppieConnector._api` to decode with `errors="replace"` before parsing, and it should at least distinguish this in the log/status from a transport outage.

### M-3. An exception in the message callback discards the rest of the poll batch

- **Area:** Polling. **Confidence:** Confirmed.
- **Where:** `src/controller/polling_controller.py:159-176`.
- **What is wrong:** `poll()` returns the whole batch, already marked relayed by the server. The loop re-raises on the first failing `message_callback(message)`, so messages 2..n are never logged, displayed or applied to `CpdlcSession`, and `should_increase_polling_rate` is skipped. The `finally` keeps polling alive, but the batch is lost. Today the concrete triggers are the deliberately unconverted local `OSError`s from the network layer raised during the nested handover logon, or a wx error in the view; the guard exists because callback failures are anticipated.
- **Failure scenario:** Batch `[uplink A, HANDOVER EDGG]`; handling A raises; the user sees an "Unexpected Error" box for A; the HANDOVER is gone, the client still believes it is logged on to the old station.
- **Fix direction:** Keep the per-message `try`, log and continue with the remaining messages (still applying `should_increase_polling_rate`), then re-raise or report the first error after the loop. Adding the message to the list before running state/SimConnect logic would at least keep the text visible.

### M-4. A non-`HoppieError` during automatic reconnection leaves the state machine stuck and stacks one error dialog per tick

- **Area:** Network/GUI. **Confidence:** Confirmed (verified by execution); the trigger is uncommon.
- **Where:** `src/model/connection_manager.py:19-24` (`TRANSPORT_ERRORS` deliberately excludes `OSError`), `:327-350` (`attempt_reconnection` catches only `HoppieError`), `src/controller/polling_controller.py:182-198`, `app.py:31-51` (reporter shows a modal synchronously).
- **What is wrong:** `poll()` catches everything, so each `OSError` poll (for example a CA bundle path that became invalid mid-session) increments `connection_failures`. `attempt_reconnection()` lets the same `OSError` from `ping` escape: `cnx` keeps the old connector, the counter is not reset, `should_attempt_reconnection()` stays true. Reproduced: after one attempt, `cnx` unchanged, failures 3, still due. The escaped exception reaches the reporter, which opens a modal `wx.MessageBox` inside the timer dispatch; the `finally` has already re-armed the one-shot, so the next tick fires inside that modal loop, fails the same way and opens a second dialog on top, every 20–75 s until the user disconnects.
- **Fix direction:** In `attempt_reconnection` (and `connect`) catch `Exception`, log, set `cnx = None`, return False, keeping the classification decision but not letting it break the state machine. In the reporter, coalesce dialogs (log only if one is already open) and show via `wx.CallAfter` even on the main thread so the failing handler unwinds first.

### M-5. The update checker can pop over any modal dialog and closes the application on "Yes", from under an open dialog

- **Area:** Threading/UX. **Confidence:** Plausible (each wx step verified in source; the end-to-end sequence was not executed).
- **Where:** `src/utils/update_checker.py:42-49, 127-158` (`wx.CallAfter(self.parent.Close)` at 150), `src/gui/main_window.py:98-101` (auto check in `__init__`), `:1155-1158` (first launch schedules `on_settings` via `CallAfter`), `:250-296`.
- **What is wrong:** The "Update Available" box is shown via `wx.CallAfter`, which the main loop dispatches even while another dialog's modal loop is running, so it appears parentless on top of whatever is open and steals focus. On Yes, `Close()` is dispatched inside the open dialog's modal loop: the frame's deferred destruction deletes the modal child, `ShowModal()` returns on a deleted object, and the handler continues with `dlg.Destroy()`/`dlg.get_settings()` on a dead proxy (`RuntimeError`). The prompt also does not say that Yes closes the program; when not connected the app closes with no further question.
- **Failure scenario:** First launch → "set up now?" Yes → Settings opens → about a second later "Update Available" appears over the form → Yes → browser opens, the frame closes under Settings → "Unexpected Error: wrapped C/C++ object … has been deleted" → exit.
- **Fix direction:** Do not close the application from the checker (open the browser and leave the user in control), or have the main window own the "update available" state and act on it only when no modal is active; give the prompt a parent; say in the text what Yes does.

### M-6. An empty weather envelope is returned as report text; a bare `ok` is reported as an unexpected response

- **Area:** Network/weather. **Confidence:** Confirmed (verified by execution); the exact empty-envelope form the servers use is Plausible (it is what the code's own comment assumes).
- **Where:** `src/model/connection_manager.py:32` (`_SERVER_INFO_PATTERN` uses `(.+)`), `:433-449`, `:470-475`.
- **What is wrong:** `(.+)` needs at least one character, so `ok {server info {}}` does not match, the unwrapping is skipped and the literal string `{server info {}}` is returned as the report; the `if not report_text` guard that the comment describes never fires. Bare `ok` falls to "Unexpected response: ok", which reads like a fault. `error {no data}` is reported with the braces kept.
- **Failure scenario:** A subscription to a mistyped ICAO gets a list row "ATIS ZZZZ: {server info {}}" (announced with the sound as an "initial report"), and the subscription lives forever because every cycle returns the same text; a real report later flips it back and forth.
- **Fix direction:** Use `(.*)`; treat `body == "ok"` and an empty inner text as "no report available" (a `HoppieError` the weather monitor already counts as a failure); strip the braces from the error reason.

### M-7. Manual logon while already logged on sends no LOGOFF and restarts the MIN counter mid-dialogue

- **Area:** Protocol. **Confidence:** Confirmed by reading.
- **Where:** `src/model/cpdlc_session.py:62-106` (`cpdlc_min_counter = 1` at line 85; `current_station` untouched), `src/gui/main_window.py:404-449` (`on_logon` checks only `is_connected()`).
- **What is wrong:** `logon()` is callable in any state. It resets MIN to 1 and records a pending logon but keeps `current_station`. Until the new station accepts, every request goes to the *old* station numbered 2, 3, … which that station already saw earlier; if the new station accepts, the old one is never told. Re-logging on to the same station (a natural thing to try when the pilot suspects they were dropped, since the app gives no indication either way) restarts MIN on a dialogue the station may consider open. `pending_logon_*` is never cleared by `logoff()`, `handle_station_logoff()` or disconnect.
- **Fix direction:** In `on_logon`, if logged on, either refuse ("log off first") or send LOGOFF and clear the station before the new REQUEST LOGON; restart MIN only when the previous dialogue was actually closed; clear pending state on logoff/disconnect.

### M-8. Dialogs validate stripped text but return it unstripped

- **Area:** GUI. **Confidence:** Confirmed (library rejects `"EDDF "` with "Invalid TO station name").
- **Where:** `src/gui/dialogs/logon_dialog.py:48` vs `:60`, `connect_dialog.py:173` vs `:197`, `pdc_dialog.py:141-146` vs `:165-171`, `telex_dialog.py:56-58` vs `:71-73`, `settings_dialog.py:179-186`; consumer `src/gui/main_window.py:421-428`.
- **What is wrong:** Every `on_text_change` strips before checking, but the getters return `GetValue().upper()` (or raw) without stripping. `hoppie_connector` validates station names as `^[A-Z0-9]{3,8}$`, so an invisible leading or trailing space passes the OK gate and fails at send time. Logon is the worst case: "EDDF " enables OK, then `on_logon` measures the unstripped value and shows "Station name must be exactly 4 characters long." Settings saves logon codes with surrounding whitespace, after which every connection fails with the server's invalid-logon error.
- **Fix direction:** Strip in every getter (and in `SettingsDialog.get_settings`), after which the length re-check in `on_logon` becomes redundant.

### M-9. SimConnect auto-tune: a failed `send_event` is reported as success; two connection attempts per CONTACT on the GUI thread

- **Area:** SimConnect. **Confidence:** Confirmed for the ignored return value and the retry logic (upstream Python-SimConnect source); Plausible for the unbounded wait.
- **Where:** `src/utils/simconnect_manager.py:37-60` (`connect`), `:74-111` (`set_com1_standby_mhz`; return value of `send_event` ignored at 96–100; `_sm` dropped without `exit()` at 101–109), `src/gui/main_window.py:1009-1027` (called from the poll tick; `load_config()` from disk on every message).
- **What is wrong:** Upstream `send_event()` returns `False` on failure rather than raising; the manager logs "COM1 standby set" and returns True regardless, so after MSFS is closed and reopened every CONTACT "succeeds" without tuning anything and the "Auto-tune failed" status never appears. When the simulator is not running, each CONTACT/MONITOR runs two full connection attempts on the GUI thread (the availability cache is reset between them). Upstream `connect()` also busy-waits without a timeout for the OPEN reply after a successful pipe open, which would spin the GUI thread inside a poll tick if the simulator delays it. On the retry path the previous `SimConnect` object is dropped without `exit()`, potentially orphaning its dispatch thread. `auto_tune_com1` defaults to True, so users without MSFS pay this on every CONTACT.
- **Fix direction:** Check the return of `send_event()`; treat a `None` event id as a failed connect; call `exit()` before dropping the object; connect once (at network connect time, off the GUI thread, with a watchdog) and only `send_event` from the message path; cache `auto_tune_com1` instead of re-reading the config file per message.

### M-10. Source checkouts identify as 0.1.0: every launch offers an "update", About and bug reports carry a useless version

- **Area:** Release. **Confidence:** Confirmed (`git show v2.1.2:src/config.py` still says `0.1.0`; tags reach v2.1.2).
- **Where:** `src/config.py:15`, `sim-cpdlc.iss:5` (0.3.1), `version_info.txt:9-10,34,39` (0.1.0), `.github/workflows/build-and-release.yml:40-41`, `src/utils/update_checker.py:112-125, 143-150`.
- **What is wrong:** `update_version.py` rewrites the three version strings only inside the release job and the result is never committed, so the tree disagrees with itself and with every release. `packaging.version.parse("2.1.2") > parse("0.1.0")`, so anyone running `python app.py` gets "A new version is available" a few seconds after start on every launch; answering Yes closes the app (M-5).
- **Fix direction:** Make the tag the single source of truth and commit the bump (release workflow commits the `update_version.py` output, or the maintainer runs it before tagging), or derive `APP_VERSION` from `git describe` when not frozen and skip the auto-check for development versions. Keep the three strings identical.

### M-11. Test fixtures are not hermetic: the real `config.json`, SimBrief and SimConnect are one call away

- **Area:** Tests. **Confidence:** Confirmed (mechanisms); no current test trips them.
- **Where:** `tests/test_main_window.py:60-64` (`window` fixture patches `load_config`, `_check_first_launch`, `wx.MessageBox` only), `tests/test_dialogs.py:13-25` (patches nothing), `tests/conftest.py:94-115` (`make_main_window`), `src/config.py:19-28` (real `CONFIG_FILE`, import-time `os.makedirs`), `src/gui/main_window.py:279` (`save_config` unpatched), `:1010, 1017` (real `load_config()` and `simconnect_manager` on every message from the current station), `connect_dialog.py:27,62`, `pdc_dialog.py:27,53` (real config, live SimBrief GET, modal box on failure).
- **What is wrong:** Nothing redirects `src.config.CONFIG_FILE` to a temp path. The first test that drives `on_settings` to OK will `os.replace` the developer's real `config.json` with the patched defaults (wiping both logon codes and the SimBrief id). Constructing `ConnectDialog` or `PDCDialog` in a test reads the real config and, on this machine (SimBrief id set), performs a live HTTPS request and opens a modal box on failure, hanging the run. A HANDOVER/LOGOFF/CONTACT uplink through `make_main_window` reads the real config and, with `auto_tune_com1` true, dereferences the unset `simconnect_manager`; through the real `window` fixture it would drive the real SimConnect. `tests/README.md` says `test_dialogs.py` covers "each request dialog", inviting exactly those tests. Every test run also creates the real user-data directory at import time.
- **Fix direction:** One autouse fixture: `CONFIG_FILE` → `tmp_path`; a `requests.get/post` guard that raises unless a test installed `serving()`; `get_latest_ofp` patched at both dialog import sites; a fake `SimConnectManager` and an injected config dict for `make_main_window`; assert `wx.GetTopLevelWindows()` is empty at `wx_app` teardown.

### M-12. The acknowledgement RR/MIN, the MRN check and half the response table have no regression tests

- **Area:** Tests. **Confidence:** Confirmed.
- **Where:** `tests/test_acknowledge_path.py:21-28` (unpacks `_own_min, _rr` and asserts only recipient/text/MRN), `tests/test_logon_status.py:15-16` and `tests/conftest.py:46-48` (`uplink` never sets an MRN, so the helper named `mrn` builds `/data2/1//NE/LOGON ACCEPTED`), `tests/test_cpdlc_session.py` (only `mrn=None` or `mrn=1` against pending MIN 1), `tests/test_message_manager.py:93-109` (covers `WU`, `R`, `NE` only).
- **What is wrong:** TODOS items 21, 22 and 24 (acks sent with `NE`, wrong `Y`/`N` response options, no MRN validation) are marked done but reverting any of them passes the suite: `RR.NO` on acknowledgements is never observed, the own MIN is discarded, the rejecting branch of the MRN check (`cpdlc_session.py:427-431`) is never entered, and `RR.YES → ["YES","NO"]`, `RR.NO → []`, `RR.AFFIRM_NEGATIVE` are untested. An unregistered WILCO is the single worst silent failure a CPDLC client can have.
- **Fix direction:** Assert the full frame `(STATION, 1, RR.NO.value, "WILCO", 53)` plus one connector-level test capturing the literal `/data2/1/53/N/WILCO`; give `uplink` an `mrn` parameter and add the mismatch case; parametrise the response table over all six `CpdlcResponseRequirement` members.

---

## Low

### L-1. "Connection problem (n/3) - retrying..." after a single failed send, until the next successful send
- **Where:** `src/model/connection_manager.py:310-316`, `src/controller/polling_controller.py:205-217`. **Confidence:** Confirmed.
- `poll_failed()` is `max(connection_failures, send_failures) > 0` and only a successful send clears `send_failures`, so one timed-out WILCO makes every subsequent good poll rewrite the status bar to a connection problem that is not happening; "Logged on to X." is lost. Report poll health from `connection_failures` only; keep the max for the reconnection decision.

### L-2. A TELEX reading `LOGON ACCEPTED` / `LOGOFF` / `HANDOVER XXXX` drives CPDLC session state
- **Where:** `src/gui/main_window.py:926-928, 946-1007`. **Confidence:** Confirmed (verified by execution: a `TelexMessage("EDGG", …, "logon accepted")` sets `current_station` to EDGG with no logon pending).
- The session-state block is gated on `hasattr(get_packet_content/get_from_name)`, which every `HoppieMessage` satisfies; telex has no `get_mrn`, so the MRN check is skipped. Gate on `isinstance(message, CpdlcMessage)` (already imported, unused) and use `get_message()`/`get_mrn()`/`get_rr()` instead of re-parsing the packet.

### L-3. Logon lifecycle has no negative paths
- **Where:** `src/gui/main_window.py:956, 968-1007`, `src/model/cpdlc_session.py:396-451`. **Confidence:** Plausible.
- Acceptance requires exactly `LOGON ACCEPTED`; a station appending anything leaves the app pending while the station considers it connected, and every later uplink from it is unanswerable. No handling of a rejection, no pending timeout, no periodic `ping(current_station)` to notice a controller who left without LOGOFF (common on VATSIM). Match on `startswith`, clear pending state on `LOGON REJECTED`/an `UNABLE` with the pending MRN, expire pending after a few minutes, ping the station occasionally.

### L-4. Weather cycle has no deadline; an in-flight cycle survives reconnect and may mix credentials
- **Where:** `src/model/weather_monitor.py:107, 120-125, 253-255, 262-269, 278-298`, `src/model/connection_manager.py:246-251, 264-270, 408-418`. **Confidence:** Confirmed.
- A stuck request (per-read timeout, unbounded DNS) keeps `_cycle_running` true for the rest of the session, silently disabling updates while "Check now" says a check is running; ten subscriptions can exceed the 5-minute interval on a slow link. `stop()` sets a flag the worker samples once per subscription; disconnect and reconnect inside that window lets the old worker finish under the new session's credentials, and the worker reads `logon_code`/`callsign`/`network_type` one attribute at a time while the GUI thread writes them, so a mixed snapshot (one network's URL with the other's logon code) is possible. Use a cycle generation number checked in `_post_result`/`_on_result`, snapshot credentials on the GUI thread and pass them to the worker, and give the cycle a budget.

### L-5. Worker-thread `IsBeingDeleted()` guards do not work and can raise at exit
- **Where:** `src/model/weather_monitor.py:304, 310-311`, `src/utils/update_checker.py:48`, `app.py:47-51, 59-60`. **Confidence:** Confirmed mechanism, Plausible timing.
- For a top-level frame the flag is set only inside the destructor (the deferred `Destroy()` does not set it), so from the worker the call is either "alive" or `RuntimeError: wrapped C/C++ object … has been deleted`; it is also a wx call from a non-GUI thread. At exit with a fetch in flight the worker dies, `threading.excepthook` calls `wx.CallAfter`, and once the `wx.App` is gone that raises `AssertionError('No wx.App created yet')` inside the excepthook. Use a Python-side flag set by `shutdown()`, wrap `wx.CallAfter` in the worker, and skip the dialog in the reporter when `wx.GetApp()` is None.

### L-6. SimBrief diagnostics never reach the log file; the console handler is dead in the windowed build
- **Where:** `src/utils/simbrief.py:8` (`getLogger(__name__)`), `src/logging_setup.py:12-27`, `connect_dialog.py:77-83`, `pdc_dialog.py:93-99`. **Confidence:** Confirmed (verified: the `src.utils.simbrief` logger has no handlers and root has none).
- Every SimBrief failure reason (timeout, HTTP 400 for an unknown id, non-JSON) is logged to an orphan logger and the dialogs log only "Failed to fetch SimBrief OFP data"; the `except Exception` branches in the dialogs are unreachable because `fetch_ofp` swallows everything. In the frozen build `StreamHandler()` wraps a `None` stderr. Use the `"Sim-CPDLC"` logger (or a child), return an error string, and add the console handler only when `sys.stderr` is not None.

### L-7. Input validation gaps in the request dialogs
- **Where:** `altitude_change_dialog.py:72-85, 94-98`, `direct_request_dialog.py:62-68`, `speed_request_dialog.py:88-106`, `when_can_we_dialog.py:104-117`, `telex_dialog.py`. **Confidence:** Confirmed (verified: `int("35_0") == 350`, `int("+350") == 350`, full-width digits pass `isdigit()`; the library accepts `REQUEST FL35_0`).
- Altitude uses `int()`, so `3_50` is transmitted as `REQUEST FL3_50` (while the pilot's own list shows `FL350`, because underscores are stripped for display), `+350` and Unicode digits fail later with "invalid characters", and two-digit levels go out unpadded. Direct-to rejects legitimate fixes with digits (`55N020W`, `5530N`) and anything over five characters, while `isalpha()` admits non-ASCII letters. Speed/When-can-we use `isdigit()` (Unicode digits pass) and the Mach/knots branches are identical (`M820` accepted). Telex gives no feedback about the 220-character/ASCII limits until after OK. Validate with ASCII regexes (`^\d{2,3}$`, `^[A-Z0-9]{2,7}$`), zero-pad levels, show remaining characters in Telex.

### L-8. Unredacted logon code survives in the exception chain; DEBUG logging prints both logon codes
- **Where:** `src/model/connection_manager.py:137, 141-143, 181` (`raise … from exc`), `app.py:39-42`, `src/controller/polling_controller.py:171`, `src/config.py:52, 85`. **Confidence:** Confirmed (verified: `str(exc)` is clean, `traceback.format_exception(exc)` contains the code via `__cause__`).
- `redact()` scrubs the message but the original `requests` exception with `?logon=…` is kept as `__cause__`, which traceback formatting prints in full; every `HoppieError` is caught today, so this is dormant but one `logger.exception` away. `Loaded config`/`Saved config` debug lines include both logon codes, at exactly the level a user would be asked to enable for troubleshooting. Raise with `from None` (or a redacted cause), redact the config dict before logging, run `redact()` in the global handler's log line.

### L-9. `on_disconnect` sleeps 500 ms on the GUI thread for nothing and re-arms polling before stopping it
- **Where:** `src/gui/main_window.py:383-391`. **Confidence:** Confirmed. `send_cpdlc` is synchronous, so the "small delay to allow the message to be sent" only freezes the loop; `set_active_polling()` three lines before `stop()` is a no-op pair. Delete both.

### L-10. Settings applies the weather interval before the save succeeds
- **Where:** `src/gui/main_window.py:277-292`. **Confidence:** Confirmed. `set_interval` runs before `save_config`; on failure the session and the file disagree and the success text ("used for future operations") is inaccurate either way. Apply runtime changes inside the success branch.

### L-11. `resource_path` resolves against the current directory in development mode
- **Where:** `src/gui/main_window.py:56-64, 82-89`. **Confidence:** Confirmed. `python C:\…\app.py` from another directory shows the missing-sound warning on every start and plays no sound. Use the directory of `app.py`.

### L-12. `@@` becomes `N/A` glued to neighbouring words; list columns never resized
- **Where:** `src/utils/message_formatting.py:25-30, 39-41`, `src/gui/message_view.py:56-62`. **Confidence:** Confirmed (verified: `FL360@@REPORT LEVEL` → `FL360N/AREPORT LEVEL`, read by NVDA as "FL360N slash AREPORT"). Pad the substitution or drop it; columns are `LIST_AUTOSIZE`d once while empty (Plausible).

### L-13. `dlg.Destroy()` is skipped when anything raises between `ShowModal()` and the end of the handler
- **Where:** every `ShowModal … Destroy` pair in `src/gui/main_window.py` (259-296, 320-347, 417-449, 513-533, 554-570, 591-609, 630-646, 673-690, 720-754, 810-840). **Confidence:** Confirmed. The unconverted local `OSError`s are exactly what can raise there. Use `with Dialog(...) as dlg:` or `try/finally`.

### L-14. Exception reporter opens a modal inside the failing handler; `OnExceptionInMainLoop` and the Ctrl+C branch are dead or wrong
- **Where:** `app.py:31-51, 53-57, 66-76, 100-107`. **Confidence:** Confirmed.
- Python exceptions in wx handlers are already routed to `sys.excepthook` by wxPython; `OnExceptionInMainLoop` only runs for C++ exceptions, where `sys.exc_info()` is all `None` and `issubclass(None, KeyboardInterrupt)` raises `TypeError`. `wx.App()` defaults to `clearSigInt=True` (SIGINT → `SIG_DFL`), so Ctrl+C kills the process and the `KeyboardInterrupt` branch never runs (and would call `on_exit` on a possibly destroyed frame). The synchronous `wx.MessageBox` in the reporter lets timers re-enter under it (see M-4). Guard on `exc_type is not None`, decide on `clearSigInt`, show the report via `wx.CallAfter` and coalesce.

### L-15. `_confirm_exit` ignores `CanVeto()`; first-launch prompt runs mid-`__init__`
- **Where:** `src/gui/main_window.py:1077-1079, 1111-1121, 79, 1142-1153`. **Confidence:** Confirmed. On a forced close (Windows end-session) the confirmation still blocks and `Veto()` trips a wx assertion, skipping cleanup. The welcome dialog runs a modal loop before `_init_ui`, before `EVT_CLOSE` is bound and before the controllers exist; safe today only because nothing else can run in that loop (the follow-up `on_settings` is correctly deferred). Check `CanVeto()`; schedule the first-launch prompt after construction.

### L-16. Weather subscriptions dialog gives no confirmation on stop and can list stale entries
- **Where:** `src/gui/dialogs/weather_subscriptions_dialog.py:94-104, 131-157`. **Confidence:** Confirmed. The other two stop paths add a SYSTEM row and status text; this one only removes the row. `_on_result` runs during the dialog's modal loop, so a subscription dropped after five failures stays listed until the next refresh. Route through the same helper; refresh from `on_error`/`on_update`.

### L-17. Smaller protocol and parsing points
- **Where:** `src/model/connection_manager.py:443-446`; `src/gui/main_window.py:970`; `src/utils/frequency_parser.py:7-14`; `src/controller/polling_controller.py:261-291`. **Confidence:** Confirmed (parser cases verified by execution).
- `error {no data}` is surfaced as "METAR request error: {no data}" (braces kept). `^HANDOVER\s+([A-Z]{4})$` handles `HANDOVER @EDYY@` but any trailing text defeats it (the message is still shown). `extract_contact_frequency("CONTACT 121.500")` returns None because the pattern demands a unit name; realistic texts with a unit name all parse, and the DOTALL comment is inaccurate. Every non-acknowledgement uplink, including `LOGON ACCEPTED`/`LOGOFF`/`HANDOVER`, starts five minutes of 20 s polling, while an ATC `STANDBY`/`ROGER` does not extend the window even though a reply is then expected.

### L-18. README and docs drift
- **Where:** `README.md:20, 28-30, 84-91, 109-110`, `tests/README.md:17-30`, `app.py:3`. **Confidence:** Confirmed (`hoppie_connector-0.2.1` METADATA: `Requires-Python: >=3.12`; the library uses `StrEnum`, `typing.Self`, `match`).
- "Python 3.7 or higher" is wrong by five minor versions (pip fails on anything below 3.12; CI uses 3.13). The altitude section describes a climb/descent choice the dialog does not have. "The report is added … and the notification sound plays" contradicts the deliberate quiet policy for requested reports. "Automatic Reconnection" overstates H-2. The tests table omits `test_config.py` and `test_weather_parsing.py` and claims dialog and downlink coverage that does not exist. `app.py`'s docstring names only SayIntentions.

### L-19. Packaging and requirements
- **Where:** `requirements.txt:2, 7`, `app.spec:11-18, 35`, `.gitignore`, `.github/workflows/build-and-release.yml`, `.github/workflows/tests.yml`. **Confidence:** Confirmed.
- `pyinstaller==6.20.0` sits in the runtime requirements. `SimConnect>=0.4.26` is the only unpinned dependency, and `app.spec` bundles `SimConnect.dll` only if it happens to be present, so a build machine without it ships an installer whose auto-tune never works, with only a PyInstaller warning. `.gitignore` lacks `installer/` and `.pytest_cache/`. The release workflow does not run the test suite and `fetch-depth: 0` is unused; the test job has no `timeout-minutes`, so an unstubbed modal dialog hangs it for six hours. The three checked-in version strings differ (0.1.0 / 0.3.1 / 0.1.0).

### L-20. Personal SimBrief data and a live-API script committed under `src/`
- **Where:** `src/utils/latest_simbrief_ofp.json` (164 KB, since the initial commit: real name, SimBrief user id, full OFP), `src/utils/test_simbrief.py:20, 42-47` (hard-coded id 189007, overwrites the JSON, one `pytest src` away from being collected). Neither is used by the application. Delete or move to `tools/` reading the id from the environment; ignore the output file.

### L-21. Test-suite weaknesses (beyond M-11/M-12)
- **Confidence:** Confirmed. Details and a full coverage map are in the tests report (appendix).
- `test_every_menu_item_has_a_handler` checks only that methods exist; deleting a `Bind` passes. `test_menu_shown_for_a_message_from_the_current_station` asserts only that a menu popped, never its items, the closure capture or the post-popup `Unbind` (TODOS 2). `test_context_menu_follows_the_session_after_a_handover` never opens a context menu. `test_repeated_failures_drop_the_subscription` cannot tell `MAX_CONSECUTIVE_ERRORS == 5` from `== 1`. The weather monitor's real thread path is exercised only incidentally by `test_check_now_says_a_cycle_started`, which returns while the worker is still running. The two `install_request_timeout` tests monkeypatch only `requests.get`, leaving `requests.post` permanently wrapped for the rest of the session. `from conftest import …` relies on pytest's default import mode. The `wx.MessageBox` stub returns `None`, so every future "!= wx.YES" confirmation silently cancels. Weak assertions: `status_texts != []`, `timeout is not None`, inforeq params never asserted.
- **Untested (highest risk first):** `on_connect`/`on_disconnect`/`on_close`; PollingController reconnection branch and `_report_connection_state`; HANDOVER, LOGOFF and CONTACT branches of `_on_message_received`; `CpdlcSession.logon`/`logoff`/`send_speed_request`/`send_pdc_request`/all failure paths (`FakeConnectionManager` never raises); `load_config`/`save_config`; `frequency_parser`, `message_formatting`, `simconnect_manager`, `update_checker`; nine of ten dialogs; `WeatherMonitor.set_interval`, re-subscribe with new text, error-count reset; `on_message_selected`.

---

## Info

### I-1. Unused imports and dead code
`src/gui/main_window.py:9-14` (`CpdlcMessage`, `RR`, `HoppieMessage`), `src/model/cpdlc_session.py:3-4` (`logging`, `Callable`), `src/controller/polling_controller.py:5` (`logging`) — all verified by AST scan. `MessageManager.get_weather_key` and `MessageView.clear` have no callers. `PollingController.default_poll_interval` is stored and never read (the docstring describes a path that cannot occur). `ConnectionManager.message_callback` is unused. `poll_status` is actually a `timedelta` and is discarded. `extract_atis_letter`'s `icao` parameter is dead. The "Always enable both logon and logoff menu items" comment describes removed code.

### I-2. Duplication the PR-24 spec left open, still open
Seven handlers hand-roll the "Not Connected" box although `_require_connection` exists (used once); five hand-roll "Not Logged On". `send_altitude_change_request`, `send_direct_request`, `send_speed_request`, `send_when_can_we_expect` differ only in the text. `_on_message_received` repeats the extract/normalise block twice and re-parses packets that `CpdlcMessage.get_message()` already exposes. `_check_first_launch` re-imports `os`, `load_config`, `save_config` locally (a local import that would also bypass the test monkeypatch).

### I-3. Indirection with no purpose
`send_logoff_message` is an alias "for backward compatibility" in an app with no external callers. `MainWindow.get_current_station` wraps the session behind a check equivalent to the session's own; its one consumer, `TelexDialog`, reaches into `parent.get_current_station()` instead of taking the value as an argument. `resource_path` is an instance method that never uses `self`.

### I-4. Accessibility conventions are applied unevenly
Mnemonics and `SetName` only in the weather dialogs and the Settings spin control; `ConnectDialog`'s `RadioBox` has an empty label with a separate static text; helper texts use a hard-coded grey `wx.Colour(100,100,100)` that ignores high-contrast themes; accelerators reuse OS conventions (`CTRL+S`, `CTRL+W`, `CTRL+O`). Menu mnemonic uniqueness is tested; dialogs are not.

### I-5. Miscellaneous
`check_polling_timeout` uses wall-clock `time.time()`. `cpdlc_min_counter` never wraps (FANS-1/A MIN is modulo 64; whether Hoppie ATC clients care is unverified). Hoppie's own change log says VATSIM/IVAO ATIS is cached for five minutes server-side, so a 1-minute ATIS interval buys nothing against Hoppie. No `requests.Session`, so every call is a fresh TLS handshake (fine at these rates). Type hint `sender: str = None` should be `Optional[str]`. About dialog copyright year is fixed at 2025. The stale review worktree `.claude/worktrees/review-25-ceb148` (excluded via `.git/info/exclude`) holds the only local environment with the app's dependencies.

---

## Recommended new tests (prioritised)

1. Full acknowledgement frame `(STATION, 1, RR.NO.value, "WILCO", 53)` and a connector-level `/data2/1/53/N/WILCO` capture (M-12).
2. Hermetic conftest: `CONFIG_FILE` → `tmp_path`, network guard, SimBrief patched, fake SimConnect, empty top-level-window assertion (M-11).
3. HANDOVER through the window: station cleared, `("EDGG", 1, "Y", "REQUEST LOGON", None)` sent, both status texts, active polling bumped; negative from a non-current station.
4. LOGOFF and `LOGOFF NOT REQUIRED…` from the current station (TODOS 23); `CURRENT ATC UNIT` filter.
5. CONTACT auto-tune with a fake SimConnect: tuned / disabled / failed-status / non-current station.
6. Telex bodies never drive session state (L-2).
7. PollingController link reporting and both reconnection outcomes, exact status texts, `is_running()` afterwards.
8. MRN mismatch rejection; response table over all six RR members.
9. Context menu labels, item firing, no stale binding after close.
10. Every downlink literally, plus every failure path via a raising fake.
11. Weather monitor with a synchronous thread stub: announce once, second `check_now()` refused, error-count reset, re-subscribe re-seeds, `set_interval` restarts.
12. Per-dialog OK-button tables and getter literals; `load_config`/`save_config` on `tmp_path`; `frequency_parser` and `message_formatting` tables; `on_connect`/`on_disconnect`/`on_close` through the real window with dialogs stubbed.

---

## Verified as sound

- `install_request_timeout()` reaches the library: `hoppie_connector/API.py` calls `requests.get`/`requests.post` as module attributes; both arrived with `timeout=15` (verified by execution). No outbound call lacks a timeout.
- Error classification at the boundary (transport vs protocol vs `OSError` pass-through), the three separate failure counters, and `should_attempt_reconnection` requiring a live `cnx` behave as the tests describe. `redact()` covers every `HoppieError` message built in `_call`; no f-string formats the logon code; both URLs are HTTPS.
- RR values on downlinks match real Hoppie traffic (`Y` for logon/requests, `NE` for LOGOFF, `N` with `mrn` for acknowledgements); MIN advances only on successful sends. LOGON ACCEPTED validation against the pending station and MRN is right; unsolicited acceptances still work; `extract_message_content` strips every prefix shape the library emits.
- Polling rate: idle re-randomised in 45–75 s per tick, 20 s active, one-shot re-armed in `finally`, `set_active_polling` only pulls a poll forward; no path polls faster than 20 s; the 15 s timeout and post-failure back-off comply with Hoppie's published request ("skip this attempt and come back after your normal random delay").
- WeatherMonitor ownership model (GUI-thread state, snapshot to worker, results via `CallAfter`, `_on_cycle_finished` posted last), timer lifecycle across start/stop/shutdown/start, `check_now()` reporting, `_on_result` tolerance of unsubscribe-in-flight, interval clamping.
- MessageView context menus: per-item bind/unbind around `PopupMenu`, lambda defaults, no accumulation (TODOS 2 fixed); message encodings round-trip; every message type `poll()` can return is displayable and only `CpdlcMessage` is answerable.
- `on_close` ordering, `Skip()`/`Veto()` pairing on normal paths, `config.py` atomic write and error handling, packaging paths in `app.spec`/`.iss`/`update_version.py`, the `global` statement in `simconnect_manager.py`, and every item previously recorded as fixed in `TODOS.md` and the PR-24 spec.

---

## Questions before planning fixes

1. **H-1 calibration.** Do your own Hoppie message logs (the web log for a past flight versus `sim-cpdlc.log`) show CPDLC uplinks containing `/ , : - ( )` or lowercase text? That decides whether H-1 needs a permissive parser or just logging plus a SYSTEM row.
2. **Reconnection policy (H-2).** Keep retrying with back-off indefinitely while showing the state, or stop after N minutes? Should a lost/restored connection play the notification sound?
3. **Session state across reconnects (M-1).** When reconnecting with the *same* callsign, should the ATC logon be kept (current behaviour, arguably correct for Hoppie) and only be reset when the callsign or network changes?
4. **Threading scope (H-3).** Move all CPDLC I/O to a worker now, or start with the cheap wins (SimBrief out of constructors, manual weather and update check threaded, split timeouts)?
5. **Update checker (M-5/M-10).** Is "Yes closes the app" intended? Should development runs (version 0.1.0 or a `git describe` string) skip the automatic check?
6. **`@@` → `N/A` (L-12).** Is that substitution still matched by observed traffic, or should empty placeholders simply collapse?
7. **Manual logon while logged on (M-7).** Refuse, or send LOGOFF to the current station first?
8. **Python floor (L-18).** Document 3.12 (the library's minimum) or 3.13 (what CI runs)?

---

## Appendix: verification performed

- Baseline: `python -m pytest -q -p no:cacheprovider` → 135 passed in 1.21 s (worktree venv; global Python 3.14 has none of the dependencies).
- Execution checks (scratchpad scripts, in-process fakes, no network): library parse whitelist and `poll()` warning behaviour (H-1); ASCII decode failure through `ConnectionManager.poll()` (M-2); inforeq envelope cases `ok {server info {}}`, `ok`, `ok {server info { }}`, `error {no data}`, HTML (M-6); timeout monkeypatch reaching the library; frequency-parser cases; `extract_message_content` cases; `int()`/`isdigit()` validation edge cases and library acceptance of `REQUEST FL35_0` (L-7); SimBrief logger handlers (L-6); AST scan for unused imports (I-1); `wx.CallAfter` without an App (L-5); telex-driven `LOGON ACCEPTED` (L-2); `OSError` escaping `attempt_reconnection` (M-4); `__cause__` retaining the logon code (L-8); `@@` formatting (L-12); `Requires-Python` of the pinned library and `APP_VERSION` at tags v2.0.0/v2.1.2 (L-18, M-10).
- External references: Hoppie ACARS technical page (poll timing and 15 s guidance; no character-set rule published); upstream Python-SimConnect source (`send_event` returns False, `map_to_sim_event` returns None, daemon dispatch thread, no retry on open).
- Lens reports with full detail (including the complete test coverage map): `docs/audit/lens/2026-09-03-threading-lifecycle.md`, `docs/audit/lens/2026-09-03-network-protocol.md`, `docs/audit/lens/2026-09-03-gui-state-config.md`, `docs/audit/lens/2026-09-03-test-suite.md`.
