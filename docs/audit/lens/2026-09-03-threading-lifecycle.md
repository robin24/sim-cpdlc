# Sim-CPDLC audit: threading, concurrency, wx event loop, object lifecycle

Scope: `app.py` and every file under `src/` (read in full), `tests/conftest.py`,
`tests/test_weather_monitor.py`, `tests/test_polling_controller.py`,
`tests/test_main_window.py` (plus the other test files for context),
`hoppie_connector` 0.2.1 (`__init__.py`, `API.py`, `Messages.py`, `Responses.py`,
`Utilities.py`), and the wxPython 4.2.5 / wxWidgets 3.2.9 sources for the
behaviours the findings depend on.

Verification basis (things checked rather than assumed):

- `wx.Timer.Destroy` exists in wxPython 4.2.5 (runtime check), so
  `WeatherMonitor.shutdown()` is valid.
- `wx.CallAfter` asserts `wx.GetApp() is not None` (`wx/core.py:3418-3431`;
  runtime check raises `AssertionError: No wx.App created yet`), and
  `wxAppConsoleBase::~wxAppConsoleBase` sets `ms_appInstance = NULL`, so
  `wx.GetApp()` is `None` once the `wx.App` object has been collected.
- sip raises `RuntimeError: wrapped C/C++ object of type X has been deleted`
  for any method call on a proxy whose C++ object is gone (string present in
  `siplib.pyd`).
- wxPython's event thunker calls `PyErr_Print()` when a Python handler raises
  (Phoenix `src/event_ex.cpp`), i.e. `sys.excepthook` runs *inside* the
  failing handler's dispatch and no C++ exception is thrown.
- wxMSW `wxProcessTimer` calls `Stop()` on a one-shot timer *before*
  `Notify()`, and a WM_TIMER queued before `Stop()` is discarded because
  `Stop()` erases the id from the timer map (`src/msw/timer.cpp`).
- `wxTopLevelWindowBase::Destroy()` only appends to `wxPendingDelete`; it does
  not call `SendDestroyEvent()`. For a frame, `m_isBeingDeleted` is first set
  in `~wxFrameBase` / `~wxWindowMSW`, i.e. inside the destructor.
  `~wxWindowMSW` calls `DestroyChildren()`, which deletes child windows
  immediately (`child->wxWindowBase::Destroy()`), and `~wxDialog` calls
  `Show(false)`, which calls `m_modalData->ExitLoop()`.
- `wxWindowMSW::DoPopupMenu` calls `wxYieldForCommandsOnly()` after
  `TrackPopupMenu`, so the selected item's handler runs before `PopupMenu()`
  returns.
- `wx.App.__init__(..., clearSigInt=True)` installs `SIG_DFL` for SIGINT
  (`wx/core.py:2143`, `2188-2193`).
- `requests`: a scalar `timeout=15` is both the connect and the read timeout,
  and the read timeout applies to each socket read, not to the whole response
  (urllib3 `Timeout` docs); DNS resolution is not covered at all.
- Python-SimConnect (upstream `SimConnect/SimConnect.py`; the package is not
  installed in the venv): `connect()` busy-waits `while self.ok is False:
  pass` after a successful `Open`, `send_event()` returns `False` on failure
  (it does not raise), `map_to_sim_event()` returns `None` on failure,
  `exit()` joins the daemon dispatch thread.

Items in `TODOS.md` / the PR-24 spec were checked against the current code and
are fixed as described; finding 6 below refines TODO #3.

---

## Findings (ordered by severity)

### 1. Every network operation runs synchronously on the GUI thread; worst-case freezes of 15-60 s per operation with no feedback

- **Severity**: High. The client is a screen-reader-first tool, and in degraded
  network conditions it becomes silently unresponsive for tens of seconds at a
  time, repeatedly, with no way to cancel.
- **Confidence**: Confirmed (code paths and timeout semantics verified; durations
  are derived from the constants in the code).
- **Location(s)**:
  `src/config.py:147` (`NETWORK_TIMEOUT = 15`);
  `src/model/connection_manager.py:221-222` (connect: `HoppieConnector` + `ping`),
  `:286` (poll), `:368-373`/`:388` (sends), `:423` (inforeq GET);
  `src/controller/polling_controller.py:149` (poll inside the timer handler),
  `:186` (reconnection inside the same tick);
  `src/gui/main_window.py:324` (connect), `:380` and `:1085` (logoff on
  disconnect/close), `:734` (manual weather), `:986` (handover logon inside the
  poll tick), `:1017` (SimConnect inside the poll tick), `:386` (`MilliSleep`);
  `src/gui/dialogs/connect_dialog.py:62` and `src/gui/dialogs/pdc_dialog.py:53`
  (SimBrief fetch inside the dialog constructor, `src/utils/simbrief.py:28-32`,
  `timeout=10`);
  `src/utils/update_checker.py:40`, `:97` (manual check, `timeout=5`).
- **What is wrong**: Only the automatic weather cycle runs off the GUI thread.
  Everything else blocks the wx main loop. With `timeout=15` passed as a scalar,
  each HTTP call can take up to 15 s to connect plus up to 15 s per socket read
  (TLS handshake, headers, body), so the nominal worst case per call is about
  30 s, more for a trickling response, plus an unbounded OS DNS lookup. While
  blocked, no timers fire, no `CallAfter` results are delivered, no paint or
  accessibility queries are answered.
