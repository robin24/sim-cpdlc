# Audit fixes — umbrella design

**Date:** 2026-09-03
**Branch:** `claude/audit-fix-design`, cut from `main` at `9c06458`.
**Status:** approved in discussion, awaiting review of this document.

## Purpose

`docs/audit/2026-09-03-codebase-audit.md` lists 3 High, 12 Medium, 21 Low and 5
Info findings against `main`. This document settles the decisions those findings
depend on, groups the work into six packages, and fixes the interfaces each
package introduces, so that each package can then get its own implementation
plan and land as its own pull request.

## Inputs

Two sources beyond the code:

- The audit report and its four lens reports under `docs/audit/`.
- The application log on the maintainer's machine, 2026-03-04 to 2026-09-03:
  242 starts, 239 SayIntentions and 21 Hoppie connections, 2,693 received
  messages (2,437 CPDLC, 256 telex), 163 handovers.

What the log established:

| Question from the audit | Answer from the log |
|---|---|
| Do uplinks contain characters the library refuses? | Not observably. Every received CPDLC uplink is template-shaped and inside the whitelist; 3 of 256 telexes carry punctuation, which telex parsing accepts anyway. `@@` never appears; `@_@` appears only in `CURRENT ATC UNIT`. |
| How do handovers behave? | In 22 of 163 handovers a WILCO-required instruction from the previous station (typically `CONTACT … ON @freq@.`) arrived after the handover, in the same poll batch as the new station's `LOGON ACCEPTED`. The pilot acknowledged 16 of them under older builds; current `main` makes them unanswerable. |
| How do outages look? | Server-side poll errors: `callsign already in use` (5), `invalid logon code` (4). One 145-poll Hoppie outage; one 8-poll SayIntentions outage on 2026-07-17 that recovered by itself after six minutes, which current `main` would have turned into a permanent stop. |
| Is send rate a problem? | 19 of 975 send gaps were under 5 s; SayIntentions rejected one ROGER with `rate_limit`. |
| Non-ASCII bodies? | Never. |
| Do `LOGON ACCEPTED` uplinks carry an MRN? | All 388 do. |

## Decisions

1. Test harness first, then five behaviour packages in the order below. Each package is one plan and one pull request.
2. **Handover window.** Unanswered uplinks stay answerable when they come from the current station or from the station the aircraft was handed over from, for 10 minutes after the handover. Responses are always addressed to the message's own sender.
3. **Link loss is never terminal.** After three consecutive poll failures the link is "lost": the user is told with a SYSTEM row and the notification sound, polling continues on a back-off ladder of 20 s, 60 s, 120 s, 300 s (cap), and a successful poll or re-verification restores it, again announced. Only `invalid logon code` stops polling.
4. **Session reset.** CPDLC session state is reset on File > Disconnect (whether or not the LOGOFF could be sent), on a connect with a different callsign or network, and on a fatal link error. Automatic reconnection with the same identity keeps the ATC logon.
5. **One network worker** owns every network call: connect, poll, sends, weather, SimBrief, update check. Sends are paced at least 5 s apart.
6. **Update checker** opens the release page and never closes the application; the automatic check is skipped when the app runs from source.
7. **Logon while logged on** sends LOGOFF to the current station first, then REQUEST LOGON, restarting the MIN counter only after that LOGOFF.
8. Smaller calls settled by evidence: the `@@` → `N/A` substitution is removed; README states Python 3.12; the library-warning mitigation for unparseable uplinks is logging plus a SYSTEM row, not a permissive parser; the non-ASCII decode shim is optional and last.

## Packages

| # | Package | Findings closed |
|---|---|---|
| 1 | Test harness hermeticity and protocol regression tests | M-11, M-12, L-21 (part) |
| 2 | Link resilience and message integrity | H-1, H-2, M-2 (optional), M-3, M-4, M-6, L-1 |
| 3 | Session and protocol state | handover race, M-1, M-7, L-2, L-3 |
| 4 | One network worker | H-3, M-5, M-9, L-4, L-5, L-9, L-13, L-14, L-15 |
| 5 | Dialog validation and feedback | M-8, L-7, L-10, L-11, L-12, L-16, L-17 |
| 6 | Release, packaging, docs, hygiene | M-10, L-6, L-8, L-18, L-19, L-20, I-1 to I-5 |

