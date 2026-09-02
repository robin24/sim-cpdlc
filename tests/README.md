# Tests

Offline checks for the CPDLC request formats, the automatic weather update
logic and the main window wiring. They need no network connection, no running
simulator and no ACARS logon code.

Run the whole suite from the repository root, which is what CI does:

```bash
pytest
```

Most files are ordinary pytest modules. `test_requests_and_weather.py` and
`test_main_window.py` are self-checking scripts instead, so they also run on
their own without pytest installed:

```bash
python tests/test_requests_and_weather.py
python tests/test_main_window.py
```

Under `pytest` these two report no test items; their assertions run as the
module is imported, and a failure exits non-zero and fails the run.

`test_requests_and_weather.py` asserts the exact text of every downlink message
the client can send, so a change to a message format will show up here before it
reaches the network.

`test_main_window.py` builds the real main window and checks the menu structure,
that every menu item has a handler, and that multi-line messages are flattened
in the message list but keep their line breaks in the detail pane.
