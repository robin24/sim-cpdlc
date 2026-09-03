# Sim-CPDLC — network / protocol / credential audit

Scope: `app.py`, everything under `src/`, the tests (read for intent), and all of `hoppie_connector` 0.2.1 (`__init__.py`, `API.py`, `Messages.py`, `Responses.py`, `Utilities.py`, `CPDLC.py`, `ADSC.py`). Read-only. Mechanisms marked *Confirmed* were either traced end-to-end in the code or reproduced with the venv interpreter using in-process fakes for `requests.get`/`post` (no network traffic).

Key library facts the findings rest on (all verified in source):

- `hoppie_connector/API.py:39,44` calls `requests.get(...)` / `requests.post(...)` as **module attributes** after `import requests`. The app's `install_request_timeout()` therefore does take effect — reproduced: the library's GET and POST both arrived at the underlying function with `timeout=15`.
- `API.py:46-47` raises the **builtin** `ConnectionError` for a non-2xx status; `API.py:50` decodes the body with `.decode('ascii')` (a `UnicodeDecodeError`, subclass of `ValueError`, for any non-ASCII byte); the response parsers raise bare `ValueError`; `_connect` raises `TypeError` or `HoppieError(reason)` for `error {...}`.
- `__init__.py:66-85` `poll()` parses each `{FROM type {packet}}` item and, on `ValueError`, calls `warnings.warn(..., HoppieWarning)` and **drops the item**. Nothing is raised.
- `Messages.py:602,613,639-641` `CpdlcMessage` accepts only `[A-Z0-9._@ ]+` as message text, so a CPDLC packet with `-`, `,`, `:`, `/`, `(`, `)`, lowercase letters or an empty text is unparseable.
- `CpdlcMessage` exposes `get_min()`, `get_mrn()`, `get_rr()` (a `CpdlcResponseRequirement` StrEnum: WU, AN, R, NE, N, Y), `get_from_name()`, and `get_message()` (the bare element text); `get_packet_content()` re-serialises `/data2/{min}/{mrn or ''}/{rr}/{text}`.
- `Utilities.py:4` validates every FROM/TO station as `^[A-Z0-9]{3,8}$`; `TelexMessage` enforces ≤220 chars and ASCII.

---

## Findings

### 1. Uplinks the library cannot parse are dropped with no trace, after the server has already marked them delivered

- **Severity**: High — an ATC instruction the controller's client shows as *delivered* never reaches the pilot, and nothing in the log or UI says so.
- **Confidence**: Confirmed (mechanism reproduced); how often real stations send such text is Plausible rather than measured.
- **Location(s)**: `hoppie_connector/__init__.py:77-85`, `hoppie_connector/Messages.py:602-623,639-641`; `src/model/connection_manager.py:284-308`; `src/controller/polling_controller.py:149-176`; `app.spec:59` (`console=False`).
- **What is wrong**: `HoppieConnector.poll()` swallows every per-message `ValueError` into a Python `warnings.warn(HoppieWarning)`. The application never captures warnings (`logging.captureWarnings` is not enabled, there is no `catch_warnings` around `cnx.poll()`), and in the packaged build `sys.stderr` is `None`, where `warnings._showwarnmsg_impl` explicitly returns without output. `ConnectionManager.poll()` sees a clean `([], delay)`; no counter moves, no log line is written, no UI element changes. Because Hoppie's `poll` marks messages as relayed when it serves them, the message is gone for good.
- **Failure scenario**: Controller sends `CLIMB TO FL350 - EXPEDITE`, `FREE TEXT: CALL ME ON 121.5`, `CONTACT LANGEN 127,825`, a message containing `/`, or (from a less strict client) lowercase text. Reproduced with a poll body of five items: the app received only the one plain item; four `HoppieWarning`s were emitted and nothing was logged by the app. Pilot sees nothing; controller sees "delivered", waits for WILCO, then escalates by voice or assumes non-compliance.
- **Evidence**:
  ```python
  # hoppie_connector/__init__.py
  80:        for d in response.get_data():
  81:            try:
  82:                result.append(p.parse(d))
  83:            except ValueError as e:
  84:                warnings.warn(f"Unable to parse {d}: {e}", HoppieWarning)
  # hoppie_connector/Messages.py
  602:    _MSG_CHARS: re.Pattern = r'[A-Z0-9\.\_\@ ]'
  613:        m = re.match(r'^/' + cls._EXCHG_FORMAT_PREFIX + r'/(\d+)/(\d*)/(WU|AN|R|NE|N|Y)/(' + cls._MSG_CHARS + r'*)$', packet)
  ```
  Reproduction output: `poll returned messages: ['EDGG -> DLH123 [CPDLC] /data2/6//WU/CONTACT LANGEN 127.825']`, warnings: `Invalid CPDLC message format` ×3, `Message contains invalid characters` ×1; `ConnectionManager.poll -> ([], 0.1), connection_failures 0, app log lines []`.
