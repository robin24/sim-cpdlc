# Package 1: Test Harness Hermeticity and Protocol Regression Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the test suite unable to touch the developer's real configuration, the network, SimBrief, SimConnect or a modal dialog, and pin the CPDLC protocol behaviour that later packages must not break.

**Architecture:** Helpers and test doubles move from `tests/conftest.py` into a plain module `tests/support.py`; `conftest.py` keeps fixtures only and gains four autouse fixtures (`isolated_config`, `no_network`, `no_simbrief`, `message_boxes`) plus a leaked-window assertion in `wx_app`. New regression tests assert the literal wire frames, the MRN validation, the response table, every message-handling branch of `MainWindow._on_message_received`, the menu and context-menu bindings, the config file round trip and the two parsers. No production code under `src/` changes in this package.

**Tech Stack:** Python 3.12+, pytest 9.1.1, pytest-timeout, wxPython 4.2.5, hoppie-connector 0.2.1.

## Global Constraints

- Run every command with the only interpreter that has the dependencies: `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below written as `$PY`). It works from any working directory, including a fresh git worktree. In Git Bash: `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`.
- Run the suite from the repository root as `$PY -m pytest -q -p no:cacheprovider`. It must be green at the end of every task. Baseline before this plan: 135 passed.
- Tests must never read or write the real config file (`%LOCALAPPDATA%\Sim-CPDLC\Sim-CPDLC\config.json`), reach the network, call SimBrief, touch the simulator, or block on a dialog.
- This package changes only `tests/`, `requirements-dev.txt`, `pytest.ini`, `.github/workflows/tests.yml` and `tests/README.md`. Do not edit anything under `src/`. Where a step says "mutation check", the temporary edit to `src/` is reverted with `git checkout -- <file>` in the same step.
- Import helpers as `from tests.support import ...` (the repo root is on `sys.path` via `pythonpath = .` in `pytest.ini`; `tests/` has no `__init__.py` and needs none).
- Commit messages: imperative sentence subject, optional body, and end with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 1". Audit: `docs/audit/2026-09-03-codebase-audit.md` (M-11, M-12, L-21).

---

## File structure

| File | Responsibility after this plan |
|---|---|
| `tests/support.py` (new) | Test doubles and builders: `uplink`, `FakeConnectionManager`, `RecordingMessageView`, `FakePollingController`, `FakeSimConnectManager`, `make_main_window`. No fixtures. |
| `tests/conftest.py` (rewrite) | Fixtures only: `logger`, `isolated_config`, `no_network`, `no_simbrief`, `message_boxes`, `wx_app` (with leak assertion), `frame`. |
| `tests/test_harness.py` (new) | Proves the hermetic fixtures do what they claim. |
| `tests/test_uplink_handling.py` (new) | `MainWindow._on_message_received` branches: HANDOVER, LOGOFF, protocol-noise filter, CONTACT auto-tune. |
| `tests/test_frequency_parser.py` (new) | Table test for `extract_contact_frequency`. |
| `tests/test_message_formatting.py` (new) | Table tests for `extract_message_content`, `format_list_text`, `format_message_text`. |
| `tests/test_acknowledge_path.py`, `test_connection_manager.py`, `test_cpdlc_session.py`, `test_logon_status.py`, `test_message_manager.py`, `test_downlink_requests.py`, `test_main_window.py`, `test_message_view.py`, `test_config.py` | Existing files gain the regression tests listed per task; imports switch to `tests.support`. |
| `requirements-dev.txt`, `pytest.ini`, `.github/workflows/tests.yml` | pytest-timeout and CI job timeout. |
| `tests/README.md` | Regenerated table. |

---

### Task 1: Move the shared helpers into `tests/support.py`

**Files:**
- Create: `tests/support.py`
- Modify: `tests/conftest.py:1-115` (remove everything except the `logger`, `wx_app`, `frame` fixtures)
- Modify (imports only): `tests/test_acknowledge_path.py:3`, `tests/test_cpdlc_session.py:3`, `tests/test_downlink_requests.py:10`, `tests/test_logon_status.py:8`, `tests/test_main_window_wiring.py:12`, `tests/test_message_manager.py:3`, `tests/test_message_view.py:6`, `tests/test_polling_controller.py:7`

**Interfaces:**
- Produces (used by every later task):
  - `uplink(sender, min_value, text="CLIMB TO AND MAINTAIN FL360", rr=RR.WILCO_UNABLE, mrn=None) -> CpdlcMessage`
  - `FakeConnectionManager(connected=True, raise_with=None)` with `.sent` (list of `(recipient, min, rr, text, mrn)`), `.telexes` (list of `(recipient, text)`), `.info_requests`, `is_connected()`, `send_cpdlc(...)`, `send_telex(recipient, message)`, `send_info_request(info_type, icao)`
  - `FakeSimConnectManager(result=True)` with `.tuned` (list of floats), `.result`, `connect()`, `disconnect()`, `set_com1_standby_mhz(frequency_mhz) -> bool`
  - `RecordingMessageView` with `.added`; `FakePollingController` with `.active_calls`
  - `make_main_window(logger, cpdlc_session, message_manager, config=None, simconnect=None) -> MainWindow` (window has `.status_texts`, `.message_view.added`, `.polling_controller.active_calls`, `.simconnect_manager`)
  - `CLIENT_CALLSIGN = "DLH123"`

- [ ] **Step 1: Create `tests/support.py`**

```python
"""Shared test doubles and builders for the sim-cpdlc test suite.

These are helpers, not fixtures: import them explicitly with
`from tests.support import ...`. Fixtures live in conftest.py.
"""

from hoppie_connector import CpdlcMessage, CpdlcResponseRequirement as RR

from src.config import DEFAULT_CONFIG, save_config

CLIENT_CALLSIGN = "DLH123"


def uplink(
    sender, min_value, text="CLIMB TO AND MAINTAIN FL360", rr=RR.WILCO_UNABLE, mrn=None
):
    """Build an uplink CpdlcMessage as it would arrive from a station.

    Args:
        sender: Station sending the message
        min_value: The station's own message number (MIN)
        text: Message element text
        rr: Response requirement
        mrn: Message reference number, the MIN of our message this one
            answers. Every real LOGON ACCEPTED carries one.
    """
    return CpdlcMessage(sender, CLIENT_CALLSIGN, min_value, rr, text, mrn)


class FakeConnectionManager:
    """Stands in for ConnectionManager, recording frames instead of transmitting.

    ConnectionManager is the network boundary and is injected into CpdlcSession,
    so this is the intended seam rather than a mock of code under test.

    Args:
        connected: What is_connected() reports
        raise_with: An exception every send raises instead of recording, for
            exercising the failure paths
    """

    def __init__(self, connected=True, raise_with=None):
        self._connected = connected
        self.raise_with = raise_with
        self.sent = []
        self.telexes = []
        self.info_requests = []

    def is_connected(self):
        return self._connected

    def send_cpdlc(self, recipient, min_value, response_type, message, mrn=None):
        if self.raise_with is not None:
            raise self.raise_with
        self.sent.append((recipient, min_value, response_type, message, mrn))

    def send_telex(self, recipient, message):
        if self.raise_with is not None:
            raise self.raise_with
        self.telexes.append((recipient, message))

    def send_info_request(self, info_type, icao):
        if self.raise_with is not None:
            raise self.raise_with
        self.info_requests.append((info_type, icao))
        return f"{icao} REPORT FOR {info_type}"