- **Failure scenario** (quantified):
  - `File > Connect` with a SimBrief ID set: up to ~20 s before the Connect
    dialog even appears (SimBrief fetch in the constructor), then up to ~30 s
    after OK (ping). Same ~20 s stall opening the PDC dialog.
  - Every poll tick: up to ~30 s, once every 20-75 s. A server that accepts
    TCP but goes silent therefore freezes the UI for 15-30 s out of every
    45-75 s; after three failures the same tick also runs
    `attempt_reconnection()` (another ~30 s in one handler), then polling stops
    with "Connection lost". Two to four minutes of mostly-frozen UI with no
    announcement.
  - A HANDOVER in a poll batch adds a synchronous logon send: poll + send up
    to ~60 s in a single timer tick; a CONTACT in the same batch adds the
    SimConnect setup (finding 5).
  - Manual weather request up to ~30 s; manual update check up to ~10 s;
    Exit while logged on: up to ~30 s after the confirm dialog is answered;
    Disconnect while logged on: up to ~30 s plus the 500 ms `MilliSleep`.
  - Accessibility impact: NVDA/JAWS query the window through UIA/MSAA; a
    window that is not pumping messages times those calls out, so the user
    hears nothing (or "not responding"), the status bar cannot be read, and
    keystrokes typed during the freeze are queued and replayed afterwards,
    landing on whatever dialog appears next.
- **Evidence**:
  ```python
  # connection_manager.py:421-425 (weather); the hoppie_connector calls have the
  # same 15 s applied by install_request_timeout()
  def _fetch():
      response = requests.get(api_url, params=params, timeout=NETWORK_TIMEOUT)
  # polling_controller.py:149
  messages, poll_status = self.connection_manager.poll()
  # connect_dialog.py:62, executed inside wx.Dialog.__init__
  ofp_data = get_latest_ofp(simbrief_userid)
  ```
- **Suggested fix direction**: Reuse the `WeatherMonitor` pattern (snapshot on
  the GUI thread, worker thread, `wx.CallAfter` back) for poll, send, connect
  and the SimBrief/update fetches; keep a single outstanding request per kind;
  announce "Connecting..."/"Sending..." in the status bar before starting and
  the outcome after. If that is too large a change, at minimum move the
  SimBrief fetch out of the dialog constructors and split the timeout into a
  short connect timeout and a total read budget.

### 2. An exception in the message callback drops the rest of the poll batch

- **Severity**: Medium. Messages already consumed from the server are lost for
  good, including LOGON ACCEPTED / HANDOVER / LOGOFF that drive session state;
  the guard exists precisely because callback failures are anticipated.
- **Confidence**: Confirmed.
- **Location(s)**: `src/controller/polling_controller.py:159-172`, `:197-198`;
  `hoppie_connector/__init__.py:66-85` (`poll()` marks messages relayed).
- **What is wrong**: `poll()` returns the whole batch and the server has already
  marked every message relayed. The loop re-raises on the first failing
  `message_callback(message)`, so messages 2..n are never logged (the
  "Received message" log line is per iteration), never displayed, never
  applied to `CpdlcSession`, and never considered by
  `should_increase_polling_rate`. The `finally` keeps polling alive, but the
  batch is gone.
- **Failure scenario**: Batch `[uplink A, HANDOVER EDGG]`. Handling of A raises
  (any exception escaping `_on_message_received`; today the concrete
  candidates are the deliberately unconverted local `OSError`s from the
  network layer during the nested logon, or a future bug in the SimConnect /
  view path). The user sees the "Unexpected Error" dialog for A; the HANDOVER
  is silently lost, the client still believes it is logged on to the old
  station, and the next uplinks from EDGG are not answerable from the context
  menu.
- **Evidence**:
  ```python
  for message in messages:
      self.logger.info(f"Received message: {message}")
      if self.message_callback:
          try:
              self.message_callback(message)
          except Exception:
              self.logger.exception("Error in message callback")
              raise
  ```
- **Suggested fix direction**: Keep the per-message `try`, but log and
  continue with the remaining messages (and still apply
  `should_increase_polling_rate`), then re-raise the first error (or report it
  via the excepthook) after the loop; alternatively add the message to the
  list before running the state/SimConnect logic so at least the text is shown.

### 3. `UpdateChecker` can close the main window from under an open modal dialog, and its prompt can pop over any modal

- **Severity**: Medium. Reachable in the very first run (welcome dialog ->
  Settings dialog -> update prompt within seconds); the outcome is a
  `RuntimeError` dialog at exit plus C++ undefined behaviour inside
  `ShowModal()`.
- **Confidence**: Plausible (every wx step verified in source; the end-to-end
  sequence was not executed).
- **Location(s)**: `src/utils/update_checker.py:42-49`, `:127-150`;
  `src/gui/main_window.py:98-101` (auto check started in `__init__`),
  `:1155-1158` (first launch schedules `on_settings` via `CallAfter`),
  `:250-296` (`on_settings` `ShowModal`/`Destroy`), `:1072-1095` (`on_close`
  ends with `event.Skip()` -> default handler -> `Destroy()`).
