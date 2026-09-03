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
`make_main_window`, `FakeClock`, `answerable`, ...) live in `support.py`; import them with
`from tests.support import ...`.

| File | Covers |
| --- | --- |
| `test_acknowledge_path.py` | Responding to an uplink, end to end from the window, down to the frame |
| `test_config.py` | Reading, writing and clamping the configuration |
| `test_connection_manager.py` | The network boundary: errors, timeouts, poll results, unreadable uplinks, the wire packets |
| `test_cpdlc_session.py` | Session state: logon acceptance and rejection, the handover window, pending expiry, reset and identity |
| `test_dialogs.py` | The validation the weather request dialog applies before submitting |
| `test_downlink_requests.py` | The exact text of every downlink the client can send, and every send failure |
| `test_error_reporting.py` | The last-resort exception reporter: one deferred dialog at a time |
| `test_frequency_parser.py` | Which CONTACT/MONITOR texts tune the standby radio |
| `test_harness.py` | The hermetic fixtures themselves |
| `test_link_state.py` | The link state machine and its back-off ladder |
| `test_link_status.py` | How the window announces a lost, restored or fatal link and unreadable uplinks |
| `test_logon_status.py` | Logon state as reported to the user, including a logon nobody answered |
| `test_main_window.py` | The real window: menu bindings, message list, weather toggles |
| `test_main_window_wiring.py` | `_init_ui` alone, on a stripped-down frame |
| `test_message_formatting.py` | Packet prefix stripping and the list and detail text |
| `test_message_manager.py` | Message storage, addressing and the full response table |
| `test_message_view.py` | The message list and its response context menu |
| `test_polling_controller.py` | Poll intervals, the back-off ladder while the link is lost, batch delivery, the tick callback |
| `test_session_lifecycle.py` | Where the dialogue ends: disconnect, exit, a rejected logon code; and that a lost link is not one |
| `test_uplink_handling.py` | HANDOVER, LOGOFF, LOGON REJECTED, protocol noise and auto-tune through the window, including the station that handed over |
| `test_weather_monitor.py` | Weather change detection and the update timer lifecycle |
| `test_weather_parsing.py` | The report registry, the ATIS letter and the report formatters |

`test_downlink_requests.py` asserts message text literally, so a change to a
format shows up there before it reaches the network.