class RecordingMessageView:
    """Captures the message IDs the window pushes into the list view."""

    def __init__(self):
        self.added = []

    def add_message(self, message_id):
        self.added.append(message_id)


class FakePollingController:
    """Records polling-rate changes without owning a wx.Timer."""

    def __init__(self):
        self.active_calls = 0

    def set_active_polling(self):
        self.active_calls += 1


class FakeSimConnectManager:
    """Records the frequencies the window tries to tune, never touching a simulator.

    Args:
        result: What connect() and set_com1_standby_mhz() report back
    """

    def __init__(self, result=True):
        self.result = result
        self.tuned = []

    def connect(self):
        return self.result

    def disconnect(self):
        pass

    def set_com1_standby_mhz(self, frequency_mhz):
        self.tuned.append(frequency_mhz)
        return self.result


def make_main_window(logger, cpdlc_session, message_manager, config=None, simconnect=None):
    """Build a MainWindow whose wx.Frame half is never initialised.

    MainWindow.__init__ opens dialogs, loads sounds and starts an update check,
    none of which a unit test should trigger. Allocating the instance and wiring
    only the collaborators the message path touches lets the real
    _on_message_received / _on_acknowledge_message code run unmodified.

    Args:
        logger: Test logger
        cpdlc_session: The CpdlcSession the window should drive
        message_manager: The MessageManager the window should fill
        config: Overrides written to the (isolated) config file, so the
            window's own load_config() calls see them. None leaves the
            defaults in place.
        simconnect: A FakeSimConnectManager; a fresh one when None
    """
    from src.gui.main_window import MainWindow

    if config is not None:
        assert save_config({**DEFAULT_CONFIG, **config}), "could not write test config"

    window = MainWindow.__new__(MainWindow)
    window.logger = logger
    window.cpdlc_session = cpdlc_session
    window.message_manager = message_manager
    window.message_view = RecordingMessageView()
    window.polling_controller = FakePollingController()
    window.simconnect_manager = (
        simconnect if simconnect is not None else FakeSimConnectManager()
    )
    window.new_message_sound = None
    window.status_texts = []
    # Instance attribute shadows wx.Frame.SetStatusText, which would need a
    # live C++ frame behind it.
    window.SetStatusText = window.status_texts.append
    return window
```

- [ ] **Step 2: Cut `tests/conftest.py` down to fixtures**

Replace the whole file with:

```python
"""Shared fixtures for the sim-cpdlc test suite.

Helpers and test doubles live in tests/support.py; this file holds fixtures
only.
"""

import logging

import pytest
import wx


@pytest.fixture
def logger():
    """A real logger that discards output, so log calls are exercised but silent."""
    log = logging.getLogger("sim-cpdlc-tests")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


@pytest.fixture
def wx_app():
    """A wx application context.

    Torn down rather than shared, because wx allows only one live App at a
    time and a leaked one would break whichever test ran next.
    """
    app = wx.App()
    yield app
    # Destroy() only queues a window for deletion; without a yield the whole
    # object graph behind it -- and for a MainWindow that means a weather
    # monitor, a SimConnect manager and an update checker -- stays alive for
    # the rest of the session.
    wx.SafeYield()
    app.Destroy()


@pytest.fixture
def frame(wx_app):
    """A top-level window to parent dialogs and timers onto."""
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()
```

- [ ] **Step 3: Switch the eight import lines**

In each file replace the `from conftest import ...` line with the same names from `tests.support`:

```python
# tests/test_acknowledge_path.py
from tests.support import FakeConnectionManager, make_main_window, uplink
# tests/test_cpdlc_session.py
from tests.support import FakeConnectionManager
# tests/test_downlink_requests.py
from tests.support import FakeConnectionManager
# tests/test_logon_status.py
from tests.support import FakeConnectionManager, make_main_window, uplink
# tests/test_main_window_wiring.py
from tests.support import FakeConnectionManager, uplink
# tests/test_message_manager.py
from tests.support import uplink
# tests/test_message_view.py
from tests.support import uplink
# tests/test_polling_controller.py
from tests.support import FakeConnectionManager, uplink
```

- [ ] **Step 4: Run the suite and confirm nothing imports `conftest` any more**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `135 passed`

Run: `grep -rn "from conftest" tests`
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add tests/support.py tests/conftest.py tests/test_acknowledge_path.py tests/test_cpdlc_session.py tests/test_downlink_requests.py tests/test_logon_status.py tests/test_main_window_wiring.py tests/test_message_manager.py tests/test_message_view.py tests/test_polling_controller.py
git commit -m "Move the test doubles out of conftest into tests/support.py

conftest.py is for fixtures; importing helpers from it only works under
pytest's default import mode. The doubles also grow what later tests need:
uplink() takes an MRN, FakeConnectionManager can raise on send and records
telexes, and make_main_window wires a fake SimConnect manager and an
optional config.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Hermetic autouse fixtures

**Files:**
- Create: `tests/test_harness.py`
- Modify: `tests/conftest.py` (add fixtures, leak assertion)
- Modify: `tests/test_main_window.py:43-71` (the `window` fixture)

**Interfaces:**
- Consumes: `tests.support` from Task 1.
- Produces (fixtures available to every test):
  - `isolated_config` (autouse) -> `str` path of the per-test config file; `src.config.CONFIG_FILE` points at it
  - `no_network` (autouse): `requests.get`, `requests.post`, `webbrowser.open` raise `RuntimeError("network access in a test")`
  - `no_simbrief` (autouse) -> `list` of SimBrief user ids the dialogs asked for; lookups return `None`
  - `message_boxes` (autouse) -> recorder with `.calls` (list of `(message, caption, style)`), `.captions`, `.answer` (default `wx.YES`)
  - `build_window()` factory fixture in `tests/test_main_window.py` returning a real, hidden `MainWindow`; `window` fixture built from it

- [ ] **Step 1: Write the failing harness tests**

Create `tests/test_harness.py`:

```python
"""The hermetic fixtures: nothing a test builds may reach outside the test.

Every fixture checked here is autouse, so these tests document guarantees the
whole suite relies on.
"""

import webbrowser
from pathlib import Path

import pytest
import requests
import wx

from src import config as config_module
from src.config import DEFAULT_CONFIG, load_config, save_config
from src.gui.dialogs import ConnectDialog


def test_the_config_file_is_a_temporary_one(isolated_config, tmp_path):
    assert Path(config_module.CONFIG_FILE) == tmp_path / "config.json"
    assert Path(isolated_config) == tmp_path / "config.json"


def test_saving_the_config_writes_only_the_temporary_file(isolated_config):
    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "42"}) is True

    assert Path(isolated_config).exists()
    assert load_config()["simbrief_userid"] == "42"