- **What is wrong**: `_show_update_dialog` runs via `wx.CallAfter`, which the
  main loop dispatches even while another dialog's modal loop is running. It
  shows a parentless YES/NO box on top of whatever is open, and on YES posts
  `self.parent.Close`. That `Close()` is also dispatched inside the open
  dialog's modal loop: `on_close` runs, `Skip()` leads to
  `wxTopLevelWindowBase::Destroy()` (deferred), and the deferred delete is
  executed by `DeletePendingObjects()` in the *dialog's* loop at the next
  idle. `~wxWindowMSW` -> `DestroyChildren()` deletes the modal dialog
  immediately; `~wxDialog` -> `Show(false)` -> `ExitLoop()`; `ShowModal()` then
  returns `GetReturnCode()` on a deleted object and the tied pointer writes
  into freed memory. Back in Python, `on_settings` continues with
  `dlg.Destroy()` (or `dlg.get_settings()`) on a dead proxy.
- **Failure scenario**: First launch -> "set up now?" Yes -> Settings dialog
  opens (CallAfter). ~1 s later the GitHub check finishes and "Update
  Available" appears over the settings form (focus yanked away from the field
  the user was editing). User answers Yes -> browser opens -> frame closes
  under the Settings dialog -> `RuntimeError: wrapped C/C++ object of type
  SettingsDialog has been deleted` -> "Unexpected Error" box -> app exits; the
  log records an error and, in the worst case, the process crashes in the
  freed-memory write.
- **Evidence**:
  ```python
  # update_checker.py:147-150
  webbrowser.open(release_url)
  wx.CallAfter(self.parent.Close)
  # main_window.py:259 / :296
  if dlg.ShowModal() == wx.ID_OK:
  ...
  dlg.Destroy()
  ```
- **Suggested fix direction**: Do not close the application from the checker
  (open the browser and leave the user in control), or have the main window
  own the "update available" state and act on it only when no modal dialog is
  active (e.g. check `wx.GetActiveWindow()`/a `_modal_depth` counter, or defer
  until the pending `ShowModal()` returns). Give the prompt a parent and delay
  it while a modal dialog is up.

### 4. CPDLC session state survives disconnect and failed reconnection, and leaks into the next connection

- **Severity**: Medium. After a reconnect the client can send requests to, and
  offer responses for, a station it is not logged on to; `Logoff` cannot clear
  the state while disconnected.
- **Confidence**: Confirmed.
- **Location(s)**: `src/model/cpdlc_session.py:108-141` (`logoff` only clears
  `current_station` on a successful send), no reset method anywhere in the
  class; `src/gui/main_window.py:349-402` (`on_disconnect` never resets the
  session), `:316-347` (`on_connect` only sets the callsign);
  `src/model/connection_manager.py:327-350` (failed `attempt_reconnection`
  clears `cnx` only); `src/controller/polling_controller.py:182-196`.
- **What is wrong**: `CpdlcSession.current_station`, `pending_logon_min`,
  `pending_logon_station` and `cpdlc_min_counter` are never reset when the
  network connection ends. `logoff()` returns `(False, None)` when the link is
  already gone and leaves `current_station` set, so `is_logged_on()` stays
  true through the disconnected period and into the next `connect()`, even
  with a different callsign or the other network.
- **Failure scenario**: (a) Logged on to LSAG; the link drops; three failed
  polls trigger `attempt_reconnection()`, which fails and stops polling. The
  user picks `File > Connect` (the label still reads "Disconnect", but the
  handler routes to `on_connect` because `is_connected()` is false) and
  connects as a new callsign. `is_logged_on()` is still true: the Requests
  menu sends `REQUEST FL350` to LSAG without a logon, uplinks from LSAG are
  answerable, the status bar and the exit confirmation talk about LSAG.
  (b) Explicit Disconnect while the network is already down: the LOGOFF send
  fails, `current_station` remains, and `Requests > Logoff` while offline
  only reports "Failed to send logoff message", with no way to clear it.
  Note: Hoppie logon state is kept by the ATC client keyed by callsign, so
  keeping the station across a reconnect with the *same* callsign may be
  intended; the different-callsign and unclearable cases are not.
- **Evidence**:
  ```python
  # cpdlc_session.py:116-118
  if not self.current_station or not self.connection_manager.is_connected():
      return False, None      # current_station untouched
  # main_window.py:389-394 -- no cpdlc_session reset
  self.polling_controller.stop()
  self.weather_monitor.stop()
  self.weather_monitor.clear()
  self.connection_manager.disconnect()
  ```
- **Suggested fix direction**: Add `CpdlcSession.reset()` and call it from
  `on_disconnect`, after a failed reconnection, and from `connect()` when the
  callsign/network changes; make `logoff()` clear local state even when the
  send fails (report the send failure separately).

### 5. SimConnect setup busy-waits on the GUI thread, a failed `send_event` is reported as success, and the retry path can orphan the dispatch thread

- **Severity**: Medium. The busy-wait has no timeout and runs inside the poll
  tick; the ignored return value defeats the "Auto-tune failed" status the
  pilot relies on.