New constants, all in `src/config.py`, so every timing in this design is tunable in one place:

```python
LINK_BACKOFF_MS = (20000, 60000, 120000, 300000)   # package 2
PREVIOUS_STATION_WINDOW_SECONDS = 600              # package 3
PENDING_LOGON_TIMEOUT_SECONDS = 600                # package 3
SEND_SPACING_SECONDS = 5                            # package 4
INFOREQ_SPACING_SECONDS = 1                         # package 4
NETWORK_TIMEOUT = (10, 15)                          # package 4: connect, read
```

---

## Package 1: test harness hermeticity and protocol regression tests

**Goal.** No test can touch the maintainer's real configuration, the network,
SimBrief or the simulator, and the protocol behaviour that later packages must
preserve is pinned.

### Fixtures (`tests/conftest.py`)

Three new autouse fixtures:

- `isolated_config`: `monkeypatch.setattr(src.config, "CONFIG_FILE", str(tmp_path / "config.json"))`. `load_config`, `save_config` and `_check_first_launch` all read the module attribute at call time, so one patch covers them.
- `no_network`: replaces `requests.get`, `requests.post` and `webbrowser.open` with functions that raise `RuntimeError("network access in a test")`. A test that needs HTTP installs `serving()` over it, as `test_connection_manager.py` already does.
- `no_simbrief`: patches `src.gui.dialogs.connect_dialog.get_latest_ofp` and `src.gui.dialogs.pdc_dialog.get_latest_ofp` to return `None`.

`wx_app` asserts `wx.GetTopLevelWindows()` is empty after its `SafeYield`, so a
leaked window fails the test that leaked it.

### Helpers (`tests/support.py`, new)

Everything currently imported with `from conftest import …` moves here:
`uplink(sender, min_value, text, rr, mrn=None)`, `FakeConnectionManager`
(gains `raise_with=None`; when set, every send raises it), `RecordingMessageView`,
`FakePollingController`, and `make_main_window(logger, session, manager,
config=None, simconnect=None)`, which now sets `window.simconnect_manager` to a
`FakeSimConnectManager` (records every frequency passed to
`set_com1_standby_mhz`, returns a configurable result) and patches
`src.gui.main_window.load_config` to return the supplied dict. A `message_boxes`
fixture replaces the silent `wx.MessageBox` stub: it records `(text, caption,
style)` and returns `.answer`, default `wx.YES`.

### Tooling

`pytest-timeout` added to `requirements-dev.txt` with `timeout = 60` in
`pytest.ini`; `timeout-minutes: 15` on the CI test job; the two
`install_request_timeout` tests patch `requests.post` as well as `requests.get`.

### Regression tests added (current behaviour)

- Acknowledgement frame: `connection.sent[-1] == (STATION, 1, RR.NO.value, "WILCO", 53)`; a second acknowledgement uses own MIN 2; through the real `HoppieConnector` with a capturing `requests.get`, `params["packet"] == "/data2/1/53/N/WILCO"`.
- `handle_logon_accepted("EDDF", mrn=2)` with pending MIN 1 is rejected; through the window, a properly built `/data2/1/2/NE/LOGON ACCEPTED` leaves the status bar silent.
- Response table parametrised over all six `CpdlcResponseRequirement` members.
- Every downlink literally: `logon`, `logoff`, `send_speed_request` (Mach and knots), `send_when_can_we_expect`, `send_telex`, `send_pdc_request`, each also with `raise_with=HoppieError("boom")` giving `(False, "boom")`.
- `_on_message_received` branches through `make_main_window`: `HANDOVER EDGG` (station cleared, `("EDGG", 1, "Y", "REQUEST LOGON", None)` sent, both status texts, active polling bumped; nothing from a non-current station), `LOGOFF` and `LOGOFF NOT REQUIRED AT THIS TIME`, `CURRENT ATC UNIT`/`CURRENT ATS UNIT` filtered, `CONTACT MARSEILLE CONTROL 133.325` tuned / disabled / failed-status / non-current station.
- Menu binding: for every item of every menu, the expected handler is replaced by a recorder and `window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, item.GetId()))` must fire exactly it; replaces the existence-only check.
- Context menu: labels `["Respond: WILCO", "Respond: UNABLE", "Respond: STANDBY"]`, firing the second item calls `on_acknowledge(message_id, "UNABLE")`, re-posting the same id after the menu closed fires nothing.
- `load_config` / `save_config` on `tmp_path`: missing-key back-fill, invalid JSON, non-dict, and an `os.replace` failure leaving the original intact with no `.tmp` behind.
- Tables for `frequency_parser` (the ten audit cases plus boundaries `136.990`/`137.000`) and `message_formatting` (prefix stripping for every RR, `@` handling).
- `tests/README.md` regenerated from the real file list.