def test_network_access_is_refused():
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.get("https://example.invalid/")
    with pytest.raises(RuntimeError, match="network access in a test"):
        requests.post("https://example.invalid/")


def test_opening_a_browser_is_refused():
    with pytest.raises(RuntimeError, match="network access in a test"):
        webbrowser.open("https://example.invalid/")


def test_message_boxes_are_recorded_and_answered_without_showing(message_boxes):
    message_boxes.answer = wx.NO

    assert wx.MessageBox("Sure?", "Confirm", wx.YES_NO) == wx.NO
    assert message_boxes.calls == [("Sure?", "Confirm", wx.YES_NO)]
    assert message_boxes.captions == ["Confirm"]


def test_the_connect_dialog_never_reaches_simbrief(frame, no_simbrief, message_boxes):
    """With a SimBrief id configured the dialog fetches the flight plan in its
    constructor and warns when that fails; both must stay inside the test."""
    save_config({**DEFAULT_CONFIG, "simbrief_userid": "189007"})

    dialog = ConnectDialog(frame)
    try:
        assert no_simbrief == ["189007"]
        assert message_boxes.captions == ["SimBrief"]
    finally:
        dialog.Destroy()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_harness.py -q -p no:cacheprovider`
Expected: errors of the form `fixture 'isolated_config' not found` / `fixture 'message_boxes' not found` / `fixture 'no_simbrief' not found`, and `test_network_access_is_refused` failing because a real `requests.ConnectionError` (not `RuntimeError`) is raised.

- [ ] **Step 3: Add the fixtures to `tests/conftest.py`**

Replace the file with:

```python
"""Shared fixtures for the sim-cpdlc test suite.

Helpers and test doubles live in tests/support.py; this file holds fixtures
only. The autouse fixtures make the suite hermetic: whatever a test builds, it
cannot read or write the real configuration file, reach the network, call
SimBrief or block on a message box.
"""

import logging
import webbrowser

import pytest
import requests
import wx

from src import config as config_module


@pytest.fixture
def logger():
    """A real logger that discards output, so log calls are exercised but silent."""
    log = logging.getLogger("sim-cpdlc-tests")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Point the configuration file at a per-test temporary path.

    load_config(), save_config() and MainWindow._check_first_launch() all read
    src.config.CONFIG_FILE at call time, so one patch covers every path that
    could otherwise touch the developer's real config.json.

    Returns:
        str: Path of the isolated config file, which may not exist yet.
    """
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", str(path))
    return str(path)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Refuse every outbound request a test did not explicitly fake.

    Tests that need HTTP install their own fake over these (see serving() in
    test_connection_manager.py); a test's own monkeypatch runs after this one.
    """

    def refuse(*args, **kwargs):
        raise RuntimeError("network access in a test")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(webbrowser, "open", refuse)


@pytest.fixture(autouse=True)
def no_simbrief(monkeypatch):
    """Answer every SimBrief lookup with "no flight plan", recording the ids asked for.

    The Connect and PDC dialogs import get_latest_ofp by name, so the patch
    lands on each dialog module rather than on src.utils.simbrief.

    Returns:
        list: The SimBrief user ids the dialogs asked for.
    """
    asked = []

    def fake(user_id):
        asked.append(user_id)
        return None

    monkeypatch.setattr("src.gui.dialogs.connect_dialog.get_latest_ofp", fake)
    monkeypatch.setattr("src.gui.dialogs.pdc_dialog.get_latest_ofp", fake)
    return asked


class MessageBoxes:
    """Records wx.MessageBox calls and answers them without showing anything."""

    def __init__(self):
        self.calls = []
        self.answer = wx.YES

    def __call__(self, message, caption="Message", style=wx.OK, *args, **kwargs):
        self.calls.append((message, caption, style))
        return self.answer

    @property
    def captions(self):
        return [caption for _, caption, _ in self.calls]


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch):
    """Replace wx.MessageBox with a recorder so no test can block on a modal.

    Every module calls it as wx.MessageBox, so patching the wx module attribute
    covers them all. Set .answer to wx.NO to take the cancel branch of a
    confirmation.
    """
    recorder = MessageBoxes()
    monkeypatch.setattr(wx, "MessageBox", recorder)
    return recorder


@pytest.fixture
def wx_app():
    """A wx application context.

    Torn down rather than shared, because wx allows only one live App at a
    time and a leaked one would break whichever test ran next.
    """
    app = wx.App()
    yield app
    # Destroy() only queues a window for deletion; without a yield the whole
    # object graph behind it -- and for a MainWindow that means a weather
    # monitor, a SimConnect manager and an update checker -- stays alive for
    # the rest of the session.
    wx.SafeYield()
    leaked = [type(window).__name__ for window in wx.GetTopLevelWindows()]
    app.Destroy()
    assert leaked == [], f"top-level windows leaked by this test: {leaked}"


@pytest.fixture
def frame(wx_app):
    """A top-level window to parent dialogs and timers onto."""
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()
```

- [ ] **Step 4: Rebuild the `window` fixture in `tests/test_main_window.py` on the new fixtures**

Replace lines 43-71 (the `window` fixture and its docstring) with:

```python
@pytest.fixture
def build_window(logger, wx_app, isolated_config, message_boxes):
    """A factory for the real window, kept offline and non-modal.

    The isolated config file is written first, so _check_first_launch() finds
    it and shows no welcome dialog, and the update check is switched off so no
    background thread starts. Every window built here is destroyed at teardown.
    """
    built = []

    def build():
        assert save_config({**DEFAULT_CONFIG, "auto_check_updates": False})
        window = mw.MainWindow(None, "Sim-CPDLC test", logger)
        window.Hide()
        built.append(window)
        return window

    yield build
    for window in built:
        window.weather_monitor.clear()
        window.weather_monitor.shutdown()
        window.Destroy()


@pytest.fixture
def window(build_window):
    return build_window()
```

and change the import at line 15 to `from src.config import DEFAULT_CONFIG, save_config`.

- [ ] **Step 5: Run the harness tests and the full suite**

Run: `$PY -m pytest tests/test_harness.py -q -p no:cacheprovider`
Expected: `6 passed`

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `141 passed` (135 + 6), no teardown errors from the leak assertion.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_harness.py tests/test_main_window.py
git commit -m "Make the test suite hermetic

Four autouse fixtures now stand between every test and the outside world:
the config file is a per-test temporary path, requests and webbrowser
refuse to run, SimBrief lookups answer with no flight plan, and
wx.MessageBox is a recorder. The wx_app fixture also fails any test that
leaks a top-level window. The main-window fixture builds on these instead
of patching load_config and MessageBox itself.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Per-test timeouts and the CI job timeout

**Files:**
- Modify: `requirements-dev.txt`
- Modify: `pytest.ini`
- Modify: `.github/workflows/tests.yml:9-13`
- Modify: `tests/test_connection_manager.py:408-438`

**Interfaces:**
- Produces: a 60 s per-test timeout for the whole suite; a 15 minute cap on the CI job.

- [ ] **Step 1: Install pytest-timeout into the venv and pin it**

Run: `$PY -m pip install pytest-timeout==2.4.0`
Then set `requirements-dev.txt` to:

```
-r requirements.txt
pytest==9.1.1
pytest-timeout==2.4.0
```

If pip reports that 2.4.0 does not exist, install `pytest-timeout` unpinned, read the installed version with `$PY -m pip show pytest-timeout`, and pin that.

- [ ] **Step 2: Configure the timeout**

`pytest.ini`:

```ini
[pytest]
# Scoped to tests/ deliberately: src/utils/test_simbrief.py is a manual script
# that calls the live SimBrief API, and pytest would otherwise collect it.
testpaths = tests
pythonpath = .
# A test that blocks on a real dialog or a real network call must fail, not
# hang the run.
timeout = 60
```

`.github/workflows/tests.yml`, inside the `test` job after `runs-on`:

```yaml
    runs-on: windows-latest
    timeout-minutes: 15