- **Confidence**: Plausible for the hang (depends on simulator behaviour);
  Confirmed for the ignored return value and the retry logic (from the
  upstream source of Python-SimConnect and the manager code).
- **Location(s)**: `src/utils/simconnect_manager.py:43-60` (`connect`),
  `:74-111` (`set_com1_standby_mhz`), `:62-72` (`disconnect`);
  `src/gui/main_window.py:1010-1027` (called from the poll tick).
- **What is wrong**:
  1. `SimConnect()` -> `connect()`: after a successful `SimConnect_Open` it
     starts a daemon dispatch thread and spins `while self.ok is False: pass`
     on the calling (GUI) thread until the `SIMCONNECT_RECV_ID_OPEN` message
     arrives. Normally milliseconds, but there is no timeout: if the sim
     accepts the pipe and delays the OPEN reply (e.g. while loading), the GUI
     thread spins at 100% CPU for that long, in the middle of a poll tick.
  2. `send_event()` returns `False` on failure; `set_com1_standby_mhz` ignores
     the return value, logs "COM1 standby set" and returns `True`. If the sim
     was closed after the first successful connect, `_sm` is kept and every
     later CONTACT/MONITOR "succeeds" without tuning anything and without the
     status-bar warning.
  3. With the sim not running, `Open` fails silently (`ok` stays `False`, no
     exception), `map_to_sim_event` returns `None`, so `connect()` returns
     `True` with `_event_id = None`; `send_event(None, ...)` raises
     `AttributeError`, the manager resets and retries: two full constructor
     attempts per CONTACT/MONITOR message, all on the GUI thread.
  4. On the exception path the manager sets `self._sm = None` without calling
     `exit()`; if the dispatch thread had been started (Open succeeded, mapping
     failed) it is orphaned and keeps calling `CallDispatch` every 2 ms for the
     rest of the process.
  5. Thread-safety of `_simconnect_available` / `_warned_unavailable`: only the
     GUI thread touches them, so no race; the `_simconnect_available = None`
     reset merely re-runs a cached import.
- **Failure scenario**: CONTACT 121.800 arrives while MSFS is between flights;
  the poll tick blocks in the spin loop until the sim answers; NVDA reports the
  window as not responding. Separately: the sim is closed mid-flight, a later
  CONTACT logs "COM1 standby set to ..." and the pilot, told nothing, expects
  the standby frequency to be there.
- **Evidence**:
  ```python
  # simconnect_manager.py:96-100 -- return value of send_event never checked
  self._sm.send_event(self._event_id, freq_hz)
  logger.info(f"COM1 standby set to {frequency_mhz:.3f} MHz ({freq_hz} Hz)")
  return True
  # simconnect_manager.py:101-109 -- _sm dropped without exit()
  self._sm = None
  self._event_id = None
  ```
  Upstream: `while self.ok is False: pass` in `SimConnect.connect()`;
  `send_event` ends in `return False`; `map_to_sim_event` ends in
  `return None`.
- **Suggested fix direction**: Treat `_event_id is None` as a failed connect;
  check `send_event()`'s return; call `_sm.exit()` before dropping it; perform
  the SimConnect connect off the GUI thread (or once, at network connect time,
  with a watchdog) and only `send_event` from the message path.

### 6. Worker-thread liveness guards (`IsBeingDeleted()`) are ineffective and can raise; the exit-time error chain ends in an `AssertionError` inside `threading.excepthook`

- **Severity**: Low. Only reachable while the application is exiting with a
  fetch in flight; the effect is log noise and a dead worker, not user-visible
  behaviour. Reported because the guard is relied on as the frame-destroyed
  protection and it does not provide it.
- **Confidence**: Confirmed mechanism (wx source: TLW `Destroy()` does not set
  the flag; sip dead-proxy behaviour; `CallAfter` assertion); Plausible timing.
- **Location(s)**: `src/model/weather_monitor.py:304`, `:310-311`;
  `src/utils/update_checker.py:48`; `app.py:47-51`, `:59-60`.