- **Suggested fix direction**: Wrap `self.cnx.poll` in `warnings.catch_warnings(record=True)` (filter `HoppieWarning`), log each dropped item at ERROR with its `from` and raw packet, and inject a SYSTEM/list entry such as "Unreadable message from EDGG: <raw packet>" with the notification sound so the pilot can ask by voice. Longer term consider parsing `cpdlc` items yourself with a permissive regex (the app already has `extract_message_content`), since the library's character class is stricter than what Hoppie's ATC clients emit.

### 2. CPDLC session state outlives the network connection

- **Severity**: Medium — after a lost or failed-logoff disconnect the app can report and act on a logon that no longer exists, sending requests and a later LOGOFF to a stale station, under a possibly different callsign.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:349-402` (`on_disconnect`), `316-347` (`on_connect`); `src/controller/polling_controller.py:182-196`; `src/model/cpdlc_session.py:108-141` (`logoff` leaves `current_station` set on failure), `24-28` (state fields).
- **What is wrong**: `ConnectionManager.disconnect()` clears its own fields, but nothing resets `CpdlcSession.current_station`, `pending_logon_min/station` or `cpdlc_min_counter`. `on_disconnect` only clears `current_station` indirectly by *successfully sending* LOGOFF; if that send fails (which is likely exactly when the user is disconnecting because the link is dead) `logoff()` returns `(False, err)` and leaves the station set. The polling controller's failed-reconnection branch (`attempt_reconnection()` → `cnx = None`, `stop()`) never touches the session either, and does not reset the `&Disconnect` menu label.
- **Failure scenario**: Logged on to EDGG. Wi-Fi drops; three polls and the ping fail; status reads "Connection lost. Reconnect to continue."; `current_station` is still `EDGG`, `menu_item_connect` still reads "Disconnect". The pilot reconnects (File menu — the "Disconnect" item opens the Connect dialog because `is_connected()` is False), perhaps as a different flight/callsign. Status: "Connected as X." but `is_logged_on()` is True: the Requests menu sends `REQUEST FL350` to EDGG with the old MIN sequence, `on_logoff` offers to log off from EDGG, `get_current_station()` feeds the message view so old EDGG uplinks become answerable again. Same result via user-initiated disconnect when the LOGOFF POST times out.
- **Evidence**:
  ```python
  # main_window.py on_disconnect
  379:        if self.cpdlc_session.is_logged_on():
  380:            success, message = self.cpdlc_session.send_logoff_message()
  ...
  394:        self.connection_manager.disconnect()     # no cpdlc_session reset anywhere
  # cpdlc_session.py logoff
  130:        except HoppieError as exc:
  134:            return False, str(exc)               # current_station untouched
  # polling_controller.py
  191:                    self.logger.error("Reconnection failed")
  192:                    self._set_status("Connection lost. Reconnect to continue.")
  196:                    self.stop()                  # session, menu label, weather monitor untouched
  ```
- **Suggested fix direction**: Add `CpdlcSession.reset()` (clear station, pending logon, restart MIN) and call it from `on_disconnect` (after the LOGOFF attempt, regardless of its outcome) and from the failed-reconnection path; have the controller notify the window (callback) so it can flip the menu label and add a SYSTEM message on connection loss.

### 3. A manual logon while already logged on sends no LOGOFF, keeps the old station current, and restarts MIN at 1 towards a station that has already seen those MINs

- **Severity**: Medium — leaves one station believing the aircraft is still logged on, and produces duplicate MINs for the same dialogue.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:404-449` (`on_logon` checks only `is_connected()`); `src/model/cpdlc_session.py:62-106` (`logon` resets `cpdlc_min_counter = 1`, never clears `current_station`).
- **What is wrong**: `logon()` is callable in any state. It resets the MIN counter to 1 and records a pending logon, but leaves `current_station` as it was. Until the new station accepts, `is_logged_on()` is still True for the *old* station, so every request goes to the old station numbered 2, 3, … — MINs that station already received earlier in the session. If the new station accepts, `current_station` flips with no LOGOFF ever sent to the old one. Re-logging on to the *same* station (a natural thing to try when the pilot suspects they were dropped, since the app gives no indication either way) also restarts MIN at 1 on a dialogue the station may consider still open.
- **Failure scenario**: Pilot logged on to EDGG at MIN 9 selects Requests > Logon > EDUU by mistake or design. Status: "Pending logon to EDUU." Pilot sends an altitude request: it goes to EDGG as MIN 2 (a MIN EDGG already saw paired with `REQUEST LOGON`'s successor). EDUU accepts: EDGG still shows the aircraft logged on, keeps uplinking; those uplinks appear in the list but offer no responses (sender ≠ current station); controller at EDGG sees no WILCO.
- **Evidence**:
  ```python
  # cpdlc_session.py
  84:        self.logger.info(f"Attempting to logon to station: {station}")
  85:        self.cpdlc_min_counter = 1
  ...
  103:        # Don't set current_station yet, just increment the counter
  ```
- **Suggested fix direction**: In `on_logon`, if `is_logged_on()`, either refuse ("log off first") or send LOGOFF to the current station and clear it before sending the new REQUEST LOGON. Only restart the MIN counter when the previous dialogue was actually closed (LOGOFF sent/received or handover); otherwise keep counting.

### 4. Reconnection is attempted exactly once, then polling stops for good — silently for a screen-reader user

- **Severity**: Medium — a 60-second outage in active mode (or ~3 minutes idle) ends the session permanently, with the only indication being status-bar text; the README promises "Automatic Reconnection".
- **Confidence**: Confirmed.
- **Location(s)**: `src/model/connection_manager.py:318-350`; `src/controller/polling_controller.py:182-196, 205-217`; `src/gui/main_window.py` (no SYSTEM message, sound or menu-label change on this path).
- **What is wrong**: After `MAX_CONNECTION_FAILURES` (3) the controller calls `attempt_reconnection()` *in the same tick*, with no back-off; that pings once, and on failure `cnx` is cleared and the timer is stopped forever. There is no retry schedule, no notification sound, no list entry — unlike connect/disconnect, which both add SYSTEM messages. `_set_status` is the only output, which NVDA users must actively query.
- **Failure scenario**: Mid-exchange (active mode, 20 s polls) the home router reboots for 70 s. Polls at t=0, 20, 40 fail; the ping at t=40 fails; polling stops. The router is back at t=70 but the client never polls again; the controller's next uplink sits on the server; the pilot, who heard no sound, keeps waiting for a reply.
- **Evidence**:
  ```python
  # polling_controller.py
  186:                success = self.connection_manager.attempt_reconnection()
  ...
  196:                    self.stop()
  # connection_manager.py
  347:        except HoppieError as exc:
  349:            self.cnx = None
  ```
- **Suggested fix direction**: Keep polling with exponential back-off (e.g. 20 s → 60 s → 120 s, capped) rather than stopping; treat `attempt_reconnection` as re-verifying rather than terminal; on the transition to "lost" add a SYSTEM message and play the notification sound; update the menu label. Consider the reconnection a state the controller owns instead of a one-off branch.

### 5. A single non-ASCII byte anywhere in a poll body loses every message in that poll and counts as a link failure

- **Severity**: Medium — a batch of valid uplinks is consumed server-side and never shown; three such polls trigger the reconnection logic.
- **Confidence**: Plausible — mechanism Confirmed by reproduction; whether Hoppie/SayIntentions ever relay non-ASCII bytes to an aircraft is unverified (the library refuses to *send* them, but other clients and SayIntentions' own text are not bound by that).
- **Location(s)**: `hoppie_connector/API.py:50` (`response.content.decode('ascii')`); `src/model/connection_manager.py:136-143, 296-308`.
- **What is wrong**: The decode happens on the whole body before any per-message parsing, so one `°`, `–` or umlaut in any telex/ATIS/free text raises `UnicodeDecodeError` (a `ValueError`) for the entire response. `_call` converts it to a protocol `HoppieError`; `poll()` logs "Poll error: 'ascii' codec can't decode…" and increments `connection_failures`. The messages were already served and therefore marked relayed.
- **Failure scenario**: Reproduced: body `ok {EDGG cpdlc {/data2/5//WU/CLIMB TO FL350}} {EDDF telex {WIND 270°/25KT}}` → `poll()` returned `(None, None)`, `connection_failures` 1, status "Connection problem (1/3) - retrying…", and the CLIMB instruction is gone.
- **Evidence**: `API.py:50: content = response.content.decode('ascii')`; reproduction log: `ERROR: Poll error: 'ascii' codec can't decode byte 0xb0 in position 67`.
- **Suggested fix direction**: The app cannot change the decode inside the library, but it can subclass/shadow `HoppieAPI.connect` (the `HoppieConnector._api` attribute) to decode with `errors="replace"` (or `latin-1`) before handing the text to the parser, and at minimum distinguish this error in the log/status from a transport outage so it is not reported as a connection problem.

### 6. `_SERVER_INFO_PATTERN` cannot match an empty envelope, so the "no report" guard is dead and `{server info {}}` is shown as weather

- **Severity**: Low — cosmetic for a manual request, but for a subscription it means the "give up after 5 failures" logic never engages for an airport with nothing to report.
- **Confidence**: Confirmed (regex behaviour reproduced); that the server answers exactly `ok {server info {}}` is Plausible (it is what the code's own comment assumes).
- **Location(s)**: `src/model/connection_manager.py:32, 435-442, 470-475`.
- **What is wrong**: `(.+)` requires at least one character; for `{server info {}}` the match fails, the unwrapping is skipped and the *literal envelope string* is returned. `send_info_request`'s `if not report_text` therefore never fires for the case its comment describes. A bare `ok` (no space) falls to the "Unexpected response: ok" branch, which reads like a fault rather than "no data".
- **Failure scenario**: Reproduced: body `ok {server info {}}` → `send_info_request` returned `'{server info {}}'`; body `ok` → `HoppieError: Unexpected response: ok`. A pilot subscribing to a mistyped ICAO gets a list entry "ATIS ZZZZ: {server info {}}" and the subscription lives forever (each cycle returns the same text → "no change").
- **Evidence**: `32: _SERVER_INFO_PATTERN = re.compile(r"^\{server info \{(.+)\}\}$", re.DOTALL)`; `471: if not report_text:`.
- **Suggested fix direction**: Use `(.*)`; treat `body == "ok"` and an empty inner text as "no report available"; keep the `error {}` branch but strip the braces from the reason.

### 7. Session-control detection does not check the message type: a TELEX reading `LOGON ACCEPTED`, `LOGOFF` or `HANDOVER XXXX` drives CPDLC state

- **Severity**: Low — requires a station (or anyone on the open Hoppie network using that station code as `from`) to send such a telex, but the fix is one `isinstance`.
- **Confidence**: Confirmed (a `TelexMessage("EDGG", …, "logon accepted")` yields `msg_text == "LOGON ACCEPTED"` after `extract_message_content`, and `get_mrn` is absent so `mrn=None`, which `handle_logon_accepted` accepts).
- **Location(s)**: `src/gui/main_window.py:926-928, 946-958, 968-1007`.
- **What is wrong**: The branch is guarded by `hasattr(message, "get_packet_content") and hasattr(message, "get_from_name")`, which every `HoppieMessage` satisfies (telex, progress, ADS-C). Only `get_mrn` is probed optionally.
- **Failure scenario**: While logged on to EDGG, a telex from `EDGG` (or from any station if no logon is pending) containing exactly `LOGOFF`/`LOGON ACCEPTED` changes `current_station`; a telex `HANDOVER EDUU` from the current station triggers an automatic REQUEST LOGON to EDUU.
- **Evidence**: `926: if hasattr(message, "get_packet_content") and hasattr(message, "get_from_name"):` … `958: mrn = message.get_mrn() if hasattr(message, "get_mrn") else None`.
- **Suggested fix direction**: `if isinstance(message, CpdlcMessage):` around the session-state block, and use `message.get_message()` / `get_mrn()` / `get_rr()` directly (see Info item on `extract_message_content`).

### 8. One failed send makes the status bar claim "Connection problem (1/3) - retrying…" on every successful poll until the next successful send

- **Severity**: Low — misleading link status for an indefinite period; nothing is actually retrying.
- **Confidence**: Confirmed (reproduced: after one timed-out telex and two good polls, `failure_count()==1`, `poll_failed()==True`).
- **Location(s)**: `src/model/connection_manager.py:310-316`; `src/controller/polling_controller.py:205-217`.
- **What is wrong**: `poll_failed()` is `max(connection_failures, send_failures) > 0`; only a successful *send* clears `send_failures`, so a transient failure on a telex or WILCO is reported as an ongoing poll problem by `_report_connection_state` on every tick.
- **Failure scenario**: Pilot's WILCO POST times out once (dialog shown). Every poll afterwards rewrites the status bar to "Connection problem (1/3) - retrying…" although polls succeed; the "Logged on to EDGG." text is gone; a screen-reader user querying the status bar concludes the link is bad.
- **Evidence**: `312: return max(self.connection_failures, self.send_failures)`; `316: return self.failure_count() > 0`; `207-214`.
- **Suggested fix direction**: Report poll health from `connection_failures` only; report send failures at the moment they happen (they already raise a dialog) and let `should_attempt_reconnection` keep using the max.

### 9. An exception in the message callback aborts the rest of the poll batch (already consumed server-side)

- **Severity**: Low — mechanism confirmed, trigger requires a bug or wx failure inside `_on_message_received`, which is reasonably robust today.
- **Confidence**: Confirmed.
- **Location(s)**: `src/controller/polling_controller.py:159-176`.
- **What is wrong**: The `raise` inside the per-message loop leaves the loop; messages 2..n of the same poll are never added to the list, never announced, and cannot be re-fetched. `check_polling_timeout()` and the reconnection check are also skipped for that tick.
- **Failure scenario**: A poll returns three uplinks; the first trips e.g. a wx error in `SetStatusText` during window teardown or a future bug in the handover branch; the two others vanish.
- **Evidence**: `164-172: try: self.message_callback(message) except Exception: self.logger.exception(...); raise`.
- **Suggested fix direction**: Log with `logger.exception`, remember the first exception, continue the loop, then re-raise (or report via the global handler) after all messages have been processed.

### 10. Recoverable-looking loop when `attempt_reconnection()` raises anything other than `HoppieError` (the OSError-for-CA-bundle case the code deliberately does not classify)

- **Severity**: Low — mechanism Confirmed, but the trigger (CA bundle path becoming invalid *mid-session*, e.g. `REQUESTS_CA_BUNDLE`/`CURL_CA_BUNDLE` pointing at a removed file or an AV quarantining `certifi/cacert.pem`) is uncommon; at initial connect the same error surfaces once as an "Unexpected Error" dialog, which is acceptable.
- **Confidence**: Confirmed (reproduced with `requests.get` raising `OSError("Could not find a suitable TLS CA certificate bundle…")`).
- **Location(s)**: `src/model/connection_manager.py:19-24, 327-350`; `src/controller/polling_controller.py:182-198`; `app.py:38-51, 73-76`; `requests/adapters.py:302-306` (plain `OSError`), `requests/sessions.py:768-769` (env override).
- **What is wrong**: `poll()` catches everything, so each OSError poll adds one to `connection_failures`. `attempt_reconnection()` catches only `HoppieError`; the OSError from `ping` escapes, so `self.cnx` keeps the old connector, the counter is not reset, `should_attempt_reconnection()` stays True. The `finally` in `on_poll_timer` reschedules; the escaped exception reaches `OnExceptionInMainLoop` → modal "Unexpected Error" dialog. Because wx timers keep firing inside a modal loop, the next tick repeats: another failed poll, another escaped OSError, another stacked dialog, every 20-75 s.
- **Failure scenario**: Reproduced state after one attempt: `cnx is old object: True, connection_failures 3, should_attempt_reconnection True`; next `poll()` → failures 4, still True.
- **Evidence**:
  ```python
  339:            self.cnx = self._open(self.callsign, self.logon_code, self.network_type)
  347:        except HoppieError as exc:   # OSError/others escape with cnx and counters intact
  ```
- **Suggested fix direction**: In `attempt_reconnection` (and `connect`) catch `Exception`, log it, set `cnx = None`, return False — keeping the *classification* decision (not counting OSError as a transport failure) but not letting it break the state machine. Also `wx.CallAfter`-coalesce the global error dialog so repeated failures do not stack modals.

  Related packaging note: TLS *verification* failures (corporate MITM, wrong clock) raise `requests.exceptions.SSLError`, which is a `RequestException` and is handled/redacted correctly; reconnection cannot fix them, so the user ends at "Connection lost" with the real reason only in the log. PyInstaller normally bundles `certifi/cacert.pem` (the venv here has no PyInstaller installed, so its hook could not be inspected directly), so the OSError path is not expected in a healthy install.

### 11. Latent credential leaks: unredacted URL survives in the exception chain; DEBUG logging writes both logon codes to the log file

- **Severity**: Low — no currently reachable path was found that prints either, but both are one line away from doing so.
- **Confidence**: Confirmed (reproduced: `str(HoppieError)` contains no secret, `traceback.format_exception(HoppieError)` does, via `__cause__`).
- **Location(s)**: `src/model/connection_manager.py:137, 141-143, 181` (`raise … from exc`); `app.py:39-42` (`traceback.format_exception` of anything unhandled); `src/controller/polling_controller.py:171` (`logger.exception`); `src/config.py:52, 85` (`logger.debug(f"Loaded config: {config}")` / `Saved config`); `src/logging_setup.py:13` (level INFO today).
- **What is wrong**: `redact()` scrubs the *message* but the original `requests` exception — whose text embeds `…connect.html?logon=<code>&from=…` — is kept as `__cause__`. Python's traceback formatting (used by the unhandled-exception handler and `logger.exception`) prints chained causes in full. Today every `HoppieError` is caught before it can reach either, so this is dormant. Separately, the whole config dict, including `sayintentions_logon_code` and `hoppie_logon_code`, is formatted into DEBUG lines; the logger is fixed at INFO, so they are not emitted — but that is exactly the level a user would be asked to raise for troubleshooting, and the resulting log would be shared.
- **Failure scenario**: A future `logger.exception(...)` around a send, or a HoppieError escaping a new handler, writes `logon=<code>` into `sim-cpdlc.log`; or a debug build is shipped and the user emails the log.
- **Evidence**: reproduction: `traceback.format_exception(HoppieError) contains SECRET? True`; `config.py:52: logger.debug(f"Loaded config: {config}")`.
- **Suggested fix direction**: Raise the redacted `HoppieError` with `from None` (or attach a redacted copy of the cause); redact the config dict before logging (or log only non-secret keys); optionally run `redact()` inside the global exception handler's log line.

### 12. Logon lifecycle has no negative paths: exact-match acceptance, no rejection handling, no pending timeout, no station-online check

- **Severity**: Low — each is a robustness gap rather than a demonstrated fault; together they are the main ways the pilot and the station end up disagreeing about the logon.
- **Confidence**: Plausible.
- **Location(s)**: `src/gui/main_window.py:956, 968-1007`; `src/model/cpdlc_session.py:396-451`.
- **What is wrong**:
  - Acceptance requires `msg_text == "LOGON ACCEPTED"` exactly (after `@`→space normalisation). A station appending anything (e.g. `LOGON ACCEPTED. WELCOME`) leaves the app at "Pending logon" while the station considers the aircraft connected; every subsequent uplink from it is then unanswerable (sender ≠ current station) and a later `HANDOVER` from it is ignored by the `elif sender == current_station` guard.
  - There is no handling of a rejection (`LOGON REJECTED`, `UNABLE` with MRN 1, or an `error {}`), so `pending_logon_station` persists and the status bar says "Pending logon to X." indefinitely.
  - A pending logon never times out; a LOGON ACCEPTED from another station while one is pending is rejected by design (`cpdlc_session.py:418-423`), which is right for stale acceptances but also blocks a forwarded/redirected logon.
  - The station's presence is never checked: if the controller disconnects without sending LOGOFF (common on VATSIM), the app shows "Logged on to X" for the rest of the flight and keeps sending requests into a queue nobody reads. `HoppieConnector.ping(stations)` exists and could be used occasionally (not per poll) to detect this.
- **Suggested fix direction**: Match `startswith("LOGON ACCEPTED")`; treat `LOGON REJECTED`/an `UNABLE` carrying MRN==pending MIN as clearing the pending state with a status message; expire a pending logon after a few minutes; ping the current station every few minutes (well within Hoppie's rules) and flag it when it goes offline.

### 13. SimBrief fetch: blocks the GUI thread before the dialog appears, and its diagnostics never reach the log file in the packaged build

- **Severity**: Low.
- **Confidence**: Confirmed.
- **Location(s)**: `src/utils/simbrief.py:8, 26-60`; `src/gui/dialogs/connect_dialog.py:57-90`; `src/gui/dialogs/pdc_dialog.py:48-106`; `src/logging_setup.py:12-27`.
- **What is wrong**: `get_latest_ofp()` runs synchronously inside the dialog constructors with `timeout=10` (connect + read, so up to ~20 s) — the Connect/PDC dialog simply does not appear while SimBrief is slow, with no feedback. Every failure (timeout, DNS, HTTP 400 for an unknown user id — SimBrief returns a JSON body explaining it — non-JSON body) is collapsed into `None`, and the detail is logged to `logging.getLogger("src.utils.simbrief")`, which has no handler: it propagates to the root logger, which only has Python's last-resort stderr handler, and stderr is `None` in the frozen build. The dialogs then log only "Failed to fetch SimBrief OFP data". The `except Exception` branches in the dialogs are effectively unreachable because `fetch_ofp` swallows everything.
- **Failure scenario**: User enters a wrong SimBrief ID; SimBrief answers 400 with `{"fetch":{"status":"Error: Unknown UserID"}}`; the user sees "Could not fetch flight plan from SimBrief." and the log file contains nothing that says why.
- **Suggested fix direction**: Use the `"Sim-CPDLC"` logger (or `getLogger("Sim-CPDLC").getChild(...)`) in `simbrief.py`; return an error string alongside `None`; fetch on a worker thread after the dialog is shown, or at least show a busy cursor.

### 14. Manual weather requests run on the GUI thread

- **Severity**: Low — the automatic path is threaded correctly; only the menu path freezes the UI for up to ~30 s on a stalled server.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:734` → `src/model/cpdlc_session.py:494-508` → `src/model/connection_manager.py:451-477` (docstring itself says "callers that run on a timer should invoke this from a worker thread").
- **Suggested fix direction**: Route the manual request through the same worker/`wx.CallAfter` pattern as `WeatherMonitor`.

### Info-level observations (no user-visible defect found, noted for the coordinator)

- `extract_message_content()` (`src/utils/message_formatting.py:6-17`) re-parses a packet the library already parsed; `CpdlcMessage.get_message()`, `get_mrn()`, `get_rr()` are authoritative and cannot drift from the library's grammar. The regex does strip every prefix shape the library emits (`/data2/N//RR/` and `/data2/N/M/RR/`), verified, so it is redundant rather than wrong. It is also applied to telex text, which is harmless only because telex is upper-cased and the pattern is lowercase `data`.
- Every non-acknowledgement CPDLC uplink — including `LOGON ACCEPTED`, `LOGOFF`, `HANDOVER` and other `NE` messages that expect no reply — starts five minutes of 20 s polling (`should_increase_polling_rate`, `INACTIVITY_TIMEOUT`). Hoppie's 20 s allowance is for "while a reply is expected"; this is more generous than necessary but never faster than 20 s.
- No `requests.Session` is used, so every poll/send is a fresh TCP+TLS handshake. Fine at these rates; it does mean each request can independently hit the 15 s connect timeout.
- `install_request_timeout()`'s `timeout=15` is a per-phase value (connect and each socket read), not a total request budget; worst case for one hoppie call is ~30 s of GUI-thread stall. Only `requests.get`/`post` are wrapped, which is exactly what the library uses; the app's own calls pass explicit timeouts (15/10/5 s). No call without a timeout was found.
- `on_disconnect` calls `set_active_polling()` and `wx.MilliSleep(500)` "to allow the message to be sent" after a fully synchronous send — both are no-ops in effect.
- FANS-1/A MINs are modulo 64; `cpdlc_min_counter` grows without bound. Whether Hoppie ATC clients care is unverified — mentioned only because a long session with automatic handovers can pass 63.
- `PollResponseParser` (`Responses.py:231`) uses `[^\}]*` for the packet, so a telex containing `}` is skipped with no warning at all (reproduced) — a library limitation, extremely rare in practice.
- Logon codes are stored in plaintext in `config.json` and shown unmasked in Settings; consistent with the app's screen-reader-first design and with how every Hoppie client behaves.

---

## Things I checked that are fine

- **Timeout patch reaches the library**: `hoppie_connector/API.py` uses module-attribute `requests.get`/`requests.post`; after `install_request_timeout()` both the library's GET (ping/poll/cpdlc) and POST (telex) arrived with `timeout=15` (reproduced). Idempotent via `_default_timeout_applied`; explicit timeouts still win.
- **Every outbound call has a timeout**: hoppie calls (15 s via patch), inforeq (15 s explicit), SimBrief (10 s), GitHub (5 s).
- **Error classification at the boundary**: builtin `ConnectionError` (library, non-2xx), `requests.RequestException` (incl. `SSLError`, `Timeout`, `HTTPError`, `JSONDecodeError`) → transport and counted; `ValueError`/`TypeError`/`UnicodeDecodeError` → protocol, not counted for sends, counted for polls (where there is no user input to blame); library `HoppieError` for `error {reason}` passes through; `poll()`'s broad `except` ensures nothing skips the counter. `OSError` is deliberately excluded (see finding 10 for the one consequence).
- **Failure counters**: polls, sends and inforeq are counted separately; a successful poll does not clear send failures (proxy-blocks-POST case); weather failures never influence reconnection; all counters reset on connect/reconnect/disconnect. `should_attempt_reconnection()` requires a live `cnx` and credentials.
- **Successful reconnection preserves the ATC logon**: `attempt_reconnection` rebuilds the connector under the same callsign and never touches `CpdlcSession`; from the station's side nothing changed.
- **Credential redaction**: `redact()` covers the `?logon=` URL form that `requests` embeds in `ConnectionError`, `HTTPError` and friends (also `HoppieAPI.__repr__`'s `logon='…'` form); applied on every `HoppieError` built in `_call`/`_transport_failure`, and `poll()` redacts anything else it logs. No f-string in `src/` formats `logon_code`, the connector, or the API object. Both API URLs are HTTPS. `HoppieConnector` has no `__repr__` exposing the code.
- **Callsign/recipient validation**: the library's `^[A-Z0-9]{3,8}$` is enforced on FROM at connect time by the `ping()` round trip and on TO at send time; both surface as `HoppieError` dialogs (whitespace is not stripped in the connect/telex dialogs, so the message is "Invalid FROM/TO station name" rather than a hint, but it is not silent). All CPDLC texts the app can generate (`REQUEST LOGON`, `LOGOFF`, `REQUEST FL350 DUE TO AIRCRAFT PERFORMANCE`, `REQUEST DIRECT TO KONOL`, `REQUEST M082`, `REQUEST 300K`, `WHEN CAN WE EXPECT …`, every response string) pass the library's `[A-Z0-9._@ ]+` check (verified). PDC telex is well under 220 chars.
- **RR / MIN / MRN on downlinks**: `REQUEST LOGON` and all requests go out with `Y`; `LOGOFF` with `NE`; acknowledgements with `N` and `mrn=<uplink MIN>` (matches the real traffic quoted in TODOS.md); MIN increments after every successful send and not after a failed one.
- **LOGON ACCEPTED validation**: station must match the pending station when one is pending; MRN must match the pending MIN when both are present; unsolicited acceptances (automatic transfer) still work; a 4-character station is required.
- **HANDOVER / LOGOFF detection**: performed on `@`-normalised, whitespace-collapsed text; `^HANDOVER\s+([A-Z]{4})$` accepts `HANDOVER @EDUU@` and `HANDOVER EDUU`; only honoured from the current station; the app then sends `REQUEST LOGON` to the new station and enters active polling. `CURRENT ATC UNIT`/`CURRENT ATS UNIT` noise is hidden before it reaches the list.
- **Messages from stations other than the current one** are displayed with sound but offer no responses (`needs_acknowledgement` compares sender to the live session station), so acknowledgements can never be misaddressed.
- **Polling rate**: idle interval re-randomised in 45-75 s per tick, active 20 s, one-shot timer rescheduled in `finally`, `set_active_polling()` only pulls a pending poll forward when it is more than 20 s away and never restarts an imminent one; no code path polls faster than 20 s or issues bursts (the reconnection ping is one extra request per 3 failures; weather cycles are spaced 1 s and serialised by `_cycle_running`).
- **`_send_info_request` request shape**: `from`/`to=SERVER`/`type=inforeq`/`packet=<kind> <ICAO>` matches Hoppie's documented inforeq; `ok {server info {…}}` unwrapping handles nested braces and multi-line bodies; `error {}` and HTML/captive-portal bodies raise; HTTP errors go through `raise_for_status` into the info counter.
- **Weather monitor threading**: subscriptions mutated only on the GUI thread, snapshot handed to a daemon worker, results returned via `wx.CallAfter` guarded by `IsBeingDeleted()`, all exceptions (including OSError) caught on the worker, per-subscription failure cap of 5 with a SYSTEM message; timer stopped and subscriptions cleared on manual disconnect; interval clamped when read from config.
- **Update checker**: background thread for the automatic check, explicit 5 s timeout, all exceptions (network absent, HTTP 403 rate limit, non-JSON, bad tag) caught and reduced to "could not retrieve"/silent; dialog scheduled via `CallAfter` only if the window is alive; manual check is synchronous but bounded.
- **Global exception plumbing**: `sys.excepthook`, `threading.excepthook` and `OnExceptionInMainLoop` all log with traceback and show a dialog, so nothing dies silently in the `console=False` build (finding 1 is the one exception, because it is a *warning*, not an exception).