Tests that pin behaviour a later package changes (strict station scoping, the
`N/A` substitution, the single reconnection attempt) are left as they are here
and rewritten by that package.

---

## Package 2: link resilience and message integrity

**Goal.** A poll failure is reported honestly, never silently ends the session,
and never loses a message the server has already handed over.

### `LinkState` (`src/controller/link_state.py`, new)

```python
class LinkState:
    CONNECTED = "connected"   # last poll succeeded
    DEGRADED = "degraded"     # 1-2 consecutive failures
    LOST = "lost"             # 3 or more; back-off active
    FATAL = "fatal"           # server said the logon code is invalid

    def __init__(self, on_change, max_failures=MAX_CONNECTION_FAILURES,
                 backoff_ms=LINK_BACKOFF_MS): ...
    def record_poll(self, result: "PollResult") -> None
    def record_reverify(self, ok: bool) -> None
    def next_delay_ms(self) -> int | None   # back-off delay while LOST, else None
    def reset(self) -> None
    state: str
    failures: int
```

`on_change(old, new, reason)` fires on every transition. Entering LOST starts
the ladder at its first rung; each further failure advances one rung and stays
at the cap; any success returns to CONNECTED and resets the ladder. A
`PollResult` whose `fatal` flag is set moves to FATAL from any state.

### `ConnectionManager.poll()` returns a `PollResult`

```python
@dataclass
class UnreadableMessage:
    sender: str
    raw: str          # the packet as the server sent it

@dataclass
class PollResult:
    ok: bool
    messages: list            # HoppieMessage objects
    unreadable: list          # UnreadableMessage objects
    reason: str | None        # server reason or error text on failure
    fatal: bool = False       # True for "invalid logon code"
```

`poll()` wraps `cnx.poll` in `warnings.catch_warnings(record=True)` filtered to
`HoppieWarning`; each recorded warning becomes an `UnreadableMessage` (sender
and raw packet parsed from the warning text, which carries the item dict) and an
ERROR log line. A `HoppieError` whose reason contains `invalid logon code`
produces `fatal=True`. `callsign already in use` is an ordinary failure but the
reason is carried so the window can announce it once per episode. Existing
fakes that return `(messages, None)` are updated to return a `PollResult`.

### `PollingController`

- Owns `self.link = LinkState(on_change=self._on_link_change)`; `start()` calls `link.reset()` and clears `_reported_failure`.
- `_schedule_next()` uses `link.next_delay_ms()` when it is not `None`, otherwise the existing active/idle logic.
- The tick: submit the poll (synchronously in this package; the worker arrives in package 4), `link.record_poll(result)`, process messages, then, while LOST and only when the back-off delay has elapsed, call `connection_manager.attempt_reconnection()` and `link.record_reverify(ok)`. The branch no longer calls `stop()`. FATAL stops the timer.
- Message loop (M-3): each callback runs in its own `try`; a failure is logged with traceback and the loop continues; the first exception is re-raised after the loop so the reporter still sees it.
- `unreadable_callback(unreadable)` is a new constructor argument alongside `message_callback`.
- Status texts, all through `_set_status`: DEGRADED "Connection problem (n/3) - retrying...", LOST "Connection lost - retrying in N s", back to CONNECTED "Connection restored.". `_report_connection_state` reads `connection_failures` only (L-1); send failures keep their dialog.
- `link_callback(old, new, reason)` constructor argument so the window can react.

### `ConnectionManager`