- **What is wrong**: For a top-level frame, `IsBeingDeleted()` becomes true
  only inside the destructor (`~wxFrameBase`/`~wxWindowMSW`); the deferred
  `Destroy()` from `on_close` does not set it. So on the worker thread the
  check is either "alive -> False" or "already deleted -> `RuntimeError:
  wrapped C/C++ object ... has been deleted`". It is also a wx call from a
  non-GUI thread. In `_fetch_worker` the `RuntimeError` from `_post_result`
  (outside the inner `try`) propagates, `finally` calls `_post_cycle_finished`,
  which raises the same error; the thread dies, `threading.excepthook` ->
  `report()` -> `wx.CallAfter(show_dialog, ...)`, and if the `wx.App` object
  has already been collected `wx.CallAfter` raises
  `AssertionError('No wx.App created yet')` inside the excepthook.
  `_cycle_running` stays `True` (irrelevant at that point). The update
  checker's copy of the check is inside a broad `except`, so it only logs
  "Error checking for updates: wrapped C/C++ object ...".
- **Failure scenario**: The user closes the window while a 5-subscription
  cycle is mid-request. `MainLoop()` returns, `main()` logs "Application
  shutdown complete", and before interpreter finalisation freezes daemon
  threads the socket completes; the worker resumes, hits the dead proxy, and
  the log ends with "Unhandled exception in background thread: RuntimeError:
  wrapped C/C++ object of type MainWindow has been deleted" followed by an
  "Exception in threading.excepthook" on a stderr that does not exist
  (`console=False`).
- **Evidence**:
  ```python
  # weather_monitor.py:304
  if self._shutting_down or not self._parent or self._parent.IsBeingDeleted():
  # weather_monitor.py:310
  if not self._parent or self._parent.IsBeingDeleted():
  # app.py:51 (worker path)
  wx.CallAfter(show_dialog, text)
  ```
- **Suggested fix direction**: Never touch wx objects from the worker; have
  `shutdown()` set a Python-side flag / `self._parent = None`, check only that
  in the worker, wrap `wx.CallAfter` in `try/except (AssertionError,
  RuntimeError)`, and re-check liveness inside the GUI-thread callbacks. In
  `report()`, skip the dialog when `wx.GetApp() is None`.

### 7. The exception reporter opens a modal dialog from inside the failing handler's dispatch, so timers keep running under it and repeated faults stack dialogs

- **Severity**: Low. State machines survive it (verified), but a persistent
  fault produces one new modal "Unexpected Error" box per poll tick (every
  20-75 s), each of which a screen-reader user must dismiss.
- **Confidence**: Confirmed mechanism (Phoenix thunker calls `PyErr_Print()`
  synchronously).
- **Location(s)**: `app.py:31-51`; `src/controller/polling_controller.py:147-198`.
- **What is wrong**: When `on_poll_timer` (or a `CallAfter`'d weather callback)
  raises, `sys.excepthook` -> `wx.MessageBox` runs while the timer event is
  still being dispatched. The `finally` has already re-armed the one-shot, so
  the next tick fires inside the dialog's modal loop and runs the whole poll
  handler re-entrantly; if it raises again, a second dialog opens on top of
  the first, and so on. Weather results, sounds and status-bar updates also
  arrive while the error box is up.
- **Failure scenario**: A fault that repeats on every tick (for example a
  local `OSError` class the network layer deliberately does not convert,
  raised from `attempt_reconnection()` at `:186`, which catches only
  `HoppieError`): dialog at tick N, another at N+1 nested inside it, ... until
  the user disconnects. Each dialog steals focus from the one before.
- **Evidence**:
  ```python
  # app.py:47-48
  if wx.IsMainThread():
      show_dialog(text)          # synchronous modal, inside the failing handler
  ```
- **Suggested fix direction**: Coalesce reports (if a report dialog is
  already open, log only or append to it) and show it via `wx.CallAfter` even
  on the main thread so the failing handler unwinds first.

### 8. `SimCpdlcApp.OnExceptionInMainLoop` is unreachable for Python errors and would itself raise `TypeError` when it does run

- **Severity**: Low. Dead for the case it was written for; harmful only for a
  genuine C++ exception, which wxPython almost never surfaces.
- **Confidence**: Confirmed for the mechanism (thunker prints Python errors, so
  no C++ exception; `sys.exc_info()` is `(None, None, None)` outside a Python
  handler; `issubclass(None, KeyboardInterrupt)` raises `TypeError`, both
  checked at runtime); Plausible for reachability.
- **Location(s)**: `app.py:73-76`, `:53-57`.
- **What is wrong**: Python exceptions from handlers are already reported via
  `sys.excepthook` (called by `PyErr_Print()`); `OnExceptionInMainLoop` is only
  invoked for a C++ exception escaping a handler. In that case
  `sys.excepthook(*sys.exc_info())` calls `handle_uncaught(None, None, None)`,
  which raises `TypeError: issubclass() arg 1 must be a class`; the original
  problem is never logged and sip falls back to the default return value.
- **Evidence**:
  ```python
  def OnExceptionInMainLoop(self):
      sys.excepthook(*sys.exc_info())
      return True
  ```
- **Suggested fix direction**: Guard on `exc_type is not None`; otherwise log a
  generic "C++ exception in main loop" and return `True`. Or delete the
  override and rely on the excepthook, which is the path that actually runs.

### 9. Ctrl+C handling in `main()` is dead code: `wx.App` resets SIGINT to `SIG_DFL`, so an interrupt kills the process without any cleanup

- **Severity**: Low. Only affects console runs (`python app.py`); the packaged
  build has no console. Reported because the code claims to handle it.
- **Confidence**: Confirmed (`wx/core.py:2143` default `clearSigInt=True`,
  `:2188-2193`).
- **Location(s)**: `app.py:69-71` (`super().__init__(False)` leaves
  `clearSigInt=True`), `:100-105`, `:53-56`.
- **What is wrong**: With `SIG_DFL` installed, Ctrl+C terminates the process
  immediately: no `KeyboardInterrupt`, no `frame.on_exit(None)`, no LOGOFF, no
  "Application shutdown complete" log line, and the `finally` never runs. Even
  if the branch were reached, `frame.on_exit(None)` after `MainLoop()` has
  returned would run `on_close` synchronously and queue a `Destroy()` that no
  loop ever processes (and raise `RuntimeError` if the frame was the reason
  the loop ended).
- **Evidence**:
  ```python
  try:
      app.MainLoop()
  except KeyboardInterrupt:
      logger.info("Application terminated by keyboard interrupt")
      frame.on_exit(None)
  ```
- **Suggested fix direction**: Either pass `clearSigInt=False` and handle
  SIGINT deliberately (a short `wx.Timer` lets Python deliver the signal, then
  call `frame.Close()`), or remove the dead branch.

### 10. `dlg.Destroy()` is not reached when anything raises between `ShowModal()` and the end of the handler

- **Severity**: Low. Leaks a hidden dialog per failure and skips the trailing
  UI updates; the exception itself is already reported.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:259-296` (settings), `:320-347`
  (connect), `:417-449` (logon; the early `dlg.Destroy(); return` at `:427-428`
  is correct), `:513-533`, `:554-570`, `:591-609`, `:630-646`, `:673-690`,
  `:720-754`, `:810-840`.
