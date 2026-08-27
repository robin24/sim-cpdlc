# Tests

Offline checks for the CPDLC request formats, the automatic weather update
logic and the main window wiring. They need no network connection, no running
simulator and no ACARS logon code.

Run them from the repository root:

```bash
python tests/test_requests_and_weather.py
python tests/test_main_window.py
```

`test_requests_and_weather.py` asserts the exact text of every downlink message
the client can send, so a change to a message format will show up here before it
reaches the network.

`test_main_window.py` builds the real main window and checks the menu structure,
that every menu item has a handler, and that multi-line messages are flattened
in the message list but keep their line breaks in the detail pane.
