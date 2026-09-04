# Tests

Offline checks for the CPDLC request formats, the message handling in the
window, the automatic weather update logic and the main window wiring. They
need no network connection, no running simulator and no ACARS logon code, and
the fixtures in `conftest.py` make sure of it: every test gets a temporary
config file, outbound requests and browser launches raise, SimBrief lookups
answer with no flight plan, and `wx.MessageBox` and `wx.MessageDialog` are
recorders.

Run them from the repository root:

```bash
pip install -r requirements-dev.txt
pytest
```

The GUI tests build real wx windows, dialogs and timers, so they need a desktop
session; CI runs them on Windows for that reason. Each test is limited to 60
seconds.

Shared test doubles (`uplink`, `FakeConnectionManager`, `FakeSimConnectManager`,
`make_main_window`, `FakeClock`, `answerable`, `inline_worker`, ...) live in `support.py`; import them with
`from tests.support import ...`. Network work runs on a worker thread in the
application; tests use `inline_worker()`, which has no thread, and call
`run_pending()` to run what a handler queued. The few tests that build the real
window start its worker thread and shut it down at teardown, and two worker tests
start a thread on purpose.

| File | Covers |
| --- | --- |
| `test_about_dialog.py` | The About box: the "(source)" label and the copyright year |
| `test_acknowledge_path.py` | Responding to an uplink, end to end from the window, queued on the worker, down to the frame |
| `test_config.py` | Reading, writing and clamping the configuration; what the log says about it |
| `test_connection_manager.py` | The network boundary: errors, timeouts, poll results, unreadable uplinks, the wire packets |
| `test_cpdlc_session.py` | Session state: logon acceptance and rejection, the handover window, pending expiry, reset and identity |
| `test_dialog_mnemonics.py` | Every dialog control has a unique access key and an accessible name |
| `test_dialogs.py` | The weather request dialog's validation; the Connect and PDC dialogs filling in from SimBrief; the Settings, Connect and PDC getters returning stripped fields |
| `test_downlink_requests.py` | The exact text of every downlink the client can send, and every send failure, through the worker |
| `test_error_reporting.py` | The last-resort exception reporter: one deferred dialog at a time |
| `test_frequency_parser.py` | Which CONTACT/MONITOR texts tune the standby radio |
| `test_harness.py` | The hermetic fixtures themselves |
| `test_link_state.py` | The link state machine and its back-off ladder |
| `test_link_status.py` | How the window announces a lost, restored or fatal link and unreadable uplinks |
| `test_logging_setup.py` | The log handlers: the file always, the console only when there is one; SimBrief's logger |
| `test_logon_status.py` | Logon state as reported to the user, including a logon nobody answered |
| `test_main_window.py` | The real window: menu bindings and mnemonics, message list, weather toggles, settings, the logon gate |
| `test_main_window_wiring.py` | `_init_ui` alone, on a stripped-down frame |
| `test_message_formatting.py` | Packet prefix stripping and the list and detail text, including doubled separators |
| `test_message_manager.py` | Message storage, addressing and the full response table |
| `test_message_view.py` | The message list, its column layout and its response context menu |
| `test_network_worker.py` | The network worker: ordering, generations, pacing, failure capture, shutdown; the collaborators that require one |
| `test_polling_controller.py` | Poll intervals, polls on the worker, the back-off ladder while the link is lost, batch delivery, the tick callback |
| `test_release.py` | The three version strings agree, the build tools stay out of the runtime requirements, the release workflow tests before it builds |
| `test_request_dialogs.py` | The OK-button rules and the returned values of the logon, altitude, direct-to, speed, when-can-we and telex dialogs, including the telex character count |
| `test_session_lifecycle.py` | Connect, disconnect and exit through the worker; a rejected logon code; a lost link is not a disconnect |
| `test_simconnect_manager.py` | The SimConnect tune path: no connecting on its own, the simulator's answer believed |
| `test_tools.py` | The manual SimBrief probe refuses to run without a user id |
| `test_update_checker.py` | The update check off the GUI thread, and the prompt that waits for open dialogs |
| `test_uplink_handling.py` | HANDOVER, LOGOFF, LOGON REJECTED, protocol noise and auto-tune through the window, including the station that handed over |
| `test_weather_monitor.py` | Weather change detection, the update cycle on the worker, the timer lifecycle, change listeners |
| `test_weather_parsing.py` | The report registry, the ATIS letter and the report formatters |
| `test_weather_requests.py` | The manual weather request through the window; the report or the error arrives from the worker |
| `test_weather_subscriptions_dialog.py` | The automatic weather updates dialog: what it lists, stopping through the window, following the monitor |

`test_downlink_requests.py` asserts message text literally, so a change to a
format shows up there before it reaches the network.