- `attempt_reconnection()` catches `Exception`, logs it, and on failure keeps the existing connector (so `is_connected()` stays true and File > Disconnect still works). On FATAL the controller only stops its timer; the window's `link_callback` is what calls `disconnect()` and resets the session, so there is one owner for the teardown.
- `connect()` likewise converts any non-`HoppieError` into a `HoppieError` for the caller (the classification into transport/protocol is unchanged for counting purposes).
- `_SERVER_INFO_PATTERN` becomes `^\{server info \{(.*)\}\}$`; `send_info_request` raises "No <report> available for <ICAO>" for a bare `ok`, `ok ` and an empty envelope; `error {reason}` is surfaced without braces.
- Optional last step (M-2): `LenientHoppieAPI(HoppieAPI)` overriding `connect` to decode with `errors="replace"`, installed as `cnx._api` in `_open`; a test asserts the attribute exists on `HoppieConnector` so a library upgrade cannot silently disable it.

### `MainWindow`

- `link_callback`: on LOST add SYSTEM row "Connection lost, retrying" and play the sound; on restore "Connection restored" with sound; on `callsign already in use` a SYSTEM row once per episode; on FATAL a dialog "The server rejected the logon code", `polling_controller.stop()`, `weather_monitor.stop()`, `connection_manager.disconnect()`, `cpdlc_session.reset()` (package 3 adds the method; until then the existing fields are cleared inline), menu label back to Connect.
- `unreadable_callback`: SYSTEM row "Unreadable message from <sender>: <raw>" with the notification sound.
- Acknowledgement `rate_limit`: `send_acknowledgement` returns `(False, "rate_limit")`; the window schedules one retry with `wx.CallLater(5000, …)`; a second failure shows the existing dialog. Package 4 replaces this with queue pacing.

### `app.py` reporter

`report()` shows its dialog through `wx.CallAfter` on every thread and keeps a
`_dialog_open` flag; while it is set, further reports are logged only.

### Tests

`FailingConnection` fake with settable `poll()` results; assertions on the
ladder (20, 60, 120, 300, 300 s), on every status text, on `is_running()` after
a failed re-verification (still true), on FATAL (timer stopped, `disconnect()`
called), on `UnreadableMessage` reaching the window, on a callback exception
not losing the rest of the batch, on the `rate_limit` retry, and on the three
envelope cases.

---

## Package 3: session and protocol state

**Goal.** The app's idea of who it is talking to matches the network's, across
handovers, disconnects and reconnects.

### `CpdlcSession` interface additions

```python
def reset(self) -> None
    # current_station, pending_logon_*, previous_station(_until) cleared; MIN = 1
def handle_handover(self, old: str, new: str) -> tuple[bool, str | None]
    # records previous_station = old, previous_station_until = now + window,
    # clears current_station, then logon(new); returns logon()'s result
def is_answerable_sender(self, sender: str) -> bool
    # current station, or previous station while the window is open
def handle_logon_rejected(self, station: str, mrn: int | None) -> bool
    # LOGON REJECTED from the pending station, or UNABLE whose MRN is the pending MIN
def expire_pending(self, now: float | None = None) -> str | None
    # returns the station whose pending logon just expired, else None
```

`logon(station)`: if `current_station` is set, call `logoff()` first (its
failure is returned to the caller as a warning string but does not abort), then
restart MIN at 1 and send REQUEST LOGON. `logoff()` and `handle_handover()`
clear the pending state. `set_callsign()` is replaced by `begin_session(callsign,
network)`, which calls `reset()` when either differs from the previous session.
Time comes from `time.monotonic()` with an injectable clock for tests.

### `MessageManager` and `MessageView`

`needs_acknowledgement(message_id, is_answerable)` takes the predicate;
`MessageView` receives `is_answerable_sender` instead of `get_current_station`.

### `MainWindow._on_message_received`

- The session block runs only for `isinstance(message, CpdlcMessage)` and reads `message.get_message()` and `message.get_mrn()` directly. Telex, progress and ADS-C messages are displayed and nothing else.
- `LOGON ACCEPTED` matches on prefix; `LOGON REJECTED` and `UNABLE` with the pending MRN go to `handle_logon_rejected` (status "Logon to X rejected.", SYSTEM row).
- `HANDOVER` calls `handle_handover`; `LOGOFF` from the current station as today.
- The auto-tune branch runs when `is_answerable_sender(sender)` is true, so the `CONTACT` that follows a handover is tuned.
- `PollingController(tick_callback=…)` runs at the end of every tick; the window uses it for `expire_pending()` and announces "Logon to X not answered." with a SYSTEM row.

### `MainWindow` connect and disconnect