```

- [ ] **Step 3: Make the two timeout tests patch `requests.post` as well**

In `tests/test_connection_manager.py` replace both tests at the end of the file with:

```python
def test_install_request_timeout_supplies_a_default(monkeypatch):
    """hoppie_connector passes no timeout and offers no hook to supply one, so
    a server that accepts the connection and goes silent blocked forever.
    socket.setdefaulttimeout() does not help: requests explicitly calls
    sock.settimeout(None) when given no timeout."""
    seen = {}

    def _request(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", _request)
    monkeypatch.setattr(requests, "post", _request)
    install_request_timeout(7)

    requests.get("https://example.invalid/")
    assert seen["timeout"] == 7

    seen.clear()
    requests.post("https://example.invalid/")
    assert seen["timeout"] == 7


def test_an_explicit_timeout_still_wins(monkeypatch):
    seen = {}

    def _request(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", _request)
    monkeypatch.setattr(requests, "post", _request)
    install_request_timeout(7)

    requests.get("https://example.invalid/", timeout=1)

    assert seen["timeout"] == 1
```

- [ ] **Step 4: Verify the plugin is active and the suite is green**

Run: `$PY -m pytest -p no:cacheprovider tests/test_config.py`
Expected: the header contains `timeout: 60.0s`, tests pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `141 passed`

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt pytest.ini .github/workflows/tests.yml tests/test_connection_manager.py
git commit -m "Give every test a 60 s timeout and the CI job a 15 minute cap

An unstubbed dialog or a real network call used to hang the run for
GitHub's six-hour default. The two request-timeout tests also patch
requests.post now, so install_request_timeout no longer leaves a wrapper
on the real post for the rest of the session.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The acknowledgement frame, in full

**Files:**
- Modify: `tests/test_acknowledge_path.py:21-28`
- Modify: `tests/test_connection_manager.py` (imports at line 17; new test in the "information requests" area or at the end)

**Interfaces:**
- Consumes: `make_main_window`, `uplink`, `FakeConnectionManager` from `tests.support`; `connected()`, `FakeResponse` already in `test_connection_manager.py`.

- [ ] **Step 1: Replace the weak acknowledgement test and add the MIN test**

In `tests/test_acknowledge_path.py` add `from hoppie_connector import CpdlcResponseRequirement as RR` to the imports and replace `test_wilco_is_sent_with_the_senders_own_min_as_mrn` with:

```python
def test_wilco_is_a_complete_response_frame(logger):
    """Recipient, own MIN, response requirement "N", text and the uplink's MIN
    as MRN. TODOS item 21: acknowledgements once went out as "NE", which some
    ATC clients ignore, and nothing asserted the requirement."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]


def test_each_acknowledgement_uses_the_next_own_min(logger):
    window, manager, connection = build(logger)
    first = manager.add_message(uplink(STATION, 53))
    second = manager.add_message(uplink(STATION, 54, "DESCEND TO AND MAINTAIN FL240"))

    window._on_acknowledge_message(first, "WILCO")
    window._on_acknowledge_message(second, "UNABLE")

    assert [(frame[1], frame[3], frame[4]) for frame in connection.sent] == [
        (1, "WILCO", 53),
        (2, "UNABLE", 54),
    ]
```

- [ ] **Step 2: Add the wire-level test to `tests/test_connection_manager.py`**

Change the import at line 17 to `from hoppie_connector import CpdlcResponseRequirement as RR, HoppieConnector, HoppieError` and add, after `test_a_rejected_message_is_not_counted_as_a_link_failure`:

```python
def test_an_acknowledgement_is_transmitted_as_data2_min_mrn_n_text(logger, monkeypatch):
    """The literal packet the station's client parses. Built by the real
    hoppie_connector, captured at the HTTP boundary."""
    seen = {}

    def _get(url, params=None, **kwargs):
        seen.update(params or {})
        return FakeResponse("ok")

    cm = connected(logger, monkeypatch)
    monkeypatch.setattr(requests, "get", _get)

    cm.send_cpdlc("LSAG", 1, RR.NO.value, "WILCO", mrn=53)

    assert seen["packet"] == "/data2/1/53/N/WILCO"
    assert (seen["to"], seen["type"], seen["from"]) == ("LSAG", "cpdlc", "DLH123")
```

- [ ] **Step 3: Run the new tests**

Run: `$PY -m pytest tests/test_acknowledge_path.py tests/test_connection_manager.py -q -p no:cacheprovider`
Expected: all pass (these pin current behaviour).

- [ ] **Step 4: Mutation check: prove the test guards the requirement code**

Edit `src/model/cpdlc_session.py` line 230 from `RR.NO.value,` to `RR.NOT_REQUIRED.value,` and run:

`$PY -m pytest tests/test_acknowledge_path.py -q -p no:cacheprovider`
Expected: `test_wilco_is_a_complete_response_frame` FAILS showing `'NE'` where `'N'` was expected.

Revert: `git checkout -- src/model/cpdlc_session.py`, rerun, expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_acknowledge_path.py tests/test_connection_manager.py
git commit -m "Assert the whole acknowledgement frame, down to the wire packet

The end-to-end test discarded the response requirement and the own MIN it
was written to protect, so reverting TODOS item 21 passed the suite.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: MRN validation and the response table

**Files:**
- Modify: `tests/test_cpdlc_session.py` (append)
- Modify: `tests/test_logon_status.py:15-16` and append
- Modify: `tests/test_message_manager.py` (append; add `import pytest`)

**Interfaces:**
- Consumes: `uplink(..., mrn=...)` from Task 1.

- [ ] **Step 1: Session-level MRN test**

Append to `tests/test_cpdlc_session.py`:

```python
def test_logon_accepted_with_a_different_mrn_is_rejected(logger):
    """TODOS item 24: the MRN must reference our REQUEST LOGON, which always
    carries MIN 1 because logon() restarts the counter."""
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDDF")

    accepted = session.handle_logon_accepted("EDDF", mrn=2)

    assert accepted is False
    assert session.get_current_station() == ""
```

- [ ] **Step 2: Fix the helper in `tests/test_logon_status.py` and add the window-level test**

Replace lines 15-16 with:

```python
def _logon_accepted_from(station, mrn):
    """A real acceptance: the station's own MIN 1, referencing our MIN as MRN.
    All 388 LOGON ACCEPTED uplinks in six months of logs carried an MRN."""
    return uplink(station, 1, text="LOGON ACCEPTED", rr=RR.NOT_REQUIRED, mrn=mrn)
```

Append:

```python
def test_status_bar_is_silent_when_the_mrn_does_not_match(logger):
    session = CpdlcSession(logger, FakeConnectionManager())
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_message_received(_logon_accepted_from("EDDF", 2))

    assert window.status_texts == []
    assert session.get_current_station() == ""
```

- [ ] **Step 3: The response table**

Append to `tests/test_message_manager.py` (add `import pytest` at the top):

```python
RESPONSE_TABLE = [
    (RR.WILCO_UNABLE, ["WILCO", "UNABLE", "STANDBY"]),
    (RR.AFFIRM_NEGATIVE, ["AFFIRM", "NEGATIVE", "STANDBY"]),
    (RR.ROGER, ["ROGER", "STANDBY"]),
    (RR.YES, ["YES", "NO"]),
    (RR.NO, []),
    (RR.NOT_REQUIRED, []),
]


def test_the_response_table_covers_every_requirement_code():
    assert {rr for rr, _ in RESPONSE_TABLE} == set(RR)


@pytest.mark.parametrize("rr, expected", RESPONSE_TABLE, ids=[rr.name for rr, _ in RESPONSE_TABLE])
def test_the_responses_offered_for_each_requirement_code(logger, rr, expected):
    """TODOS item 22: "Y" once offered only YES, and "N" wrongly offered NO."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink(STATION, 9, "CONFIRM SQUAWK", rr=rr))

    assert manager.needs_acknowledgement(message_id, STATION) == (bool(expected), expected)
```

- [ ] **Step 4: Run the three files**

Run: `$PY -m pytest tests/test_cpdlc_session.py tests/test_logon_status.py tests/test_message_manager.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Mutation check**

Edit `src/model/cpdlc_session.py` line 428: change `if mrn != self.pending_logon_min:` to `if False:`. Run the three files again. Expected: `test_logon_accepted_with_a_different_mrn_is_rejected` and `test_status_bar_is_silent_when_the_mrn_does_not_match` FAIL. Revert with `git checkout -- src/model/cpdlc_session.py` and rerun: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_cpdlc_session.py tests/test_logon_status.py tests/test_message_manager.py
git commit -m "Pin the MRN check on LOGON ACCEPTED and the whole response table

The helper named after the MRN never set one, so the rejecting branch was
unreachable from the tests, and three of the six response-requirement
rows had no test at all.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Every downlink, literally, and every failure path

**Files:**
- Modify: `tests/test_downlink_requests.py` (imports and append)

**Interfaces:**
- Consumes: `FakeConnectionManager(raise_with=...)`, `.telexes` from Task 1; `make_session`/`session` fixtures already in the file (`STATION = "EGGX"`, callsign `BAW123`).

- [ ] **Step 1: Add the tests**

Change the imports at the top of `tests/test_downlink_requests.py` to:

```python
import pytest
from hoppie_connector import HoppieError

from tests.support import FakeConnectionManager
from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER
from src.model.cpdlc_session import CpdlcSession
```

Append:

```python
# --- the remaining downlinks --------------------------------------------------


def test_a_logon_request_uses_min_one_and_expects_an_answer(make_session):
    session = make_session(station="")

    assert session.logon("EGGX") == (True, "REQUEST LOGON")
    assert session.connection_manager.sent == [("EGGX", 1, "Y", "REQUEST LOGON", None)]
    assert (session.pending_logon_station, session.pending_logon_min) == ("EGGX", 1)


def test_a_logoff_needs_no_response_and_clears_the_station(session):
    assert session.logoff() == (True, "LOGOFF")
    assert session.connection_manager.sent == [(STATION, 1, "NE", "LOGOFF", None)]
    assert session.get_current_station() == ""


@pytest.mark.parametrize(
    "speed, is_mach, reason, expected",
    [
        ("082", True, None, "REQUEST M082"),
        ("300", False, None, "REQUEST 300K"),
        ("078", True, REASON_WEATHER, "REQUEST M078 DUE TO WEATHER"),
    ],
    ids=["mach", "knots", "mach-with-reason"],
)
def test_a_speed_request_names_mach_or_knots(session, speed, is_mach, reason, expected):
    assert session.send_speed_request(speed, is_mach, reason) == (True, expected)


def test_a_when_can_we_expect_inquiry_is_sent_verbatim(session):
    text = "WHEN CAN WE EXPECT HIGHER LEVEL"

    assert session.send_when_can_we_expect(text) == (True, text)


def test_every_request_goes_to_the_current_station_expecting_an_answer(session):
    session.send_altitude_change_request("FL350")
    session.send_direct_request("MALOT")
    session.send_speed_request("082", True)
    session.send_when_can_we_expect("WHEN CAN WE EXPECT LOWER LEVEL")

    frames = session.connection_manager.sent
    assert [frame[0] for frame in frames] == [STATION] * 4
    assert [frame[2] for frame in frames] == ["Y"] * 4
    assert [frame[1] for frame in frames] == [1, 2, 3, 4]


def test_a_telex_goes_to_its_recipient_unchanged(session):
    assert session.send_telex("EDDF", "HELLO THERE") == (True, "HELLO THERE")
    assert session.connection_manager.telexes == [("EDDF", "HELLO THERE")]


def test_a_pdc_request_is_a_telex_to_the_departure_airport(session):
    ok, text = session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K")

    assert ok is True
    assert text == "REQUEST PREDEP CLEARANCE BAW123 A339 TO LIMC AT EGLL STAND 521 ATIS K"
    assert session.connection_manager.telexes == [("EGLL", text)]


def test_a_pdc_request_needs_a_callsign(make_session):
    session = make_session()
    session.set_callsign("")

    assert session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K") == (False, None)


# --- failure paths ------------------------------------------------------------

SENDS = [
    ("logon", lambda s: s.logon("EGGX")),
    ("logoff", lambda s: s.logoff()),
    ("altitude", lambda s: s.send_altitude_change_request("FL350")),
    ("direct", lambda s: s.send_direct_request("MALOT")),
    ("speed", lambda s: s.send_speed_request("082", True)),
    ("when-can-we", lambda s: s.send_when_can_we_expect("WHEN CAN WE EXPECT HIGHER LEVEL")),
    ("acknowledgement", lambda s: s.send_acknowledgement(STATION, 7, "WILCO")),
    ("telex", lambda s: s.send_telex("EDDF", "HELLO")),
    ("pdc", lambda s: s.send_pdc_request("EGLL", "LIMC", "A339", "521", "K")),
]


@pytest.mark.parametrize("send", [case[1] for case in SENDS], ids=[case[0] for case in SENDS])
def test_a_transmission_failure_is_reported_and_consumes_no_min(logger, send):
    """The error text reaches the dialog, and the MIN is not spent, so the
    next successful send does not leave a gap the station has to explain."""
    session = CpdlcSession(logger, FakeConnectionManager(raise_with=HoppieError("boom")))
    session.set_callsign("BAW123")
    session.current_station = STATION

    assert send(session) == (False, "boom")
    assert session.cpdlc_min_counter == 1
```

- [ ] **Step 2: Run the file**

Run: `$PY -m pytest tests/test_downlink_requests.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_downlink_requests.py
git commit -m "Assert every downlink text and every send failure path

Logon, logoff, speed, when-can-we, telex and PDC had no literal test, and
FakeConnectionManager could not fail, so ten error branches were dead to
the suite.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The uplink-handling branches of the main window

**Files:**
- Create: `tests/test_uplink_handling.py`

**Interfaces:**
- Consumes: `make_main_window(config=..., simconnect=...)`, `FakeSimConnectManager`, `FakeConnectionManager`, `uplink` from Task 1; `isolated_config` from Task 2 (so `config=` writes land in the temp file).

- [ ] **Step 1: Write the tests**

```python
"""How the window reacts to uplinks that change session state or tune the radio.

These drive MainWindow._on_message_received with the exact texts the two
networks send, taken from the maintainer's logs.
"""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR

from tests.support import (
    FakeConnectionManager,
    FakeSimConnectManager,
    make_main_window,
    uplink,
)
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

CURRENT = "EDYY"
OTHER = "EDUU"
CONTACT = "CONTACT MARSEILLE CONTROL ON @133.325@."


def build(logger, config=None, simconnect=None):
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection)
    session.set_callsign("DLH123")
    session.handle_logon_accepted(CURRENT)
    simconnect = simconnect if simconnect is not None else FakeSimConnectManager()
    window = make_main_window(
        logger, session, MessageManager(logger), config=config, simconnect=simconnect
    )
    return window, session, connection, simconnect


# --- handover -----------------------------------------------------------------


def test_a_handover_logs_off_and_requests_logon_with_the_next_station(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"
    assert connection.sent == [("EDGG", 1, RR.YES.value, "REQUEST LOGON", None)]
    assert window.status_texts == ["Logged off from EDYY.", "Pending logon to EDGG."]
    assert window.polling_controller.active_calls == 1


def test_a_handover_from_another_station_is_shown_but_not_acted_on(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(OTHER, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == CURRENT
    assert connection.sent == []
    assert window.status_texts == []
    assert len(window.message_view.added) == 1


# --- logoff -------------------------------------------------------------------


def test_a_logoff_from_the_current_station_ends_the_logon(logger):
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 5, "LOGOFF", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == ""
    assert window.status_texts == ["Logged off from EDYY."]


@pytest.mark.parametrize(
    "sender, text",
    [(OTHER, "LOGOFF"), (CURRENT, "LOGOFF NOT REQUIRED AT THIS TIME")],
    ids=["other-station", "not-an-exact-logoff"],
)
def test_other_logoff_texts_leave_the_logon_alone(logger, sender, text):
    """TODOS item 23: substring matching once logged off on the second text."""
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(sender, 5, text, rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == CURRENT
    assert window.status_texts == []


# --- protocol noise -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["CURRENT ATC UNIT@_@EDYY@_@MAASTRICHT RADAR", "CURRENT ATS UNIT@_@EDYY@_@MAASTRICHT RADAR"],
    ids=["atc", "ats"],
)
def test_current_unit_announcements_are_hidden(logger, text):
    window, _, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 2, text, rr=RR.NOT_REQUIRED))

    assert window.message_view.added == []
    assert window.message_manager.message_log == {}
    assert window.status_texts == []


# --- CONTACT / MONITOR auto-tune ----------------------------------------------


def test_a_contact_instruction_tunes_the_standby_radio(logger):
    window, _, _, simconnect = build(logger)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert window.status_texts == []


def test_auto_tune_can_be_switched_off(logger):
    window, _, _, simconnect = build(logger, config={"auto_tune_com1": False})

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == []


def test_a_failed_auto_tune_tells_the_pilot_the_frequency(logger):
    window, _, _, simconnect = build(logger, simconnect=FakeSimConnectManager(result=False))

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert window.status_texts == ["Auto-tune failed \u2014 set 133.325 manually"]


def test_a_contact_from_another_station_is_not_tuned(logger):
    window, _, _, simconnect = build(logger)

    window._on_message_received(uplink(OTHER, 7, CONTACT))

    assert simconnect.tuned == []
```

- [ ] **Step 2: Run the file**

Run: `$PY -m pytest tests/test_uplink_handling.py -q -p no:cacheprovider`
Expected: `10 passed`. If `test_auto_tune_can_be_switched_off` fails with the frequency tuned, the `config=` path is not reaching the isolated file: check that `make_main_window` calls `save_config` and that `isolated_config` is autouse.

- [ ] **Step 3: Commit**

```bash
git add tests/test_uplink_handling.py
git commit -m "Cover the handover, logoff, noise-filter and auto-tune branches

Only LOGON ACCEPTED had a test through the window. The handover branch is
the automatic re-logon to the next sector, and the auto-tune branch was
untestable because the fixture never set a SimConnect manager.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Menu items fire the handlers they claim to

**Files:**
- Modify: `tests/test_main_window.py:20-40` (constants), `:177-189` (replace the existence test, strengthen the guard test)

**Interfaces:**
- Consumes: `build_window` factory fixture from Task 2, `message_boxes` from Task 2.

- [ ] **Step 1: Replace the handler list with the binding table**

Replace lines 20-40 (`MENU_TITLES` and `MENU_HANDLERS`) with:

```python
MENU_TITLES = ["File", "Requests"]

# Which handler each menu item must fire. Every handler is replaced on the
# class before the window is built, so the Bind() calls in _init_menu pick up
# the recorders; posting the item's command event then shows which one ran.
MENU_BINDINGS = {
    "File": {
        "Connect": "on_connect_or_disconnect",
        "Settings": "on_settings",
        "Check for Updates": "on_check_updates",
        "About": "on_about",
        "Exit": "on_exit",
    },
    "Requests": {
        "PDC": "on_pdc_request",
        "Logon": "on_logon",
        "Logoff": "on_logoff",
        "Altitude change": "on_altitude_change",
        "Direct to": "on_direct_request",
        "Speed change": "on_speed_request",
        "When can we expect": "on_when_can_we_expect",
        "Telex message": "on_telex",
        "ATIS and Weather request": "on_weather_request",
        "Automatic weather updates": "on_weather_subscriptions",
    },
}
```

Add `import wx` to the imports.

- [ ] **Step 2: Replace `test_every_menu_item_has_a_handler` and strengthen the guard test**

Replace the two tests (`test_every_menu_item_has_a_handler` and `test_a_request_needing_a_connection_is_refused_while_disconnected`) with:

```python
def _recorder(name, fired):
    def handler(self, event):
        fired.append(name)

    return handler


def test_every_menu_item_fires_its_own_handler(build_window, monkeypatch):
    """A deleted or mis-targeted Bind() shows up as a dead or wrong menu item;
    checking that the methods merely exist could not see either."""
    fired = []
    for names in MENU_BINDINGS.values():
        for name in names.values():
            monkeypatch.setattr(mw.MainWindow, name, _recorder(name, fired))
    window = build_window()
    menu_bar = window.GetMenuBar()

    observed = {}
    for menu_index in range(menu_bar.GetMenuCount()):
        title = menu_bar.GetMenuLabel(menu_index).replace("&", "")
        for item in menu_bar.GetMenu(menu_index).GetMenuItems():
            if item.IsSeparator():
                continue
            fired.clear()
            window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, item.GetId()))
            observed.setdefault(title, {})[item.GetItemLabelText()] = (
                fired[0] if len(fired) == 1 else list(fired)
            )

    assert observed == MENU_BINDINGS


# --- guards -------------------------------------------------------------------


def test_a_request_needing_a_connection_is_refused_and_the_user_is_told(window, message_boxes):
    assert window._require_connection("test") is False
    assert message_boxes.captions == ["Not Connected"]
```

- [ ] **Step 3: Run the file**

Run: `$PY -m pytest tests/test_main_window.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 4: Mutation check**

Comment out line 227 of `src/gui/main_window.py` (`self.Bind(wx.EVT_MENU, self.on_altitude_change, menu_item_altitude_change)`) and rerun the file. Expected: `test_every_menu_item_fires_its_own_handler` FAILS with `"Altitude change": []` in the diff. Revert with `git checkout -- src/gui/main_window.py` and rerun: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_main_window.py
git commit -m "Drive every menu item and assert which handler it fires

The old test only checked that the handler methods existed, so a dropped
Bind() passed. The connection guard test now also checks the user was
told.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: The response context menu: its items, its firing, its cleanup

**Files:**
- Modify: `tests/test_message_view.py` (append)

**Interfaces:**
- Consumes: `uplink`, `panel` fixture already in the file (`STATION = "LSAG"`).

- [ ] **Step 1: Add the test**

Append to `tests/test_message_view.py`:

```python
def test_the_response_menu_offers_every_response_and_fires_the_chosen_one(panel, logger):
    """The menu is destroyed as soon as it closes, so its items are captured
    inside the fake PopupMenu; the second item is chosen from there. TODOS
    item 2: the per-item bindings must be gone once the menu has closed, or a
    reused id would fire a stale response."""
    manager = MessageManager(logger)
    acknowledged = []
    view = MessageView(
        panel, logger, manager, lambda mid, resp: acknowledged.append((mid, resp)), lambda: STATION
    )
    message_id = manager.add_message(uplink(STATION, 4))
    shown = {}

    def choose_second(menu):
        shown["labels"] = [item.GetItemLabelText() for item in menu.GetMenuItems()]
        shown["ids"] = [item.GetId() for item in menu.GetMenuItems()]
        panel.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, shown["ids"][1]))

    panel.PopupMenu = choose_second
    view.add_message(message_id)
    view.message_list.Select(0)

    view.on_context_menu(None)

    assert shown["labels"] == ["Respond: WILCO", "Respond: UNABLE", "Respond: STANDBY"]
    assert acknowledged == [(message_id, "UNABLE")]

    panel.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, shown["ids"][1]))
    assert acknowledged == [(message_id, "UNABLE")], "binding survived the menu"