- **What is wrong**: None of the `ShowModal()` ... `Destroy()` sequences uses
  `try/finally` or `with dlg:`. Normal branches all reach `Destroy()`.
  Exceptions that can occur in between are exactly the ones the network layer
  chooses not to convert to `HoppieError` (local `OSError`s such as the
  missing CA bundle case pinned by
  `test_a_local_os_error_is_not_disguised_as_a_network_failure`), since
  `CpdlcSession` catches only `HoppieError`, plus any wx error in
  `_add_custom_message`.
- **Failure scenario**: `on_connect` -> `connect()` raises `OSError` -> the
  excepthook dialog appears, the Connect dialog object stays alive (hidden) as
  a child TLW until the frame closes; repeated attempts accumulate them.
- **Evidence**:
  ```python
  dlg = ConnectDialog(self)
  if dlg.ShowModal() == wx.ID_OK:
      ...
      self.connection_manager.connect(callsign, logon_code, network_type)  # may raise non-HoppieError
  ...
  dlg.Destroy()
  ```
- **Suggested fix direction**: `with SettingsDialog(...) as dlg:` (wxPython
  dialogs support the context-manager protocol and call `Destroy()`), or
  `try/finally`.

### 11. A weather cycle in flight survives disconnect/reconnect and resumes under the new session's identity; the credential snapshot it takes is not atomic

- **Severity**: Low. Wastes requests and, in a microsecond window, can pair one
  network's URL with the other network's logon code; no state corruption on the
  GUI side.
- **Confidence**: Confirmed.
- **Location(s)**: `src/model/weather_monitor.py:107` (`start()` clears
  `_shutting_down`), `:120-125`, `:218-224`, `:262-269`, `:278-298`;
  `src/model/connection_manager.py:246-251`, `:264-270` (fields written one at
  a time), `:408-418` (fields read one at a time on the worker).
- **What is wrong**: `stop()` only sets a flag the worker samples once per
  subscription (before a 1 s sleep and a request of up to ~30 s). If the user
  disconnects and reconnects inside that window, `start()` has already cleared
  `_shutting_down`, so the worker never notices: it finishes the *old*
  subscription list using whatever `cnx`/`network_type`/`logon_code`/`callsign`
  are current, and posts results that `_on_result` drops (`:328-331`) unless the
  same key was re-subscribed. Independently, the worker reads the four
  attributes in sequence while `connect()`/`disconnect()` write them in
  sequence on the GUI thread; a GIL switch between the reads yields a mixed
  snapshot (SayIntentions URL + Hoppie logon, or an empty `from=`/`logon=`),
  i.e. one malformed request or one credential sent to the other network's
  server. The counters are safe: the worker touches only `info_failures`,
  which gates nothing; `cnx` is swapped by a single attribute assignment and
  never dereferenced across threads.
- **Failure scenario**: Ten subscriptions; the user disconnects from Hoppie and
  connects to SayIntentions within a few seconds. Up to nine more `inforeq`
  GETs go to SayIntentions for the Hoppie-era airports under the new
  credentials, then results are discarded; meanwhile new ticks are skipped
  because `_cycle_running` is still `True`.
- **Evidence**:
  ```python
  # weather_monitor.py:278-283
  for index, (icao, info_type) in enumerate(pending):
      if self._shutting_down:
          break
      if index:
          time.sleep(_REQUEST_SPACING_SECONDS)
  # connection_manager.py:411-414 (worker thread)
  api_url = self._api_url()
  params = {"logon": self.logon_code, "from": self.callsign, ...}
  ```
- **Suggested fix direction**: Give each cycle a generation number captured
  in `_run_cycle` and checked in `_post_result`/`_on_result`; snapshot the
  credentials on the GUI thread in `_run_cycle` and pass them into the worker
  (e.g. a `send_info_request(info_type, icao, credentials)` overload).

### 12. No overall deadline for a weather cycle: a single stuck request keeps `_cycle_running` true for the rest of the session

- **Severity**: Low. Automatic updates silently stop and "Check now" keeps
  saying a check is already running; no other damage.
- **Confidence**: Confirmed (design gap; timeout semantics verified).
- **Location(s)**: `src/model/weather_monitor.py:253-255`, `:264-269`,
  `:299-317`; `src/model/connection_manager.py:423`.
