# Tests

Offline checks for the CPDLC request formats, the automatic weather update
logic and the main window wiring. They need no network connection, no running
simulator and no ACARS logon code.

Run them from the repository root:

```bash
pip install -r requirements-dev.txt
pytest
```

The GUI tests build real wx windows, dialogs and timers, so they need a desktop
session; CI runs them on Windows for that reason.

| File | Covers |
| --- | --- |
| `test_acknowledge_path.py` | Responding to an uplink, end to end from the window |
| `test_connection_manager.py` | The network boundary: errors, timeouts, reconnection |
| `test_cpdlc_session.py` | Session state and logon acceptance validation |
| `test_dialogs.py` | The validation each request dialog applies before submitting |
| `test_downlink_requests.py` | The exact text of every downlink the client can send |
| `test_logon_status.py` | Logon state as reported to the user |
| `test_main_window.py` | The real window: menus, handlers, message list, weather toggles |
| `test_main_window_wiring.py` | `_init_ui` alone, on a stripped-down frame |
| `test_message_manager.py` | Message storage, addressing and response options |
| `test_message_view.py` | The message list and its response context menu |
| `test_polling_controller.py` | Which messages speed up polling, and the poll intervals |
| `test_weather_monitor.py` | Weather change detection and the update timer lifecycle |

`test_downlink_requests.py` asserts message text literally, so a change to a
format shows up there before it reaches the network.