```

- [ ] **Step 2: Run the file**

Run: `$PY -m pytest tests/test_message_view.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 3: Mutation check**

In `src/gui/message_view.py` comment out lines 168-169 (the `for menu_item in menu_items: self.parent.Unbind(...)` loop) and rerun. Expected: the new test FAILS at "binding survived the menu". Revert with `git checkout -- src/gui/message_view.py` and rerun: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_message_view.py
git commit -m "Assert the response menu's items, its firing and its cleanup

The existing test only checked that a menu popped. Now the labels, the
response the chosen item sends and the removal of the bindings afterwards
are all pinned.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: `load_config` and `save_config`

**Files:**
- Modify: `tests/test_config.py` (imports and append)

**Interfaces:**
- Consumes: `isolated_config` from Task 2.

- [ ] **Step 1: Add the tests**

Change the imports of `tests/test_config.py` to:

```python
import os
from pathlib import Path

from src.config import (
    DEFAULT_CONFIG,
    DEFAULT_WEATHER_INTERVAL_MINUTES,
    MAX_WEATHER_INTERVAL_MINUTES,
    MIN_WEATHER_INTERVAL_MINUTES,
    load_config,
    save_config,
    weather_interval_minutes,
)
```

Append:

```python
# --- reading and writing the file ---------------------------------------------


def test_a_missing_file_yields_a_fresh_copy_of_the_defaults():
    loaded = load_config()

    assert loaded == DEFAULT_CONFIG
    assert loaded is not DEFAULT_CONFIG


def test_missing_keys_are_filled_in_and_present_ones_kept(isolated_config):
    Path(isolated_config).write_text('{"hoppie_logon_code": "ABC"}')

    loaded = load_config()

    assert loaded["hoppie_logon_code"] == "ABC"
    assert set(loaded) == set(DEFAULT_CONFIG)


def test_invalid_json_yields_the_defaults(isolated_config):
    Path(isolated_config).write_text("{not json")

    assert load_config() == DEFAULT_CONFIG


def test_only_a_mapping_can_be_saved():
    assert save_config("nope") is False


def test_a_saved_config_round_trips():
    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "42"}) is True

    assert load_config()["simbrief_userid"] == "42"


def test_a_failed_write_leaves_the_previous_file_and_no_temp_file_behind(
    isolated_config, monkeypatch
):
    """TODOS item 5: the write is atomic. A PermissionError from os.replace is
    what Windows raises when the file is open elsewhere."""
    save_config({**DEFAULT_CONFIG, "simbrief_userid": "before"})

    def refuse(src, dst):
        raise PermissionError(13, "file in use", dst)

    monkeypatch.setattr(os, "replace", refuse)

    assert save_config({**DEFAULT_CONFIG, "simbrief_userid": "after"}) is False
    assert load_config()["simbrief_userid"] == "before"
    assert [path.name for path in Path(isolated_config).parent.iterdir()] == ["config.json"]
```