- **What is wrong**: Per request the bound is 15 s connect + 15 s per socket
  read (not total) + unbounded DNS; per cycle it is that times the number of
  subscriptions, plus 1 s spacing, sequentially. Ten subscriptions can exceed
  the default 5-minute interval on a slow link, so alternate ticks are skipped
  and the effective interval doubles. A trickling response or a hung resolver
  has no upper bound at all, and nothing ever clears `_cycle_running` except
  the worker itself.
- **Evidence**:
  ```python
  if self._cycle_running:
      self.logger.debug("Weather update cycle still running, skipping this tick")
      return False
  ```
- **Suggested fix direction**: Per-cycle budget (e.g. the interval itself) and
  a generation counter so the timer can abandon a late cycle and start a new
  one; optionally fetch subscriptions concurrently with a small pool.

### 13. `on_disconnect` sleeps 500 ms on the GUI thread for no effect and re-arms polling immediately before stopping it

- **Severity**: Low. A half-second freeze and two pointless timer operations.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:379-391`.
- **What is wrong**: `send_logoff_message()` is synchronous; when it returns the
  HTTP request has completed, so the "small delay to allow the message to be
  sent" achieves nothing except blocking the loop (no timers, no `CallAfter`
  deliveries run inside `wx.MilliSleep`). `polling_controller.set_active_polling()`
  at `:383` does `Stop()` + `StartOnce(20000)` three lines before `stop()`.
- **Evidence**:
  ```python
  self.polling_controller.set_active_polling()
  # Small delay to allow the message to be sent
  wx.MilliSleep(500)  # 500ms delay
  # Stop polling and automatic weather updates
  self.polling_controller.stop()
  ```
- **Suggested fix direction**: Delete both lines.

### 14. (Info) `_check_first_launch` runs a modal loop in the middle of `__init__`, before `_init_ui`, before `EVT_CLOSE` is bound, and before the controllers exist

- **Severity**: Info. Safe today; fragile.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/main_window.py:79`, `:1142-1153`, `:126`.
- **What is wrong / why it is fine now**: The welcome `wx.MessageDialog` is
  shown while the frame has no panel, no message view, no `weather_monitor`,
  no `polling_controller`, no `update_checker` and no close handler. Nothing
  else can run in that nested loop today (no timers, no threads, no pending
  `CallAfter`), and the follow-up `on_settings` is correctly deferred with
  `wx.CallAfter`, so `self.weather_monitor` exists by the time it runs
  (created at `:117`, before `Show()` and before the main loop starts). A
  forced close during the welcome dialog would bypass `on_close`. Prefer
  scheduling the whole first-launch prompt with `wx.CallAfter` after
  construction.

### 15. (Info) `WeatherSubscriptionsDialog` can show stale entries while open

- **Severity**: Info. No crash.
- **Confidence**: Confirmed.
- **Location(s)**: `src/gui/dialogs/weather_subscriptions_dialog.py:94-104`,
  `:131-139`; `src/model/weather_monitor.py:339-345`.
- **What is wrong**: `CallAfter`'d `_on_result` callbacks run during the
  dialog's modal loop, so a subscription can be dropped for
  `MAX_CONSECUTIVE_ERRORS` while it is listed. `_keys` is not refreshed, so
  "Stop updating" on that row unsubscribes a key that is already gone
  (returns `False`) and the following `_refresh()` corrects the list. A
  refresh hook from `on_error`/`on_update` would keep the list honest.

### 16. (Info) A non-vetoable close still shows the confirm dialog and calls `Veto()`

- **Severity**: Info. Only on `Close(force=True)` paths such as a Windows
  end-session.
- **Confidence**: Confirmed for the code; the wx assertion behaviour is
  standard (`wxCloseEvent::Veto` is a `wxCHECK_RET`).