`on_connect` calls `cpdlc_session.begin_session(callsign, network_type)`.
`on_disconnect` attempts the LOGOFF, adds "Could not send LOGOFF to X: <reason>"
if it failed, then always calls `reset()`. `on_close` does the same before
shutting down.

### Tests

Replace the strict-scoping tests with the window rule. Add the log's handover
sequence verbatim: `HANDOVER @CZYZ@`, then in one batch `CONTACT TORONTO CENTER
ON @135.625@.` from KUSA and `LOGON ACCEPTED` from CZYZ — the CONTACT is
answerable, is tuned, and is no longer answerable once the clock passes the
window. Reset on disconnect with a failed LOGOFF; no reset on automatic
reconnection; reset on a different callsign; logon while logged on sends
`LOGOFF` then `REQUEST LOGON` with MIN 1; rejection and expiry; a telex reading
`LOGON ACCEPTED` changes nothing.

---

## Package 4: one network worker

**Goal.** The GUI thread never waits on the network, sends are paced and
serialised, and background results can never touch a dead window.

### `NetworkWorker` (`src/model/network_worker.py`, new)

```python
@dataclass(order=True)
class Job:
    priority: int             # 0 send, 1 connect/poll, 2 inforeq/simbrief/update/simconnect
    sequence: int             # FIFO within a priority
    kind: str = field(compare=False)
    fn: Callable = field(compare=False)
    on_done: Callable = field(compare=False)
    generation: int = field(compare=False)

@dataclass
class JobResult:
    ok: bool
    value: object = None
    error: str | None = None      # HoppieError text or "<ExceptionName>: <text>"
    job: Job | None = None

class NetworkWorker:
    def __init__(self, logger, dispatch=wx.CallAfter, start_thread=True,
                 spacing=None): ...
    def submit(self, kind, fn, on_done, priority) -> Job
    def new_generation(self) -> int
    def run_pending(self) -> None          # test mode: run queued jobs inline
    def shutdown(self, timeout=2.0) -> None
```

One daemon thread pops jobs from a `queue.PriorityQueue`. A job whose
generation is older than the current one is skipped. Before a `send` job the
worker sleeps until `SEND_SPACING_SECONDS` have passed since the previous send;
`inforeq` jobs use `INFOREQ_SPACING_SECONDS`. `fn()` runs on the worker; any
exception is caught and becomes `JobResult(ok=False, error=…)`, with
non-`HoppieError` exceptions logged with traceback. Results go back through
`dispatch(on_done, result)` guarded by an alive flag; `dispatch` errors
(`AssertionError` from a gone `wx.App`, `RuntimeError` from a dead proxy) are
logged and dropped. Nothing in the worker touches a wx object.

### Callers

- `PollingController` submits `("poll", connection_manager.poll, self._on_poll_result, 1)` per tick and skips a tick while one is in flight; `_on_poll_result` is the existing processing code. The timer stays on the GUI thread.
- `CpdlcSession.send_*` methods, and likewise `logon`, `logoff` and `handle_handover` from package 3, return `bool` (enqueued or refused by a precondition), build and validate the frame synchronously, consume the MIN at enqueue time (a failed send leaves a gap, which is harmless), and call `on_done(success, text_or_error)` on the GUI thread. Window handlers keep their current success/failure code inside the callback. `send_acknowledgement` loses the `CallLater` retry from package 2: pacing makes `rate_limit` unreachable, and a residual one is reported like any other failure.
- `on_connect` submits a connect job, closes the dialog at once, shows "Connecting as X…", disables the Connect menu item until the result; on success it runs today's post-connect code, on failure the existing dialog.
- `WeatherMonitor` drops its thread: a cycle bumps a cycle id and submits one inforeq job per subscription; the cycle is complete when its last job reports; a new cycle's id makes older results ignored. The manual weather request uses the same path, closing the dialog immediately and adding the report or the error when it arrives.
- `ConnectDialog` and `PDCDialog` take a `fetch_simbrief(on_done)` callable, open immediately with a "Fetching SimBrief flight plan…" label, and fill their fields in `on_done` if `self._alive` (cleared by an overridden `Destroy`).
- `UpdateChecker` submits its request as a job; the result is handed to the window as `pending_update`, shown only when no dialog is open. The prompt is parented to the main window, says "Open the release page in your browser?", and never closes the app. Runs from source (`not getattr(sys, "frozen", False)`) skip the automatic check.
- `SimConnectManager.connect()` runs once per network connect as a job. `set_com1_standby_mhz` stays on the GUI thread, checks the return value of `send_event`, and on failure calls `exit()`, drops the object and submits a reconnect job whose callback re-sends the frequency once. `auto_tune_com1` is cached on the window and refreshed when Settings is saved.