- [ ] **Step 2: Run the file**

Run: `$PY -m pytest tests/test_config.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_config.py
git commit -m "Test reading, writing and the atomic replace of the config file

These functions hold the logon codes and had no test beyond the interval
clamp.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Table tests for the two parsers

**Files:**
- Create: `tests/test_frequency_parser.py`
- Create: `tests/test_message_formatting.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Frequency parser table**

Create `tests/test_frequency_parser.py`:

```python
"""What extract_contact_frequency tunes, on the texts the networks send.

Texts are given as the window sees them: after "@" separators have been
turned into spaces and whitespace collapsed.
"""

import pytest

from src.utils.frequency_parser import extract_contact_frequency

CASES = [
    ("CONTACT MAASTRICHT 132.850", 132.85),
    ("CONTACT MARSEILLE CONTROL ON 133.325 .", 133.325),
    ("CONTACT MAASTRICHT ON 132.855 MHZ", 132.855),
    ("MONITOR UNICOM 122.8", 122.8),
    ("AT KONOL CONTACT LONDON CONTROL 127.425", 127.425),
    ("CONTACT MAASTRICHT 132.850 OR 121.500", 132.85),
    ("CONTACT EDDF_TWR 118.700", 118.7),
    ("CONTACT MAASTRICHT\n132.850", 132.85),
    ("CONTACT LOWER LIMIT 118.000", 118.0),
    ("CONTACT UPPER LIMIT 136.990", 136.99),
    ("CLIMB TO FL350 REPORT LEVEL", None),
    ("CONTACT RHEIN RADAR 136.995", None),
    ("CONTACT LANGEN RADAR 117.950", None),
    ("CONTACT UPPER LIMIT 137.000", None),
]


@pytest.mark.parametrize("text, expected", CASES, ids=[case[0][:32] for case in CASES])
def test_the_frequency_read_from_a_contact_or_monitor_instruction(text, expected):
    assert extract_contact_frequency(text) == expected
```