- **Location(s)**: `src/gui/main_window.py:1077-1079`, `:1111-1121`.
- **What is wrong**: `_confirm_exit` does not check `event.CanVeto()`. On a
  forced close it still blocks in a MessageBox and, on "No", calls `Veto()`,
  which trips a wx assertion (raised as `wx.wxAssertionError` under
  wxPython's default assert mode); `shutdown()` and `Skip()` are then skipped.
  Check `CanVeto()` and go straight to cleanup when it is false.

---

## Things I checked that are fine

- **WeatherMonitor ownership model.** All subscription mutation
  (`subscribe`/`unsubscribe`/`clear`/`_on_result`) is on the GUI thread; the
  worker receives a list of `(icao, info_type)` tuples, never the dict; results
  come back through `wx.CallAfter` in FIFO order with `_on_cycle_finished`
  posted last, so `_cycle_running` is cleared only after every result of that
  cycle has been applied; `_on_result` tolerates unsubscribe/clear/re-subscribe
  while a request was in flight (`weather_monitor.py:328-331`);
  `_cycle_running` is written on the GUI thread except in the dead-frame path
  of finding 6.
- **Timer lifecycle across start/stop/shutdown/start.** `wx.Timer.Destroy()`
  exists; `shutdown()` stops, destroys and nulls the timer, and the next
  `start()` creates a fresh timer and binding on the same parent; `stop()` and
  `start()` are idempotent; `set_interval()` while stopped only stores the
  value that the next `start()` uses; `check_now()` while stopped or
  disconnected returns `False` (covered by `test_weather_monitor.py`).
  `shutdown()` is only called from `on_close`, so the never-unbound old
  `EVT_TIMER` entry cannot accumulate.
- **Weather timer re-entrancy.** It is a continuous timer whose handler only
  snapshots and spawns; a tick inside a nested modal loop is harmless.
- **PollingController one-shot state machine.** wxMSW stops a one-shot timer
  before `Notify()`, so `is_running()` is false inside the tick and the
  `set_active_polling()` guard behaves as the test
  `test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once`
  describes; there is a single `wx.Timer`, and `StartOnce` on it restarts it,
  so there can never be two pending polls; every exit from `on_poll_timer`
  either reaches the `finally` reschedule or deliberately called `stop()`
  first; a WM_TIMER already queued when `stop()` runs is discarded by the MSW
  timer map; `stop()` followed by `start()` reuses the bound timer correctly
  (`_stopped` cleared, `_schedule_next()` re-arms); `_next_poll_at` is only
  read/written on the GUI thread; ticks cannot overlap because the handler
  contains no modal dialog (the only modal that can nest inside a tick is the
  excepthook's, finding 7).
- **Modal dialogs inside the timer handler.** `_on_message_received` shows no
  dialogs; `wx.MessageBox` appears only in menu handlers, in
  `_on_acknowledge_message` (PopupMenu context), and in the excepthook.
- **message_view.py context menus.** Bindings are per-item-id on the panel,
  the panel is the `PopupMenu` target, wxMSW dispatches the resulting
  WM_COMMAND before `PopupMenu()` returns, and `Unbind(wx.EVT_MENU, id=...)`
  matches the real `EvtHandler.Unbind(event, source=None, id=..., id2=...,
  handler=None)` signature, so the handler always runs before the unbind and
  no binding accumulates (TODO #2 is fixed). Lambda defaults (`resp=`, `mid=`,
  `r=`) avoid late binding. `PopupMenu` cannot be re-entered: the list is
  disabled while any modal opened by the handler is up. A handler exception is
  swallowed by the thunker, so `Unbind`/`menu.Destroy()` still run.
  `wx.ID_ANY` menu-item ids are unique among live items.
- **Construction order vs. `CallAfter`.** `on_settings` scheduled from
  `_check_first_launch` runs after `__init__` completes; every attribute it
  uses (`weather_monitor`) exists by then. The update-check thread started at
  `main_window.py:101` touches only `self.parent` and `wx.CallAfter`, and its
  `CallAfter`'d dialog cannot run before the main loop starts.
- **`on_close` sequence.** Polling stopped (whenever connected), weather timer
  destroyed before the frame, SimConnect `exit()` joins its 2 ms loop quickly,
  then `Skip()`. The poll timer is always stopped whenever `is_connected()`
  becomes false (`on_disconnect`, failed `attempt_reconnection`, the
  not-connected branch of the tick), so no running timer can outlive its owner
  frame. Anything still queued afterwards is harmless on the GUI thread:
  `_on_result` is not posted once `_shutting_down` is set,
  `_on_cycle_finished` is pure Python, and `event.Skip()`/`Veto()` are paired
  correctly on every normal path.
- **SimConnectManager flags.** `_simconnect_available` and
  `_warned_unavailable` are touched only from the GUI thread (message path
  and `on_close`); Python-SimConnect's dispatch thread never reaches them.
- **`wx.adv.Sound`.** Loaded once in `__init__`; `Play(SOUND_ASYNC)` is
  non-blocking; `if self.new_message_sound:` uses `Sound.__bool__` ->
  `IsOk()`, so a file that exists but fails to load is skipped; only called on
  the GUI thread (`_on_message_received` from the timer, `_on_weather_update`
  via `CallAfter`).
- **`wx.CallAfter` first-use race.** The lazy `_CallAfterId` initialisation
  is not locked, but the first call is on the GUI thread (first launch) or the
  update thread seconds after start, long before the weather worker exists,
  and a double initialisation would still dispatch correctly.
- **`install_request_timeout`.** It rebinds `requests.get`/`requests.post`,
  which `hoppie_connector/API.py:39,44` looks up at call time, so every
  connector call gets the 15 s default; the three app-owned request sites pass
  explicit timeouts.
- **ConnectionManager cross-thread counters.** The worker writes only
  `info_failures`, which is excluded from `failure_count()` and therefore
  from reconnection decisions (spec fix 6, verified); `connection_failures`,
  `send_failures` and the connector object are GUI-thread only.
- **Logging and excepthooks.** Handlers are thread-safe; both hooks are
  installed before any thread or `wx.App` exists; `report()` correctly routes
  worker-thread reports through `wx.CallAfter` (modulo finding 6).
- **hoppie_connector usage.** `HoppieConnector.__init__` performs no I/O;
  `ping`, `poll`, `send_cpdlc` (GET) and `send_telex` (POST) are one request
  each; `_call` converts `ValueError`/`TypeError`/`ConnectionError`/
  `RequestException` to `HoppieError` for every path the worker uses, so the
  weather thread's `except HoppieError` covers the library's failure modes.