### Modal dialogs

```python
@contextmanager
def _show_dialog(self, dlg):
    self._modal_depth += 1
    try:
        yield dlg.ShowModal()
    finally:
        self._modal_depth -= 1
        dlg.Destroy()
        self._flush_deferred()      # pending update prompt, if any
```

Every handler uses it; `wx.MessageBox` calls go through a `_message_box()`
helper that counts the same way. A test patches `wx.Dialog.ShowModal` to assert
the counter is positive whenever it is called.

### Lifecycle

- `install_request_timeout(NETWORK_TIMEOUT)` passes the `(10, 15)` tuple.
- `on_disconnect` loses `wx.MilliSleep(500)` and the `set_active_polling()` before `stop()`; `worker.new_generation()` drops queued work.
- `on_close`: `_confirm_exit` checks `event.CanVeto()` and skips the question on a forced close; LOGOFF is submitted at priority 0 and `worker.shutdown(timeout=5)` waits for the queue to drain; then weather monitor, SimConnect, `Skip()`.
- `app.py`: the `KeyboardInterrupt` branch and the `OnExceptionInMainLoop` override are removed (wx already routes handler exceptions to `sys.excepthook`, and SIGINT is reset by `wx.App`).

### Landing order

Three steps, each leaving the suite green: (1) worker plus poll path plus
weather; (2) sends and connect through the worker, `CpdlcSession` callback
signatures; (3) SimBrief, update checker, SimConnect connect, modal counting,
lifecycle clean-up.

### Tests

The worker is tested with `dispatch=lambda fn, *a: fn(*a)` and
`start_thread=False`: priority order, FIFO within priority, generation skipping,
send spacing (with an injected clock and sleep), exception capture, alive-flag
drop. Each caller's tests drive `run_pending()` and assert the GUI-side effects
that exist today. Package 1's thread-stub weather tests become worker tests.

---

## Package 5: dialog validation and feedback