- [ ] **Step 2: Message formatting tables**

Create `tests/test_message_formatting.py`:

```python
"""The CPDLC packet-to-text helpers the list and the detail pane rely on."""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR

from src.utils.message_formatting import (
    extract_message_content,
    format_list_text,
    format_message_text,
)


@pytest.mark.parametrize("rr", list(RR), ids=[rr.name for rr in RR])
def test_the_packet_prefix_is_stripped_with_and_without_an_mrn(rr):
    assert extract_message_content(f"/data2/12//{rr.value}/CLIMB TO FL350") == "CLIMB TO FL350"
    assert extract_message_content(f"/data2/12/3/{rr.value}/WILCO") == "WILCO"


@pytest.mark.parametrize("text", ["CLIMB TO FL350", "", None], ids=["plain", "empty", "none"])
def test_text_without_a_prefix_is_returned_unchanged(text):
    assert extract_message_content(text) == text


def test_the_detail_pane_puts_each_field_on_its_own_line():
    assert format_message_text("CONTACT CLEVELAND CENTER ON @123.450@.") == (
        "CONTACT CLEVELAND CENTER ON\n123.450."
    )
    assert format_message_text("CURRENT ATC UNIT@_@EDUU@_@RHEIN RADAR") == (
        "CURRENT ATC UNIT\nEDUU\nRHEIN RADAR"
    )


def test_the_list_row_carries_no_separators():
    row = format_list_text("CONTACT CLEVELAND CENTER ON @123.450@.")

    assert "@" not in row
    assert "123.450" in row
    assert format_list_text("CURRENT ATC UNIT@_@EDUU@_@RHEIN RADAR").split() == [
        "CURRENT", "ATC", "UNIT", "EDUU", "RHEIN", "RADAR",
    ]
```

- [ ] **Step 3: Run both files**

Run: `$PY -m pytest tests/test_frequency_parser.py tests/test_message_formatting.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_frequency_parser.py tests/test_message_formatting.py
git commit -m "Add table tests for the frequency parser and the packet formatters

Neither module had a test. The parser decides what gets tuned into the
simulator radio; the formatters produce the text NVDA reads.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Regenerate `tests/README.md` and run the whole suite

**Files:**
- Modify: `tests/README.md`

- [ ] **Step 1: Rewrite the README**

```markdown
# Tests

Offline checks for the CPDLC request formats, the message handling in the
window, the automatic weather update logic and the main window wiring. They
need no network connection, no running simulator and no ACARS logon code, and
the fixtures in `conftest.py` make sure of it: every test gets a temporary
config file, outbound requests and browser launches raise, SimBrief lookups
answer with no flight plan, and `wx.MessageBox` is a recorder.

Run them from the repository root:

```bash
pip install -r requirements-dev.txt
pytest
```

The GUI tests build real wx windows, dialogs and timers, so they need a desktop
session; CI runs them on Windows for that reason. Each test is limited to 60
seconds.

Shared test doubles (`uplink`, `FakeConnectionManager`, `FakeSimConnectManager`,
`make_main_window`, ...) live in `support.py`; import them with
`from tests.support import ...`.

| File | Covers |
| --- | --- |
| `test_acknowledge_path.py` | Responding to an uplink, end to end from the window, down to the frame |
| `test_config.py` | Reading, writing and clamping the configuration |
| `test_connection_manager.py` | The network boundary: errors, timeouts, reconnection, the wire packets |
| `test_cpdlc_session.py` | Session state and logon acceptance validation, including the MRN check |
| `test_dialogs.py` | The validation the weather request dialog applies before submitting |
| `test_downlink_requests.py` | The exact text of every downlink the client can send, and every send failure |
| `test_frequency_parser.py` | Which CONTACT/MONITOR texts tune the standby radio |
| `test_harness.py` | The hermetic fixtures themselves |
| `test_logon_status.py` | Logon state as reported to the user |
| `test_main_window.py` | The real window: menu bindings, message list, weather toggles |
| `test_main_window_wiring.py` | `_init_ui` alone, on a stripped-down frame |
| `test_message_formatting.py` | Packet prefix stripping and the list and detail text |
| `test_message_manager.py` | Message storage, addressing and the full response table |
| `test_message_view.py` | The message list and its response context menu |
| `test_polling_controller.py` | Which messages speed up polling, and the poll intervals |
| `test_uplink_handling.py` | HANDOVER, LOGOFF, protocol noise and auto-tune through the window |
| `test_weather_monitor.py` | Weather change detection and the update timer lifecycle |
| `test_weather_parsing.py` | The report registry, the ATIS letter and the report formatters |

`test_downlink_requests.py` asserts message text literally, so a change to a
format shows up there before it reaches the network.
```

- [ ] **Step 2: Run the whole suite one last time and check the tree**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass, roughly 195 tests, no teardown errors.

Run: `git status --short`
Expected: only `tests/README.md` modified (nothing under `src/` touched).

- [ ] **Step 3: Commit**

```bash
git add tests/README.md
git commit -m "Regenerate the tests README for the hermetic suite

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec coverage (Package 1 section): fixtures `isolated_config`, `no_network`, `no_simbrief` (Task 2); leaked-window assertion (Task 2); helpers in `tests/support.py` with `uplink(mrn=)`, `raise_with`, `FakeSimConnectManager`, `make_main_window(config=, simconnect=)`, `message_boxes` (Tasks 1–2); `pytest-timeout`, `timeout-minutes`, `requests.post` in the timeout tests (Task 3); acknowledgement frame and wire packet (Task 4); MRN mismatch, response table (Task 5); every downlink and failure path (Task 6); HANDOVER, LOGOFF, noise filter, CONTACT branches (Task 7); menu binding via `ProcessEvent` (Task 8); context-menu labels, firing, no stale binding (Task 9); `load_config`/`save_config` including the atomic-write failure (Task 10); parser tables (Task 11); README regenerated (Task 12).
- Behaviour a later package changes (strict station scoping, `N/A` substitution, single reconnection attempt, unit-less CONTACT texts) is deliberately not pinned here.
- Names used across tasks: `tests.support` symbols are defined once in Task 1 and used unchanged; `isolated_config`, `message_boxes`, `no_simbrief`, `build_window` are defined in Task 2 and used in Tasks 7, 8 and 10.