- Every getter returns stripped text; `LogonDialog` validates `^[A-Z0-9]{4}$` after upper-casing and `on_logon` drops its duplicate check; `SettingsDialog.get_settings` strips the codes and the SimBrief id.
- Numeric validation on ASCII digits only (`text.isascii() and re.fullmatch(...)`): altitude `\d{2,3}` zero-padded to three (`FL050`); Mach `\d{2,3}` padded to three; knots `\d{3}`; When-can-we per type with the same rules. Direct-to `[A-Z0-9]{2,7}`, helper text "2-7 letters or digits, e.g. KONOL or 55N020W". The Mach/knots duplicate branch in `SpeedRequestDialog` collapses.
- `TelexDialog` shows "n / 220 characters" and disables OK over 220 or for non-ASCII text.
- `on_settings` applies the interval inside the `save_config` success branch; the confirmation reads "Settings saved. The weather interval applies now; logon codes apply to the next connection."
- `resource_path` uses `os.path.dirname(os.path.abspath(sys.argv[0]))` when not frozen.
- `message_formatting`: `@@` collapses like a single `@`; `format_list_text` collapses runs of spaces. `MessageView` sets the Sender column to `LIST_AUTOSIZE_USEHEADER` and resizes the Message column on `EVT_SIZE`.
- `WeatherSubscriptionsDialog` takes an `on_stop(icao, info_type)` callback (the window's toggle helper, which adds the SYSTEM row and status text) and a `subscribe_to_changes(callback)` hook on `WeatherMonitor` to refresh when a subscription is dropped or updated.
- `frequency_parser`: unit name optional (`(?:.+?\s+)?`), comment corrected; HANDOVER pattern `^HANDOVER\s+@?([A-Z]{4})@?` with trailing text allowed.
- Tests: per-dialog OK-button tables and getter literals (Telex built with a parent stub); the formatting and parser tables extended.

---

## Package 6: release, packaging, docs, hygiene

- **Version.** `RELEASING.md` documents: run `python update_version.py X.Y.Z`, commit, tag `vX.Y.Z`, push. The release workflow adds a step that fails when `APP_VERSION` in `src/config.py` differs from the tag, and a `test` job the build depends on. `about_dialog` shows "(source)" after the version and the copyright year comes from `datetime.date.today().year`.
- **Dependencies.** `requirements-build.txt` holds `pyinstaller`; `requirements.txt` pins `SimConnect==0.4.26`; `app.spec` raises `SystemExit("SimConnect.dll not found")` instead of silently omitting it; `.gitignore` gains `installer/` and `.pytest_cache/`; dependabot watches `github-actions`.
- **Docs.** README: "Python 3.12 or higher", altitude section without the climb/descent bullet, "requested reports arrive without the sound; automatic updates play it", reconnection paragraph describing package 2, tests table from `tests/README.md`; `app.py` docstring names both networks.
- **Hygiene.** Delete `src/utils/latest_simbrief_ofp.json`; move `src/utils/test_simbrief.py` to `tools/simbrief_probe.py` reading `SIMBRIEF_USERID` from the environment. Remove unused imports (`main_window.py`, `cpdlc_session.py`, `polling_controller.py`), `MessageManager.get_weather_key`, `ConnectionManager.message_callback`, `PollingController.default_poll_interval`, the `send_logoff_message` alias, `MainWindow.get_current_station` (`TelexDialog(parent, recipient)`), the local imports in `_check_first_launch`. Add `_require_logon(action)` next to `_require_connection` and use both in every handler; one `_send_request(text)` helper behind the four request senders. `simbrief.py` logs to `"Sim-CPDLC"`; `setup_logging` adds the console handler only when `sys.stderr` is not `None`; `load_config`/`save_config` log key names only; redacted `HoppieError`s are raised `from None`; `Optional[str]` hints; helper texts use `wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)`; the Connect `RadioBox` gets the label "Network".

---

## Cross-cutting

### Notification policy

| Event | Status bar | SYSTEM row | Sound |
|---|---|---|---|
| Uplink received | — | (message row) | yes |
| Automatic weather change | "New ATIS EGLL information K" | (report row) | yes |
| Link degraded (1–2 failures) | "Connection problem (n/3) - retrying..." | — | — |
| Link lost (3+) | "Connection lost - retrying in N s" | "Connection lost, retrying" | yes |
| Link restored | "Connection restored." | "Connection restored" | yes |
| Logon code rejected (fatal) | "Disconnected: logon code rejected." | yes, plus dialog | yes |
| Callsign already in use | (degraded text) | once per episode | — |
| Unreadable uplink | — | "Unreadable message from X: <raw>" | yes |
| Send in progress / done | "Sending WILCO…" / cleared | (echo row on success) | — |
| Send failed | — | — | dialog |
| Logon rejected / expired | "Logon to X rejected." / "not answered." | yes | — |
| LOGOFF could not be sent on disconnect | — | yes | — |

### Testing rules

TDD in every package; the suite is green after every commit; package 1's
fixtures make any network or real-config access a test failure. Each package's
plan lists its tests before its code.

### Manual acceptance before the next release

Handover followed by a `CONTACT` from the previous station is answerable and
tuned; unplugging the network for three minutes produces the lost and restored
announcements and messages resume afterwards; a wrong logon code produces the
fatal dialog and a Connect label; two acknowledgements sent within five seconds
on SayIntentions both arrive; File > Connect with a SimBrief id opens the dialog
at once; the update prompt never closes the app.

## Sequencing and delivery

Packages land in order 1 to 6, one branch and pull request each, and each plan
is written after the previous package has merged so it builds on merged code.
Package 4 is the largest and lands in the three steps listed above.

## Risks

- Package 4 changes the `CpdlcSession` send signatures and every handler; the three-step landing keeps each diff reviewable.
- The 10-minute windows and the back-off ladder are guesses informed by the log; all are constants in `config.py`.
- The optional decode shim uses the library's private `_api` attribute; its guard test fails loudly on a library change.
- Modal counting depends on every dialog going through `_show_dialog`; the `ShowModal` assertion test catches a bypass.

## Out of scope

Station-presence pings, a permissive CPDLC parser, MIN wrap at 64, message-log
eviction (accepted WON'T FIX), other networks, accelerator remapping.
