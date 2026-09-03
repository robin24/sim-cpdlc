# Package 3: Session and Protocol State — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app's idea of who it is talking to matches the network's, across handovers, disconnects and reconnects.

**Architecture:** `CpdlcSession` owns the dialogue state and gains a lifecycle (`reset`, `begin_session`), a handover window (`handle_handover`, `is_answerable_sender`), the logon's negative paths (`handle_logon_rejected`, `expire_pending`) and an injectable clock. Answerability becomes a predicate the session provides, which `MessageManager` and `MessageView` take instead of a station name. `MainWindow._on_message_received` handles session state only for `CpdlcMessage`, reads the library's accessors instead of re-parsing packets, and tunes the radio for any answerable sender. A `tick_callback` on `PollingController` lets the window give up on an unanswered logon. Connect, disconnect, exit and the fatal teardown all go through the session's lifecycle.

**Tech Stack:** Python 3.12+, wxPython 4.2.5, hoppie-connector 0.2.1, pytest 9.1.1 with pytest-timeout.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 260 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg3-session-state`, cut from `main` at `cb60a5a`, in the worktree `C:\Claude\sim-cpdlc\.claude\worktrees\pkg3-session-state`. Never touch `C:\Claude\sim-cpdlc` itself.
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog (the autouse fixtures in `tests/conftest.py` enforce this; keep using `tests.support` doubles).
- Files this package may change: `src/model/cpdlc_session.py`, `src/model/message_manager.py`, `src/gui/message_view.py`, `src/gui/main_window.py`, `src/controller/polling_controller.py`, `src/config.py`, and anything under `tests/`. Nothing else under `src/` changes.
- Exact values (from the spec): `PREVIOUS_STATION_WINDOW_SECONDS = 600` and `PENDING_LOGON_TIMEOUT_SECONDS = 600` in `src/config.py`. Status texts: `"Logged on to X."`, `"Logon to X rejected."`, `"Logon to X not answered."`, `"Logged off from X."`, `"Pending logon to X."`. SYSTEM rows: `"Logon to X rejected"`, `"Logon to X not answered"`, `"Could not send LOGOFF to X: <reason>"`. A logon while logged on sends `LOGOFF` (RR `NE`, the current MIN) and then `REQUEST LOGON` (RR `Y`, MIN 1). Time comes from `time.monotonic()` through the session's injectable `clock`.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 3" and the "Inputs" table (the handover race). Audit: `docs/audit/2026-09-03-codebase-audit.md` (M-1, M-7, L-2, L-3).

## Deviations from the spec (decided while planning; the spec's "Package 3" section is otherwise followed)

1. **A LOGOFF that cannot be sent aborts a manual logon** instead of being "returned as a warning" while the REQUEST LOGON goes out anyway. The old station must be told before the dialogue moves on (audit M-7 is exactly the state where it was not), and a link that has just failed a send would only fail the next one after another timeout. `logon()` returns `(False, "could not send LOGOFF to <old>: <reason>")`, which the existing "Failed to send logon request" dialog shows; the pilot retries once the link is back.
2. **The two strict-scoping tests stay.** `test_a_contact_from_another_station_is_not_tuned` and `test_a_handover_from_another_station_is_shown_but_not_acted_on` pin a rule the window keeps: a station that is neither current nor previous is not followed and not tuned. The window rule is added beside them, with the log's handover sequence.
3. **`on_disconnect` drops `wx.MilliSleep(500)` and the `set_active_polling()` before `stop()`.** Sends are synchronous, so the delay waited for nothing; a poll mode set one line before the timer stops does nothing either.
4. **`send_logoff_message` is removed.** It was an alias of `logoff()` "kept for backward compatibility" whose only callers were the two window paths this plan rewrites.
5. **An UNABLE counts as a rejection only from the pending station** with the pending MRN (the spec names only the MRN). A stale UNABLE from another station cannot cancel a logon.

## Design notes

- `reset()` forgets the dialogue (station, pending logon, handover window, MIN counter) but keeps the callsign and network: they identify the aircraft, and the rows the window adds after a disconnect still name it.
- A handover sends no LOGOFF to the old station (it ended the dialogue itself) and starts the new logon at MIN 1, exactly as today. What is new is that the old station's uplinks stay answerable for `PREVIOUS_STATION_WINDOW_SECONDS`.
- Interim limitation until package 4 paces sends: on SayIntentions, the LOGOFF and the REQUEST LOGON of a logon-while-logged-on go out back to back and the second may be answered `rate_limit`. The state is then consistent (logged off, nothing pending) and the pilot's retry succeeds.
- `pending_logon_at` and `previous_station_until` are clock readings, not wall-clock times; only differences are ever computed.

## File structure

| File | Responsibility after this plan |
|---|---|
| `src/model/cpdlc_session.py` | Dialogue state and lifecycle: `reset`, `begin_session`, LOGOFF-first `logon`, `handle_handover`, `is_answerable_sender`, `handle_logon_rejected`, `expire_pending`; injectable clock. |
| `src/model/message_manager.py` | `needs_acknowledgement` takes a sender predicate. |
| `src/gui/message_view.py` | Takes `is_answerable_sender` and hands it to the manager. |
| `src/gui/main_window.py` | `_on_message_received` split into `_protocol_text`, `_handle_session_uplink`, `_follow_handover`, `_auto_tune`; `_on_poll_tick`; `_end_dialogue` shared by disconnect and exit; `begin_session` on connect; `reset()` on the fatal path. |
| `src/controller/polling_controller.py` | `tick_callback` run at the end of every tick. |
| `src/config.py` | `PREVIOUS_STATION_WINDOW_SECONDS`, `PENDING_LOGON_TIMEOUT_SECONDS`. |
| `tests/support.py` | `FakeClock`, `answerable()`, `FakeCloseEvent`; `FakeConnectionManager.connect()`, `FakePollingController.start()`, `FakeWeatherMonitor.shutdown()`. |
| `tests/test_cpdlc_session.py`, `tests/test_uplink_handling.py`, `tests/test_logon_status.py`, `tests/test_polling_controller.py`, `tests/test_message_manager.py`, `tests/test_message_view.py`, `tests/test_main_window_wiring.py`, `tests/test_main_window.py`, `tests/test_acknowledge_path.py`, `tests/test_downlink_requests.py`, `tests/test_link_status.py` | Updated for the new interfaces and behaviour. |
| `tests/test_session_lifecycle.py` (new) | Where the dialogue ends: disconnect, exit, a rejected logon code; and that a lost link is not one. |
| `tests/README.md` | One new row, four reworded. |

---

### Task 1: Session lifecycle — `reset()`, `begin_session()`, a clock, and LOGOFF before a new logon

**Files:**
- Modify: `src/model/cpdlc_session.py:1-60` (imports, class docstring, `__init__`, replace `set_callsign` with `reset`/`begin_session`/`_clear_pending`), `:62-141` (`logon`, `logoff`), `:433-437` (`handle_logon_accepted` uses `_clear_pending`)
- Modify: `tests/support.py` (add `FakeClock` after `FakeCallLater`)
- Modify: `tests/test_cpdlc_session.py` (imports, `build()` helper, new tests)
- Modify: `tests/test_downlink_requests.py:18-26, 151-182`, `tests/test_acknowledge_path.py:16`, `tests/test_link_status.py:19`, `tests/test_uplink_handling.py:27` (`set_callsign` is gone)

**Interfaces:**
- Consumes: `FakeConnectionManager(connected=True, raise_with=None)` from `tests/support.py`, recording sends as `(recipient, min, rr, text, mrn)` tuples.
- Produces (used by every later task):
  - `CpdlcSession(logger, connection_manager, clock=time.monotonic)`; `session.clock` is the callable given.
  - `reset() -> None`: `current_station = ""`, `cpdlc_min_counter = 1`, pending logon cleared; callsign and network untouched.
  - `begin_session(callsign: str, network: str | None) -> None`: calls `reset()` when either differs from the stored identity, then stores both. Replaces `set_callsign`.
  - Fields `network` (None until `begin_session`), `pending_logon_at` (clock reading when the REQUEST LOGON went out, None otherwise).
  - `logon(station)`: if a station is logged on, sends LOGOFF first; on its failure returns `(False, "could not send LOGOFF to <old>: <reason>")` and sends nothing else.
  - `logoff()` clears the pending logon as well as the station.
  - `FakeClock(now=1000.0)`: callable returning `now`; `advance(seconds)`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, add after the `FakeCallLater` class:

```python
class FakeClock:
    """A monotonic clock the test moves by hand, for the session's time windows.

    Args:
        now: The starting reading, in seconds
    """

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
```

Replace the header of `tests/test_cpdlc_session.py` (the docstring and the two imports, lines 1-4) with:

```python
"""Tests for CPDLC session state: logon validation, lifecycle and the handover window."""

from hoppie_connector import HoppieError

from src.model.cpdlc_session import CpdlcSession
from tests.support import FakeClock, FakeConnectionManager


def build(logger, connection=None):
    """A session with a hand-driven clock, identified as DLH123 on Hoppie."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock())
    session.begin_session("DLH123", "hoppie")
    return session
```

Leave the five existing tests as they are and append:

```python
# --- lifecycle ----------------------------------------------------------------


def test_reset_forgets_the_dialogue_but_not_the_identity(logger):
    session = build(logger)
    session.logon("EDGG")
    session.handle_logon_accepted("EDGG", mrn=1)
    session.send_altitude_change_request("FL350")

    session.reset()

    assert session.get_current_station() == ""
    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)
    assert session.cpdlc_min_counter == 1
    assert session.get_callsign() == "DLH123"


def test_reset_clears_a_pending_logon(logger):
    session = build(logger)
    session.logon("EDGG")

    session.reset()

    assert (
        session.pending_logon_station,
        session.pending_logon_min,
        session.pending_logon_at,
    ) == (None, None, None)


def test_a_new_session_under_the_same_identity_keeps_the_logon(logger):
    """Decision 4 of the design: the network holds the ATC logon by callsign,
    so reconnecting as the same aircraft must not pretend it is gone."""
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("DLH123", "hoppie")

    assert session.get_current_station() == "EDGG"


def test_a_new_session_under_another_callsign_starts_clean(logger):
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("BAW123", "hoppie")

    assert session.get_current_station() == ""
    assert session.get_callsign() == "BAW123"


def test_a_new_session_on_another_network_starts_clean(logger):
    session = build(logger)
    session.handle_logon_accepted("EDGG")

    session.begin_session("DLH123", "sayintentions")

    assert session.get_current_station() == ""
    assert session.network == "sayintentions"


def test_a_logon_request_records_when_it_was_sent(logger):
    session = build(logger)
    session.clock.now = 1234.0

    session.logon("EDGG")

    assert session.pending_logon_at == 1234.0


# --- logon while logged on (audit M-7) ----------------------------------------


def test_logging_on_while_logged_on_sends_logoff_first(logger):
    """Audit M-7: without the LOGOFF the old station was never told, and the
    MIN restarted on a dialogue it still considered open."""
    session = build(logger)
    session.handle_logon_accepted("EDYY")
    session.send_altitude_change_request("FL350")  # MIN 1 spent

    result = session.logon("EDGG")

    assert result == (True, "REQUEST LOGON")
    assert session.connection_manager.sent[1:] == [
        ("EDYY", 2, "NE", "LOGOFF", None),
        ("EDGG", 1, "Y", "REQUEST LOGON", None),
    ]
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"


def test_relogging_on_to_the_same_station_closes_the_dialogue_first(logger):
    session = build(logger)
    session.handle_logon_accepted("EDYY")

    session.logon("EDYY")

    assert [frame[3] for frame in session.connection_manager.sent] == ["LOGOFF", "REQUEST LOGON"]
    assert session.pending_logon_station == "EDYY"


def test_a_failed_logoff_aborts_the_new_logon(logger):
    """The old station must be told before the dialogue moves on, and a link
    that has just failed would only fail again; the pilot retries instead."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    session = build(logger, connection)
    session.handle_logon_accepted("EDYY")

    result = session.logon("EDGG")

    assert result == (False, "could not send LOGOFF to EDYY: timed out")
    assert session.get_current_station() == "EDYY"
    assert session.pending_logon_station is None
    assert connection.sent == []


def test_logoff_clears_a_pending_logon(logger):
    """State an earlier build could leave behind: logged on and pending."""
    session = build(logger)
    session.handle_logon_accepted("EDYY")
    session.pending_logon_station, session.pending_logon_min = "EDGG", 1

    session.logoff()

    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)
```

Update the call sites of the removed `set_callsign`:

- `tests/test_acknowledge_path.py:16`, `tests/test_link_status.py:19`, `tests/test_uplink_handling.py:27`: replace `session.set_callsign("DLH123")` with `session.begin_session("DLH123", "hoppie")`.
- `tests/test_downlink_requests.py:22`: replace `session.set_callsign("BAW123")` with `session.begin_session("BAW123", "hoppie")`.
- `tests/test_downlink_requests.py:153` (`test_a_pdc_request_needs_a_callsign`): replace `session.set_callsign("")` with `session.callsign = ""`.
- `tests/test_downlink_requests.py:160-182`: replace the `SENDS` list and the parametrised test with the version below. The logon case now starts with no station logged on, so it exercises the REQUEST LOGON failure itself rather than the LOGOFF that precedes it (which `test_a_failed_logoff_aborts_the_new_logon` covers).

```python
SENDS = [
    # (name, station logged on before the send, the send)
    ("logon", "", lambda s: s.logon("EGGX")),
    ("logoff", STATION, lambda s: s.logoff()),
    ("altitude", STATION, lambda s: s.send_altitude_change_request("FL350")),
    ("direct", STATION, lambda s: s.send_direct_request("MALOT")),
    ("speed", STATION, lambda s: s.send_speed_request("082", True)),
    ("when-can-we", STATION, lambda s: s.send_when_can_we_expect("WHEN CAN WE EXPECT HIGHER LEVEL")),
    ("acknowledgement", STATION, lambda s: s.send_acknowledgement(STATION, 7, "WILCO")),
    ("telex", STATION, lambda s: s.send_telex("EDDF", "HELLO")),
    ("pdc", STATION, lambda s: s.send_pdc_request("EGLL", "LIMC", "A339", "521", "K")),
]


@pytest.mark.parametrize(
    "station, send", [case[1:] for case in SENDS], ids=[case[0] for case in SENDS]
)
def test_a_transmission_failure_is_reported_and_consumes_no_min(logger, station, send):
    """The error text reaches the dialog, and the MIN is not spent, so the
    next successful send does not leave a gap the station has to explain."""
    session = CpdlcSession(logger, FakeConnectionManager(raise_with=HoppieError("boom")))
    session.begin_session("BAW123", "hoppie")
    session.current_station = station

    assert send(session) == (False, "boom")
    assert session.cpdlc_min_counter == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_cpdlc_session.py tests/test_downlink_requests.py tests/test_acknowledge_path.py tests/test_link_status.py tests/test_uplink_handling.py`
Expected: FAIL with `AttributeError: 'CpdlcSession' object has no attribute 'begin_session'` (and `TypeError: ... unexpected keyword argument 'clock'`).

- [ ] **Step 3: Implement the lifecycle**

In `src/model/cpdlc_session.py`, replace lines 1-60 (module docstring through `get_current_station`) with:

```python
"""CPDLC session management for the client."""

import logging
import time
from typing import Optional, Callable, Tuple

from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

from src.model.connection_manager import ConnectionManager
from src.utils.weather_parsing import report_type_label


class CpdlcSession:
    """Manages CPDLC session state and operations.

    The session knows who the aircraft is talking to: the station logged on
    and a REQUEST LOGON still waiting for its answer. reset() forgets all of
    it; the callsign and network survive, because they identify the aircraft
    rather than the dialogue.
    """

    def __init__(
        self,
        logger,
        connection_manager: ConnectionManager,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Initialize the CPDLC session.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            clock: Returns the current time in seconds. Monotonic, so the
                session's time windows are not upset by a clock change; tests
                pass a hand-driven clock.
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.clock = clock
        self.callsign = ""
        self.network = None
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self.pending_logon_min = None
        self.pending_logon_station = None
        self.pending_logon_at = None

    def reset(self) -> None:
        """Forget the ATC dialogue: station, pending logon and MIN counter.

        The window calls this on File > Disconnect whether or not the LOGOFF
        could be sent, on a fatal link error, and (through begin_session) when
        the aircraft's identity changes. Audit M-1: without it a disconnect
        left the app believing it was still logged on.
        """
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self._clear_pending()
        self.logger.debug("CPDLC session state reset")

    def begin_session(self, callsign: str, network: Optional[str]) -> None:
        """Record the identity of a new network connection.

        The network holds the ATC logon by callsign, so reconnecting as the
        same aircraft on the same network keeps the dialogue; any change of
        identity starts from a clean one.

        Args:
            callsign: The aircraft callsign
            network: The network type, "hoppie" or "sayintentions"
        """
        if (callsign, network) != (self.callsign, self.network):
            self.reset()
        self.callsign = callsign
        self.network = network

    def _clear_pending(self) -> None:
        """Forget a REQUEST LOGON that is waiting for its answer."""
        self.pending_logon_min = None
        self.pending_logon_station = None
        self.pending_logon_at = None

    def get_callsign(self) -> str:
        """Get the current aircraft callsign.

        Returns:
            str: The current callsign
        """
        return self.callsign

    def is_logged_on(self) -> bool:
        """Check if logged on to a station.

        Returns:
            bool: True if logged on, False otherwise
        """
        return bool(self.current_station)

    def get_current_station(self) -> str:
        """Get the current station.

        Returns:
            str: The current station or empty string if not logged on
        """
        return self.current_station
```

Replace `logon()` (from `def logon` down to its `return True, message`) with:

```python
    def logon(self, station: str) -> Tuple[bool, Optional[str]]:
        """Logon to a CPDLC station.

        A station still logged on is sent LOGOFF first, so it learns the
        dialogue has ended before the next one starts (audit M-7). If that
        LOGOFF cannot be sent nothing else is: the app never has a dialogue
        open with two stations, and the pilot retries once the link is back.

        Args:
            station: The station to logon to

        Returns:
            tuple: (success, message_or_error) where success is True and message_or_error
                  is the sent message text, or success is False and message_or_error is
                  an error description (or None for precondition failures)
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Logon attempted without active connection")
            return False, None

        # Validate station name is exactly 4 characters
        if len(station) != 4:
            self.logger.warning(
                f"Invalid station name: {station} (must be 4 characters)"
            )
            return False, None

        if self.current_station:
            previous = self.current_station
            sent, detail = self.logoff()
            if not sent:
                return False, f"could not send LOGOFF to {previous}: {detail}"

        self.logger.info(f"Attempting to logon to station: {station}")
        self.cpdlc_min_counter = 1
        message = "REQUEST LOGON"

        try:
            self.connection_manager.send_cpdlc(
                station,
                self.cpdlc_min_counter,
                RR.YES.value,
                message,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send logon request to {station}: {exc}")
            return False, str(exc)

        # Track the pending logon for MRN validation on LOGON ACCEPTED, and
        # when it was sent so an unanswered request can be given up on
        self.pending_logon_min = self.cpdlc_min_counter
        self.pending_logon_station = station
        self.pending_logon_at = self.clock()

        # Don't set current_station yet, just increment the counter
        self.cpdlc_min_counter += 1
        self.logger.info(f"Logon request sent to {station}")
        return True, message
```

In `logoff()`, replace the block from `# Update session state` to `return True, message` with:

```python
        # Update session state. A logon that was still pending is abandoned
        # too: the pilot is leaving the dialogue, not waiting on it.
        previous_station = self.current_station
        self.cpdlc_min_counter += 1
        self.current_station = ""
        self._clear_pending()
        self.logger.info(f"Successfully logged off from {previous_station}")
        return True, message
```

In `handle_logon_accepted()`, replace the last four lines with:

```python
        self.logger.info(f"Logon accepted by station: {station}")
        self.current_station = station
        self._clear_pending()
        return True
```

Leave `send_logoff_message` in place for now; Task 6 removes it together with its two callers in the window.

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, 260 plus the ten new tests here.

- [ ] **Step 5: Commit**

```bash
git add src/model/cpdlc_session.py tests/support.py tests/test_cpdlc_session.py tests/test_downlink_requests.py tests/test_acknowledge_path.py tests/test_link_status.py tests/test_uplink_handling.py
git commit -m "Give the CPDLC session a lifecycle and send LOGOFF before a new logon"
```

---

### Task 2: The handover window, logon rejection and pending expiry

**Files:**
- Modify: `src/config.py:120-123` (two constants after `RATE_LIMIT_RETRY_MS`)
- Modify: `src/model/cpdlc_session.py` (import the constants; class docstring; `__init__` and `reset()` gain the previous-station fields; new methods after `handle_station_logoff`; the warning in `send_acknowledgement`)
- Test: `tests/test_cpdlc_session.py`

**Interfaces:**
- Consumes: Task 1's `build()`, `FakeClock`, `session.clock`.
- Produces (used by Tasks 3-6):
  - `PREVIOUS_STATION_WINDOW_SECONDS = 600`, `PENDING_LOGON_TIMEOUT_SECONDS = 600` in `src/config.py`.
  - `handle_handover(old: str, new: str) -> Tuple[bool, Optional[str]]`: `(False, None)` unless `old` is the current station; otherwise records `previous_station = old`, `previous_station_until = clock() + PREVIOUS_STATION_WINDOW_SECONDS`, clears the station and the pending logon, and returns `logon(new)`'s result (no LOGOFF is sent).
  - `is_answerable_sender(sender: str) -> bool`: the current station, or the previous station while `clock() < previous_station_until`.
  - `handle_logon_rejected(station: str, mrn: int | None = None) -> bool`: True (and the pending logon cleared) only when `station` is the pending station and `mrn`, if given, equals the pending MIN.
  - `expire_pending(now: float | None = None) -> str | None`: the station whose pending logon is at least `PENDING_LOGON_TIMEOUT_SECONDS` old (cleared, returned once), else None.
  - Fields `previous_station: str` (`""` when none), `previous_station_until: float | None`; both cleared by `reset()`.

- [ ] **Step 1: Write the failing tests**

Add to the imports of `tests/test_cpdlc_session.py`:

```python
import logging

from src.config import PENDING_LOGON_TIMEOUT_SECONDS, PREVIOUS_STATION_WINDOW_SECONDS
```

Append:

```python
# --- the handover window ------------------------------------------------------


def test_a_handover_moves_the_logon_and_keeps_the_old_station_answerable(logger):
    """In 22 of 163 logged handovers the old station's CONTACT arrived after
    the handover, in the same poll as the new station's LOGON ACCEPTED."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    result = session.handle_handover("KUSA", "CZYZ")

    assert result == (True, "REQUEST LOGON")
    assert session.connection_manager.sent == [("CZYZ", 1, "Y", "REQUEST LOGON", None)]
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "CZYZ"
    assert session.is_answerable_sender("KUSA") is True
    assert session.is_answerable_sender("CZYZ") is False


def test_the_old_station_stops_being_answerable_when_the_window_closes(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")
    session.handle_logon_accepted("CZYZ", mrn=1)

    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS - 1)
    assert session.is_answerable_sender("KUSA") is True

    session.clock.advance(1)
    assert session.is_answerable_sender("KUSA") is False
    assert session.is_answerable_sender("CZYZ") is True


def test_a_handover_from_a_station_that_is_not_logged_on_is_ignored(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    assert session.handle_handover("EDUU", "CZYZ") == (False, None)
    assert session.get_current_station() == "KUSA"
    assert session.connection_manager.sent == []


def test_a_handover_sends_no_logoff(logger):
    """The station handing over has ended the dialogue itself."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")

    session.handle_handover("KUSA", "CZYZ")

    assert [frame[3] for frame in session.connection_manager.sent] == ["REQUEST LOGON"]


def test_nobody_is_answerable_when_not_logged_on(logger):
    session = build(logger)

    assert session.is_answerable_sender("KUSA") is False
    assert session.is_answerable_sender("") is False


def test_reset_closes_the_handover_window(logger):
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")

    session.reset()

    assert session.is_answerable_sender("KUSA") is False
    assert (session.previous_station, session.previous_station_until) == ("", None)


def test_only_a_stranger_is_flagged_when_acknowledged(logger, caplog):
    """A WILCO to the station that handed over is part of the dialogue and
    must not be logged as a mismatch."""
    session = build(logger)
    session.handle_logon_accepted("KUSA")
    session.handle_handover("KUSA", "CZYZ")
    session.handle_logon_accepted("CZYZ", mrn=1)

    # The shared `logger` fixture disables propagation so tests stay silent;
    # caplog's handler has to be attached to it directly.
    with caplog.at_level(logging.WARNING, logger=logger.name):
        logger.addHandler(caplog.handler)
        session.send_acknowledgement("KUSA", 7, "WILCO")
        session.send_acknowledgement("EDUU", 8, "WILCO")

    flagged = [record.getMessage() for record in caplog.records if "dialogue" in record.getMessage()]
    assert flagged == ["Acknowledgement sender EDUU is not part of the dialogue (current station CZYZ)"]


# --- rejection and expiry (audit L-3) -----------------------------------------


def test_a_logon_rejected_by_the_pending_station_cancels_the_logon(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG", mrn=1) is True
    assert session.pending_logon_station is None
    assert session.get_current_station() == ""


def test_a_rejection_without_an_mrn_still_counts(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG") is True
    assert session.pending_logon_station is None


def test_a_rejection_from_another_station_is_ignored(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDUU", mrn=1) is False
    assert session.pending_logon_station == "EDGG"


def test_an_unable_for_another_request_is_not_a_rejection(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.handle_logon_rejected("EDGG", mrn=2) is False
    assert session.pending_logon_station == "EDGG"


def test_a_rejection_with_nothing_pending_is_ignored(logger):
    session = build(logger)
    session.handle_logon_accepted("EDYY")

    assert session.handle_logon_rejected("EDYY", mrn=1) is False
    assert session.get_current_station() == "EDYY"


def test_an_unanswered_logon_expires_after_the_timeout(logger):
    session = build(logger)
    session.logon("EDGG")

    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS - 1)
    assert session.expire_pending() is None
    assert session.pending_logon_station == "EDGG"

    session.clock.advance(1)
    assert session.expire_pending() == "EDGG"
    assert (session.pending_logon_station, session.pending_logon_min) == (None, None)


def test_expiry_reports_each_unanswered_logon_once(logger):
    session = build(logger)
    session.logon("EDGG")
    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)
    session.expire_pending()

    assert session.expire_pending() is None


def test_expiry_leaves_an_accepted_logon_alone(logger):
    session = build(logger)
    session.logon("EDGG")
    session.handle_logon_accepted("EDGG", mrn=1)
    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)

    assert session.expire_pending() is None
    assert session.get_current_station() == "EDGG"


def test_expiry_can_be_asked_about_a_given_time(logger):
    session = build(logger)
    session.logon("EDGG")

    assert session.expire_pending(now=session.clock.now + PENDING_LOGON_TIMEOUT_SECONDS) == "EDGG"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_cpdlc_session.py`
Expected: FAIL with `ImportError: cannot import name 'PENDING_LOGON_TIMEOUT_SECONDS'`.

- [ ] **Step 3: Add the constants**

In `src/config.py`, after the `RATE_LIMIT_RETRY_MS = 5000` line (line 123), add:

```python

# After a HANDOVER the station that handed the aircraft over may still send
# a WILCO-required instruction (typically the CONTACT frequency); the log
# shows this in 22 of 163 handovers. Its uplinks stay answerable this long.
PREVIOUS_STATION_WINDOW_SECONDS = 600

# A REQUEST LOGON nobody answers is given up on after this long, and the
# pilot is told.
PENDING_LOGON_TIMEOUT_SECONDS = 600
```

- [ ] **Step 4: Implement the window, the rejection and the expiry**

In `src/model/cpdlc_session.py`:

Add after the `from hoppie_connector import ...` line:

```python
from src.config import PENDING_LOGON_TIMEOUT_SECONDS, PREVIOUS_STATION_WINDOW_SECONDS
```

Replace the class docstring with:

```python
    """Manages CPDLC session state and operations.

    The session knows who the aircraft is talking to: the station logged on,
    a REQUEST LOGON still waiting for its answer, and for a while after a
    handover the station that handed the aircraft over, whose late uplinks
    (typically the CONTACT instruction) are still answerable. reset() forgets
    all of it; the callsign and network survive, because they identify the
    aircraft rather than the dialogue.
    """
```

In `__init__`, after `self.pending_logon_at = None`, add:

```python
        self.previous_station = ""
        self.previous_station_until = None
```

In `reset()`, after `self._clear_pending()`, add:

```python
        self.previous_station = ""
        self.previous_station_until = None
```

and change its first docstring line to `"""Forget the ATC dialogue: station, pending logon, handover window, MIN.`

In `send_acknowledgement()`, replace the `if self.current_station and sender != self.current_station:` warning with:

```python
        if self.current_station and not self.is_answerable_sender(sender):
            self.logger.warning(
                f"Acknowledgement sender {sender} is not part of the dialogue "
                f"(current station {self.current_station})"
            )
```

Add after `handle_station_logoff()` (before `send_pdc_request`):

```python
    def handle_handover(self, old: str, new: str) -> Tuple[bool, Optional[str]]:
        """Follow a HANDOVER from the current station to the next one.

        The old station keeps answering for a while: in 22 of 163 logged
        handovers its CONTACT instruction arrived after the handover, in the
        same poll as the new station's LOGON ACCEPTED. Its uplinks therefore
        stay answerable for PREVIOUS_STATION_WINDOW_SECONDS. No LOGOFF is
        sent; the station handing over has ended the dialogue itself.

        Args:
            old: The station handing over; must be the current station
            new: The station to log on to

        Returns:
            logon()'s result, or (False, None) when old is not the current
            station
        """
        if not old or old != self.current_station:
            self.logger.warning(
                f"Ignoring handover from {old}: current station is "
                f"{self.current_station or '(none)'}"
            )
            return False, None

        self.logger.info(f"Handover from {old} to {new}")
        self.previous_station = old
        self.previous_station_until = self.clock() + PREVIOUS_STATION_WINDOW_SECONDS
        self.current_station = ""
        self._clear_pending()
        return self.logon(new)

    def is_answerable_sender(self, sender: str) -> bool:
        """Whether an uplink from this station can still be answered.

        True for the current station, and for the station that handed the
        aircraft over until its window closes. The message list uses this to
        decide whether to offer responses.

        Args:
            sender: The station the uplink came from
        """
        if not sender:
            return False
        if sender == self.current_station:
            return True
        return (
            sender == self.previous_station
            and self.previous_station_until is not None
            and self.clock() < self.previous_station_until
        )

    def handle_logon_rejected(self, station: str, mrn: Optional[int] = None) -> bool:
        """Handle a station refusing our REQUEST LOGON.

        Covers an explicit LOGON REJECTED and an UNABLE answering the request.
        Either must come from the station the logon is pending with, and an
        MRN, when given, must reference the pending request.

        Args:
            station: The station that answered
            mrn: The message reference number of the answer, if any

        Returns:
            bool: True if a pending logon was cancelled, False if the message
                did not concern one
        """
        if not self.pending_logon_station or station != self.pending_logon_station:
            return False
        if mrn is not None and mrn != self.pending_logon_min:
            return False

        self.logger.info(f"Logon to {station} rejected")
        self._clear_pending()
        return True

    def expire_pending(self, now: Optional[float] = None) -> Optional[str]:
        """Give up on a REQUEST LOGON nobody answered.

        Args:
            now: The current clock reading; taken from the clock when None

        Returns:
            The station whose pending logon just expired, else None
        """
        if self.pending_logon_at is None:
            return None
        now = self.clock() if now is None else now
        if now - self.pending_logon_at < PENDING_LOGON_TIMEOUT_SECONDS:
            return None

        station = self.pending_logon_station
        self.logger.warning(
            f"Logon to {station} not answered within {PENDING_LOGON_TIMEOUT_SECONDS} s"
        )
        self._clear_pending()
        return station
```

- [ ] **Step 5: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, sixteen more than after Task 1.

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/model/cpdlc_session.py tests/test_cpdlc_session.py
git commit -m "Keep the station that handed over answerable, and handle a refused or unanswered logon"
```

---

### Task 3: Answerability is a predicate the session provides

**Files:**
- Modify: `src/model/message_manager.py:3` (import `Callable`), `:301-334` (`needs_acknowledgement`)
- Modify: `src/gui/message_view.py:11-45` (constructor), `:132-137` (`on_context_menu`)
- Modify: `src/gui/main_window.py:146-154` (`_init_ui` passes `is_answerable_sender`)
- Modify: `tests/support.py` (add `answerable()` after `uplink()`)
- Modify: `tests/test_message_manager.py`, `tests/test_acknowledge_path.py`, `tests/test_message_view.py`, `tests/test_main_window_wiring.py`

**Interfaces:**
- Consumes: `CpdlcSession.is_answerable_sender`, `handle_handover` (Task 2), `FakeClock` (Task 1).
- Produces:
  - `MessageManager.needs_acknowledgement(message_id: int, is_answerable: Callable[[str], bool]) -> Tuple[bool, List[str]]`; the predicate is called with the sender of a CPDLC message and never for other entries.
  - `MessageView(parent, logger, message_manager, on_acknowledge, is_answerable_sender, on_toggle_weather_updates=None, is_weather_watched=None)`; attribute `is_answerable_sender`.
  - `tests.support.answerable(*stations)`: a predicate that is True for exactly those stations.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, add after the `uplink()` function:

```python
def answerable(*stations):
    """A sender predicate that answers True for exactly these stations.

    Stands in for CpdlcSession.is_answerable_sender where no session is
    involved; answerable() with no stations means nobody is logged on.
    """
    return lambda sender: sender in stations
```

In `tests/test_message_manager.py`:

- Change the support import to `from tests.support import answerable, uplink`.
- Replace every `needs_acknowledgement(<id>, STATION)` (lines 26, 36, 46, 57, 99, 111, 156) with `needs_acknowledgement(<id>, answerable(STATION))`.
- Line 65: `needs_acknowledgement(message_id, "EDGG")` becomes `needs_acknowledgement(message_id, answerable("EDGG"))`.
- Line 72: `needs_acknowledgement(message_id, "")` becomes `needs_acknowledgement(message_id, answerable())`.
- Change the docstring of `test_a_message_from_another_station_offers_no_responses` to `"""A station the session no longer answers for offers no responses."""`.
- Add after `test_a_message_offers_no_responses_when_not_logged_on`:

```python
def test_the_predicate_is_asked_about_the_message_sender(logger):
    """After a handover the previous station stays answerable for a while;
    the manager only relays the question to whoever knows the dialogue."""
    manager = MessageManager(logger)
    message_id = manager.add_message(uplink("KUSA", 4))
    asked = []

    def is_answerable(sender):
        asked.append(sender)
        return True

    assert manager.needs_acknowledgement(message_id, is_answerable)[0] is True
    assert asked == ["KUSA"]


def test_a_custom_row_never_asks_the_predicate(logger):
    manager = MessageManager(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    def never(sender):
        raise AssertionError("asked about a SYSTEM row")

    assert manager.needs_acknowledgement(message_id, never) == (False, [])
```

In `tests/test_acknowledge_path.py`:

- Change the support import to `from tests.support import FakeConnectionManager, answerable, make_main_window, uplink`.
- Replace `needs_acknowledgement(message_id, STATION)` at lines 55, 65, 97 and 105 with `needs_acknowledgement(message_id, answerable(STATION))`.

In `tests/test_message_view.py`:

- Change the support import to `from tests.support import answerable, uplink`.
- `build_view`: replace `lambda: station` with `answerable(station)`.
- Line 32: replace `lambda: ""` with `answerable()`.
- Lines 76 and 101: replace `lambda: STATION` with `answerable(STATION)`.

Replace `tests/test_main_window_wiring.py` from its `STATION = "LSAG"` line to the end with:

```python
STATION = "LSAG"


class HeadlessMainWindow(MainWindow):
    def __init__(self, logger, cpdlc_session, message_manager):
        wx.Frame.__init__(self, None, title="Sim-CPDLC test")
        self.logger = logger
        self.cpdlc_session = cpdlc_session
        self.message_manager = message_manager
        self._init_ui()


@pytest.fixture
def window(logger, wx_app):
    session = CpdlcSession(logger, FakeConnectionManager(), clock=FakeClock())
    frame = HeadlessMainWindow(logger, session, MessageManager(logger))
    # PopupMenu runs a nested modal loop, which would hang the test; count
    # the menus that would have been shown instead.
    frame.panel.popped = []
    frame.panel.PopupMenu = frame.panel.popped.append
    yield frame
    frame.Destroy()


def test_init_ui_wires_the_message_view_to_the_live_session(window):
    """The view must ask the session, not a stale copy, who can be answered."""
    window.cpdlc_session.handle_logon_accepted(STATION)

    assert window.message_view.is_answerable_sender(STATION) is True
    assert window.message_view.is_answerable_sender("EDGG") is False


def test_context_menu_follows_the_session_after_a_handover(window):
    """A message from the station that handed us over keeps offering
    responses until its window closes, then stops."""
    window.cpdlc_session.handle_logon_accepted("EDYY")
    message_id = window.message_manager.add_message(uplink("EDYY", 4))
    window.message_view.add_message(message_id)
    window.message_view.message_list.Select(0)
    window.cpdlc_session.handle_handover("EDYY", "EDGG")

    window.message_view.on_context_menu(None)
    assert len(window.panel.popped) == 1

    window.cpdlc_session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)
    window.message_view.on_context_menu(None)
    assert len(window.panel.popped) == 1
```

and change its imports to:

```python
import pytest
import wx

from src.config import PREVIOUS_STATION_WINDOW_SECONDS
from src.gui.main_window import MainWindow
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeClock, FakeConnectionManager, uplink
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_message_manager.py tests/test_message_view.py tests/test_main_window_wiring.py tests/test_acknowledge_path.py`
Expected: FAIL. `test_the_predicate_is_asked_about_the_message_sender` and the reworked manager tests fail with `TypeError: 'function' object ...` or `AttributeError` inside `needs_acknowledgement` (it compares the sender to the predicate); the wiring test fails with `AttributeError: 'MessageView' object has no attribute 'is_answerable_sender'`.

- [ ] **Step 3: Implement the predicate**

In `src/model/message_manager.py`, change the typing import to:

```python
from typing import Callable, List, Tuple, Set, Optional, Any
```

Replace `needs_acknowledgement` with:

```python
    def needs_acknowledgement(
        self, message_id: int, is_answerable: Callable[[str], bool]
    ) -> Tuple[bool, List[str]]:
        """Check if a message needs acknowledgement and get valid responses.

        Args:
            message_id: The ID of the message to check
            is_answerable: Whether a reply to a given station is still part
                of the live dialogue. The session answers True for the
                current station and, for a while after a handover, for the
                station that handed the aircraft over.

        Returns:
            tuple: (needs_ack, responses)
        """
        message = self.message_log.get(message_id)

        if isinstance(message, CpdlcMessage):
            sender = message.get_from_name()
            if not is_answerable(sender):
                self.logger.debug(
                    f"Message ID={message_id} is from {sender}, which is no "
                    "longer part of the dialogue; not answerable."
                )
                return False, []

            # Check if this message has already been acknowledged
            if message_id not in self.acknowledged_messages:
                responses = self._get_cpdlc_responses(message)
                if responses:
                    self.logger.debug("Message needs acknowledgement.")
                    return True, responses

        self.logger.debug("Message does not need acknowledgement.")
        return False, []
```

In `src/gui/message_view.py`:

- In the constructor signature, rename the parameter `get_current_station` to `is_answerable_sender`.
- Replace its docstring entry with:

```python
            is_answerable_sender: Callable(station) returning whether a reply
                to that station is still part of the live dialogue: the
                current station, or for a while after a handover the one that
                handed the aircraft over
```

- Replace `self.get_current_station = get_current_station` with `self.is_answerable_sender = is_answerable_sender`.
- In `on_context_menu`, replace the comment and call:

```python
        # needs_acknowledgement resolves the ID itself and rejects anything
        # that is not an unanswered CPDLC message from a station still in the
        # dialogue.
        self.logger.debug(f"Checking message ID={message_id}")
        needs_ack, responses = self.message_manager.needs_acknowledgement(
            message_id, self.is_answerable_sender
        )
```

In `src/gui/main_window.py` `_init_ui`, replace `self.cpdlc_session.get_current_station,` with `self.cpdlc_session.is_answerable_sender,`.

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, two more than after Task 2.

- [ ] **Step 5: Commit**

```bash
git add src/model/message_manager.py src/gui/message_view.py src/gui/main_window.py tests/support.py tests/test_message_manager.py tests/test_acknowledge_path.py tests/test_message_view.py tests/test_main_window_wiring.py
git commit -m "Ask the session whether a sender can still be answered"
```

---

### Task 4: `_on_message_received` — CPDLC only, prefix matching, rejection, the handover window

**Files:**
- Modify: `src/gui/main_window.py:47` (drop the `extract_message_content` import), after line 52 (module constant `HANDOVER_PATTERN`), `:1039-1148` (replace `_on_message_received`)
- Test: `tests/test_uplink_handling.py`

**Interfaces:**
- Consumes: `CpdlcSession.handle_handover`, `handle_logon_rejected`, `is_answerable_sender` (Task 2); `CpdlcMessage.get_message()`, `get_from_name()`, `get_mrn()` from hoppie_connector; `TelexMessage(from_name, to_name, message)`.
- Produces: `MainWindow._protocol_text(message)` (staticmethod), `_handle_session_uplink(message, text)`, `_follow_handover(sender, new_station)`, `_auto_tune(text)`; module constant `HANDOVER_PATTERN`. Status texts and rows exactly as in the Global Constraints.

- [ ] **Step 1: Write the failing tests**

Replace the header of `tests/test_uplink_handling.py` (everything above `# --- handover ---`) with:

```python
"""How the window reacts to uplinks that change session state or tune the radio.

These drive MainWindow._on_message_received with the exact texts the two
networks send, taken from the maintainer's logs.
"""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR, TelexMessage

from src.config import PREVIOUS_STATION_WINDOW_SECONDS
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeConnectionManager,
    FakeSimConnectManager,
    make_main_window,
    uplink,
)

CURRENT = "EDYY"
OTHER = "EDUU"
CONTACT = "CONTACT MARSEILLE CONTROL ON @133.325@."


def build(logger, config=None, simconnect=None, station=CURRENT):
    """A window logged on to `station` ("" for none) as DLH123 on Hoppie."""
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock())
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    if station:
        session.handle_logon_accepted(station)
    simconnect = simconnect if simconnect is not None else FakeSimConnectManager()
    window = make_main_window(
        logger, session, MessageManager(logger), config=config, simconnect=simconnect
    )
    return window, session, connection, simconnect


def system_rows(window):
    """The texts of the SYSTEM rows in the message list, in order."""
    manager = window.message_manager
    rows = [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]
    return [text for sender, text in rows if sender == "SYSTEM"]
```

Leave the existing tests as they are (the `build(logger)` calls still work) and add, after `test_a_handover_from_another_station_is_shown_but_not_acted_on`:

```python
def test_a_handover_keeps_the_old_station_answerable(logger):
    window, session, _, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGG@", rr=RR.NOT_REQUIRED))

    assert session.is_answerable_sender(CURRENT) is True


def test_the_logged_handover_sequence_tunes_and_answers_the_late_contact(logger):
    """Verbatim from the log: KUSA hands over to CZYZ, and the next poll
    carries KUSA's CONTACT together with CZYZ's LOGON ACCEPTED. Older builds
    let the pilot WILCO that CONTACT; the strict scoping on main did not."""
    window, session, connection, simconnect = build(logger, station="KUSA")
    window._on_message_received(uplink("KUSA", 12, "HANDOVER @CZYZ@", rr=RR.NOT_REQUIRED))

    before = len(window.message_view.added)
    window._on_message_received(uplink("KUSA", 13, "CONTACT TORONTO CENTER ON @135.625@."))
    window._on_message_received(uplink("CZYZ", 1, "LOGON ACCEPTED", rr=RR.NOT_REQUIRED, mrn=1))

    contact_id = window.message_view.added[before]
    assert connection.sent == [("CZYZ", 1, RR.YES.value, "REQUEST LOGON", None)]
    assert session.get_current_station() == "CZYZ"
    assert simconnect.tuned == [135.625]
    assert window.message_manager.needs_acknowledgement(contact_id, session.is_answerable_sender)[0] is True

    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)

    assert window.message_manager.needs_acknowledgement(contact_id, session.is_answerable_sender)[0] is False


def test_a_contact_from_the_old_station_is_not_tuned_once_the_window_has_closed(logger):
    window, session, _, simconnect = build(logger, station="KUSA")
    window._on_message_received(uplink("KUSA", 12, "HANDOVER @CZYZ@", rr=RR.NOT_REQUIRED))
    session.clock.advance(PREVIOUS_STATION_WINDOW_SECONDS)

    window._on_message_received(uplink("KUSA", 13, "CONTACT TORONTO CENTER ON @135.625@."))

    assert simconnect.tuned == []
```

Append at the end of the file:

```python
# --- only CPDLC carries session state (audit L-2) -----------------------------


@pytest.mark.parametrize(
    "text",
    ["LOGON ACCEPTED", "LOGOFF", "HANDOVER @EDGG@"],
    ids=["accepted", "logoff", "handover"],
)
def test_a_telex_cannot_drive_the_session(logger, text):
    """The old hasattr gate let any HoppieMessage through; a telex from the
    current station reading LOGON ACCEPTED was treated as one."""
    window, session, connection, _ = build(logger)

    window._on_message_received(TelexMessage(CURRENT, CLIENT_CALLSIGN, text))

    assert session.get_current_station() == CURRENT
    assert connection.sent == []
    assert window.status_texts == []
    assert len(window.message_view.added) == 1


# --- logon acceptance and rejection (audit L-3) -------------------------------


def test_logon_accepted_with_trailing_text_still_logs_on(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(
        uplink("EDGG", 1, "LOGON ACCEPTED WELCOME", rr=RR.NOT_REQUIRED, mrn=1)
    )

    assert session.get_current_station() == "EDGG"
    assert window.status_texts == ["Logged on to EDGG."]


def test_a_logon_rejected_cancels_the_pending_logon(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink("EDGG", 1, "LOGON REJECTED", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station is None
    assert window.status_texts == ["Logon to EDGG rejected."]
    assert system_rows(window) == ["Logon to EDGG rejected"]


def test_an_unable_answering_the_logon_request_cancels_it(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink("EDGG", 1, "UNABLE", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station is None
    assert window.status_texts == ["Logon to EDGG rejected."]
    assert system_rows(window) == ["Logon to EDGG rejected"]


def test_an_unable_answering_another_request_is_only_shown(logger):
    window, session, _, _ = build(logger)
    session.send_altitude_change_request("FL350")  # our MIN 1

    window._on_message_received(uplink(CURRENT, 9, "UNABLE", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.get_current_station() == CURRENT
    assert window.status_texts == []
    assert system_rows(window) == []
    assert len(window.message_view.added) == 1


def test_a_rejection_from_a_station_we_did_not_ask_is_only_shown(logger):
    window, session, _, _ = build(logger, station="")
    session.logon("EDGG")

    window._on_message_received(uplink(OTHER, 1, "LOGON REJECTED", rr=RR.NOT_REQUIRED, mrn=1))

    assert session.pending_logon_station == "EDGG"
    assert window.status_texts == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_uplink_handling.py`
Expected: the new tests FAIL (`simconnect.tuned == []` in the log sequence, `status_texts == ["Logged on to EDYY."]` for the telex, no status for the rejections, no logon for the trailing text); the existing ones still pass.

- [ ] **Step 3: Rewrite the handler**

In `src/gui/main_window.py`:

Delete the line `from src.utils.message_formatting import extract_message_content` (nothing else in the file uses it).

After the last import (`from src.gui.dialogs.settings_dialog import SettingsDialog`), add:

```python
# A HANDOVER names the next station as a 4-letter code; the @ separators the
# networks wrap it in have been flattened to spaces by then.
HANDOVER_PATTERN = re.compile(r"^HANDOVER\s+([A-Z]{4})$")
```

Replace the whole `_on_message_received` method (from `def _on_message_received` down to the `"Auto-tune failed"` status text and its closing parenthesis) with:

```python
    def _on_message_received(self, message):
        """Handle received messages from the network.

        Only a CPDLC message can change session state or tune the radio.
        Telex, progress and ADS-C messages are shown and nothing else, so a
        telex reading LOGON ACCEPTED cannot log the aircraft on (audit L-2).

        Args:
            message: The received message
        """
        text = None
        if isinstance(message, CpdlcMessage):
            text = self._protocol_text(message)
            # Protocol noise, hidden before it reaches the list
            if text.startswith("CURRENT ATC UNIT") or text.startswith("CURRENT ATS UNIT"):
                self.logger.debug(f"Hiding protocol message: {text}")
                return

        message_id = self.message_manager.add_message(message)
        if message_id < 0:
            return

        self.message_view.add_message(message_id)
        self._play_message_sound()

        if text is not None:
            self._handle_session_uplink(message, text)

    @staticmethod
    def _protocol_text(message):
        """A CPDLC message element with its @ separators flattened to spaces."""
        return " ".join(message.get_message().replace("@", " ").split())

    def _handle_session_uplink(self, message, text):
        """Apply a CPDLC uplink to the session, then tune the radio if it asks.

        Args:
            message: The CpdlcMessage, already in the list
            text: Its element text as returned by _protocol_text
        """
        session = self.cpdlc_session
        sender = message.get_from_name()
        mrn = message.get_mrn()

        if text.startswith("LOGON ACCEPTED"):
            # Only report the logon if the session actually accepted it; a
            # stale acceptance from a previously contacted station is ignored
            # and must not be announced as success.
            if session.handle_logon_accepted(sender, mrn=mrn):
                self.SetStatusText(f"Logged on to {sender}.")
                self.logger.info(f"Logon accepted by {sender}")
        elif text.startswith("LOGON REJECTED") or (text == "UNABLE" and mrn is not None):
            # An UNABLE is only a rejection when it answers the REQUEST LOGON;
            # the session checks the station and the MRN.
            if session.handle_logon_rejected(sender, mrn=mrn):
                self.SetStatusText(f"Logon to {sender} rejected.")
                self._add_custom_message(f"Logon to {sender} rejected", "SYSTEM")
        elif sender == session.get_current_station():
            match = HANDOVER_PATTERN.match(text)
            if match:
                self._follow_handover(sender, match.group(1))
            elif text == "LOGOFF":
                session.handle_station_logoff(sender)
                self.SetStatusText(f"Logged off from {sender}.")
                self.logger.info(f"Received LOGOFF from {sender}")

        # The station that handed the aircraft over may still send the CONTACT
        # for the next frequency, so any answerable sender may tune the radio.
        if session.is_answerable_sender(sender):
            self._auto_tune(text)

    def _follow_handover(self, sender, new_station):
        """Log on to the station a HANDOVER names.

        Args:
            sender: The station handing over (the current station)
            new_station: The station to log on to
        """
        self.logger.info(f"Handover detected from {sender} to {new_station}")
        self.SetStatusText(f"Logged off from {sender}.")
        self._add_custom_message(f"Logging on to {new_station}", "SYSTEM")

        success, message = self.cpdlc_session.handle_handover(sender, new_station)
        if success:
            if message:
                self._add_custom_message(message)
            self.SetStatusText(f"Pending logon to {new_station}.")
            self.polling_controller.set_active_polling()
        else:
            error_detail = f": {message}" if message else ""
            self.logger.error(
                f"Failed to send logon request to {new_station} during handover{error_detail}"
            )
            self._add_custom_message(
                f"Failed to logon to {new_station} during handover{error_detail}",
                "SYSTEM",
            )

    def _auto_tune(self, text):
        """Put a CONTACT/MONITOR frequency into the COM1 standby, if enabled.

        Args:
            text: The uplink's element text as returned by _protocol_text
        """
        config = load_config()
        if not config.get("auto_tune_com1", True):
            return

        freq = extract_contact_frequency(text)
        if freq is None:
            return

        self.logger.info(f"CONTACT/MONITOR frequency detected: {freq:.3f} MHz")
        if self.simconnect_manager.set_com1_standby_mhz(freq):
            self.logger.info(f"COM1 standby set to {freq:.3f} MHz")
        else:
            self.logger.warning("Could not set COM1 standby (SimConnect unavailable)")
            self.SetStatusText(f"Auto-tune failed \u2014 set {freq:.3f} manually")
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, eleven more than after Task 3 (the telex case is parametrised three ways).

- [ ] **Step 5: Commit**

```bash
git add src/gui/main_window.py tests/test_uplink_handling.py
git commit -m "Let only CPDLC uplinks drive the session, and tune for the station that handed over"
```

---

### Task 5: A tick callback, so an unanswered logon is given up on

**Files:**
- Modify: `src/controller/polling_controller.py:30-64` (constructor), `:184-187` (call it at the end of the tick)
- Modify: `src/gui/main_window.py:108-117` (pass `tick_callback`), after `_on_unreadable_messages` (add `_on_poll_tick`)
- Test: `tests/test_polling_controller.py`, `tests/test_logon_status.py`, `tests/test_main_window.py:222-228`

**Interfaces:**
- Consumes: `CpdlcSession.expire_pending()` (Task 2); `ScriptedConnection`, `failed()`, `tick()` from `tests/test_polling_controller.py`.
- Produces: `PollingController(..., tick_callback=None)`, attribute `tick_callback`, called with no arguments after the batch is delivered and the inactivity check has run, on every tick including failed polls (not after a FATAL poll, when the tick returns early). `MainWindow._on_poll_tick()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_polling_controller.py`:

```python
# --- the tick callback --------------------------------------------------------


def test_the_tick_callback_runs_after_every_poll_even_a_failed_one(logger, frame):
    """The window gives up on an unanswered logon from here, and an outage
    must not stop that clock."""
    # A bare wx.Frame has no status bar; the failed poll reaches _set_status().
    frame.SetStatusText = lambda text: None
    ticks = []
    poller = PollingController(
        logger, ScriptedConnection(failed(1)), tick_callback=lambda: ticks.append(1)
    )
    poller.start(frame)

    tick(poller)
    tick(poller)

    assert len(ticks) == 2


def test_the_tick_callback_runs_after_the_batch_is_delivered(logger, frame):
    order = []
    poller = PollingController(
        logger,
        ScriptedConnection(PollResult(ok=True, messages=["CLEARANCE"])),
        order.append,
        tick_callback=lambda: order.append("tick"),
    )
    poller.start(frame)

    tick(poller)

    assert order == ["CLEARANCE", "tick"]


def test_a_raising_tick_callback_still_schedules_the_next_poll(logger, frame):
    def tick_callback():
        raise RuntimeError("status bar gone")

    poller = PollingController(logger, ScriptedConnection(), tick_callback=tick_callback)
    poller.start(frame)

    with pytest.raises(RuntimeError, match="status bar gone"):
        tick(poller)

    assert poller.is_running() is True
```

In `tests/test_main_window.py`, replace `test_the_real_window_listens_to_its_polling_controller` with:

```python
def test_the_real_window_listens_to_its_polling_controller(window):
    """The link, unreadable and tick callbacks are how a lost link, a dropped
    uplink and an unanswered logon reach the message list at all."""
    controller = window.polling_controller

    assert controller.link_callback == window._on_link_change
    assert controller.unreadable_callback == window._on_unreadable_messages
    assert controller.tick_callback == window._on_poll_tick
```

In `tests/test_logon_status.py`, change the imports to:

```python
from hoppie_connector import CpdlcResponseRequirement as RR

from src.config import PENDING_LOGON_TIMEOUT_SECONDS
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeClock, FakeConnectionManager, make_main_window, uplink
```

and append:

```python
def test_an_unanswered_logon_is_given_up_on_and_announced(logger):
    """Audit L-3: a pending logon never expired, so the status bar said
    "Pending logon to X." for the rest of the flight."""
    session = CpdlcSession(logger, FakeConnectionManager(), clock=FakeClock())
    session.logon("EDDF")
    window = make_main_window(logger, session, MessageManager(logger))

    window._on_poll_tick()
    assert window.status_texts == []

    session.clock.advance(PENDING_LOGON_TIMEOUT_SECONDS)
    window._on_poll_tick()
    window._on_poll_tick()

    assert window.status_texts == ["Logon to EDDF not answered."]
    assert session.pending_logon_station is None
    manager = window.message_manager
    assert [manager.get_message_display_text(mid) for mid in manager.message_log] == [
        ("SYSTEM", "Logon to EDDF not answered")
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_polling_controller.py tests/test_logon_status.py tests/test_main_window.py`
Expected: FAIL with `TypeError: PollingController.__init__() got an unexpected keyword argument 'tick_callback'` and `AttributeError: 'MainWindow' object has no attribute '_on_poll_tick'`.

- [ ] **Step 3: Implement the callback**

In `src/controller/polling_controller.py`:

- Add `tick_callback=None,` to the constructor signature after `unreadable_callback=None,`.
- Add to the constructor docstring, after the `unreadable_callback` entry:

```python
            tick_callback: Callback() run at the end of every tick, whatever
                the poll returned, for housekeeping that keeps the poll's
                rhythm, such as giving up on an unanswered logon
```

- After `self.unreadable_callback = unreadable_callback`, add `self.tick_callback = tick_callback`.
- In `on_poll_timer`, replace

```python
            self._deliver(result)
            self.check_polling_timeout()
            if link_error is not None:
                raise link_error
```

with

```python
            self._deliver(result)
            self.check_polling_timeout()
            if self.tick_callback:
                self.tick_callback()
            if link_error is not None:
                raise link_error
```

In `src/gui/main_window.py`:

- In `__init__`, add `tick_callback=self._on_poll_tick,` after `unreadable_callback=self._on_unreadable_messages,`.
- Add after `_on_unreadable_messages`:

```python
    def _on_poll_tick(self):
        """Housekeeping on the poll clock: give up on a logon nobody answered."""
        station = self.cpdlc_session.expire_pending()
        if station:
            self.SetStatusText(f"Logon to {station} not answered.")
            self._add_custom_message(f"Logon to {station} not answered", "SYSTEM")
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, four more than after Task 4.

- [ ] **Step 5: Commit**

```bash
git add src/controller/polling_controller.py src/gui/main_window.py tests/test_polling_controller.py tests/test_logon_status.py tests/test_main_window.py
git commit -m "Give up on a logon nobody answers, checked on every poll tick"
```

---

### Task 6: Connect, disconnect, exit and the fatal teardown go through the session lifecycle

**Files:**
- Modify: `src/gui/main_window.py:345-346` (`on_connect`), `:385-397` (`on_disconnect`), add `_end_dialogue` after `on_disconnect`, `:882-885` (`_on_fatal_link_error`), `:1229-1236` (`on_close`)
- Modify: `src/model/cpdlc_session.py:143-152` (delete `send_logoff_message`)
- Modify: `tests/support.py` (`FakeConnectionManager.connect`, `FakePollingController.start`, `FakeWeatherMonitor.shutdown`, `FakeCloseEvent`)
- Create: `tests/test_session_lifecycle.py`
- Modify: `tests/README.md`

**Interfaces:**
- Consumes: `CpdlcSession.reset`, `begin_session`, `logoff`, `handle_handover` (Tasks 1-2); `make_main_window`; the autouse `message_boxes` recorder (answers `wx.YES` unless its `answer` is changed).
- Produces: `MainWindow._end_dialogue()`; `FakeConnectionManager.connect(callsign, logon_code, network_type)` recording `connected_as = (callsign, network_type)` and turning `is_connected()` on; `FakePollingController.start(parent_window)` setting `started`; `FakeWeatherMonitor.shutdown()` setting `shut_down`; `FakeCloseEvent` with `Skip()`/`Veto()` recorded as `skipped`/`vetoed`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`:

- In `FakeConnectionManager.__init__`, add `self.connected_as = None` after `self.disconnected = False`, and add the method:

```python
    def connect(self, callsign, logon_code, network_type):
        self._connected = True
        self.connected_as = (callsign, network_type)
```

- In `FakePollingController.__init__`, add `self.started = False`, and the method:

```python
    def start(self, parent_window):
        self.started = True
```

- In `FakeWeatherMonitor.__init__`, add `self.shut_down = False`, and the method:

```python
    def shutdown(self):
        self.shut_down = True
```

- Add after `FakeCallLater`:

```python
class FakeCloseEvent:
    """Stands in for the wx.CloseEvent on_close receives."""

    def __init__(self):
        self.skipped = False
        self.vetoed = False

    def Skip(self):
        self.skipped = True

    def Veto(self):
        self.vetoed = True
```

Create `tests/test_session_lifecycle.py`:

```python
"""Where the ATC dialogue ends: File > Disconnect, exit, a rejected logon code.

A lost link is not one of them: the network holds the logon by callsign, so
the session must survive an outage (design decision 4).
"""

import wx
from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

import src.gui.main_window as mw
from src.controller.link_state import LinkState
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeCloseEvent,
    FakeConnectionManager,
    make_main_window,
)

STATION = "EDYY"


def build(logger, connection=None):
    """A window logged on to EDYY as DLH123 on Hoppie, MIN counter at 1."""
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock())
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, session, connection, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def dialogue(session):
    """The state reset() is responsible for."""
    return (
        session.get_current_station(),
        session.pending_logon_station,
        session.previous_station,
        session.cpdlc_min_counter,
    )


# --- File > Disconnect --------------------------------------------------------


def test_disconnect_logs_off_and_forgets_the_dialogue(logger):
    window, session, connection, manager = build(logger)

    window.on_disconnect()

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert connection.disconnected is True
    assert rows(manager) == [
        (CLIENT_CALLSIGN, "LOGOFF"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert window.status_texts == ["Disconnected from CPDLC network."]


def test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails(logger):
    """Audit M-1: a dead link is the usual reason to disconnect, and the
    failed LOGOFF used to leave the app believing it was still logged on."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, connection, manager = build(logger, connection)

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert rows(manager)[0] == ("SYSTEM", "Could not send LOGOFF to EDYY: timed out")
    assert connection.disconnected is True


def test_disconnect_closes_a_handover_in_progress(logger):
    window, session, connection, _ = build(logger)
    session.handle_handover(STATION, "EDGG")

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert session.is_answerable_sender(STATION) is False
    assert [frame[3] for frame in connection.sent] == ["REQUEST LOGON"]


def test_a_cancelled_disconnect_changes_nothing(logger, message_boxes):
    message_boxes.answer = wx.NO
    window, session, connection, _ = build(logger)

    window.on_disconnect()

    assert session.get_current_station() == STATION
    assert connection.sent == []
    assert connection.disconnected is False


# --- exit ---------------------------------------------------------------------


def test_exit_logs_off_and_forgets_the_dialogue(logger):
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert window.polling_controller.stopped is True
    assert window.weather_monitor.shut_down is True
    assert event.skipped is True


def test_exit_reports_a_logoff_it_could_not_send(logger):
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, _, manager = build(logger, connection)

    window.on_close(FakeCloseEvent())

    assert rows(manager) == [("SYSTEM", "Could not send LOGOFF to EDYY: timed out")]
    assert session.is_logged_on() is False


def test_a_vetoed_exit_keeps_the_logon(logger, message_boxes):
    message_boxes.answer = wx.NO
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)

    assert event.vetoed is True
    assert session.get_current_station() == STATION
    assert connection.sent == []


# --- a rejected logon code ----------------------------------------------------


def test_a_rejected_logon_code_forgets_the_dialogue(logger):
    window, session, _, _ = build(logger)
    session.handle_handover(STATION, "EDGG")

    window._on_link_change(LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")

    assert dialogue(session) == ("", None, "", 1)


# --- an outage is not a disconnect --------------------------------------------


def test_a_lost_and_restored_link_keeps_the_logon(logger):
    window, session, _, _ = build(logger)
    session.send_altitude_change_request("FL350")

    window._on_link_change(LinkState.DEGRADED, LinkState.LOST, "timed out")
    window._on_link_change(LinkState.LOST, LinkState.CONNECTED, None)

    assert dialogue(session) == (STATION, None, "", 2)


# --- File > Connect -----------------------------------------------------------


class FakeConnectDialog:
    """Stands in for ConnectDialog: answers OK with fixed details, never shows."""

    def __init__(self, parent):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_connection_details(self):
        return ("BAW123", "secret", "sayintentions")

    def Destroy(self):
        pass


def test_connecting_hands_the_identity_to_the_session(logger, monkeypatch):
    """A different callsign or network starts a clean dialogue; the session
    decides, the window only passes both on."""
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    window, session, connection, manager = build(logger)

    window.on_connect()

    assert connection.connected_as == ("BAW123", "sayintentions")
    assert (session.get_callsign(), session.network) == ("BAW123", "sayintentions")
    assert session.is_logged_on() is False
    assert window.polling_controller.started is True
    assert window.status_texts == ["Connected as BAW123."]
    assert rows(manager) == [("SYSTEM", "Connected as BAW123")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_session_lifecycle.py`
Expected: FAIL. The disconnect and exit tests fail on `dialogue(session)` (the station survives) or on the missing "Could not send LOGOFF" row; the connect test fails with `AttributeError: 'CpdlcSession' object has no attribute 'set_callsign'`; the fatal test fails on `previous_station`.

- [ ] **Step 3: Route the four paths through the session**

In `src/gui/main_window.py`:

In `on_connect`, replace

```python
                # Set callsign in session
                self.cpdlc_session.set_callsign(callsign)
```

with

```python
                # Hand the identity to the session; a different callsign or
                # network starts a clean dialogue, the same one keeps the logon
                self.cpdlc_session.begin_session(callsign, network_type)
```

In `on_disconnect`, replace the block from `self.logger.info("Disconnecting from CPDLC network")` down to `wx.MilliSleep(500)  # 500ms delay` with:

```python
        self.logger.info("Disconnecting from CPDLC network")
        self._cancel_pending_retry()
        self._end_dialogue()
```

Add after `on_disconnect`:

```python
    def _end_dialogue(self):
        """Log off from the current station, if any, then forget the dialogue.

        The session is reset whether or not the LOGOFF could be sent: after a
        disconnect the app must not believe it is still logged on (audit M-1).
        A LOGOFF that could not be sent gets a SYSTEM row, so the pilot knows
        the station was not told.
        """
        if self.cpdlc_session.is_logged_on():
            station = self.cpdlc_session.get_current_station()
            success, message = self.cpdlc_session.logoff()
            if success:
                if message:
                    self._add_custom_message(message)
            else:
                error_detail = f": {message}" if message else ""
                self.logger.warning(f"Could not send LOGOFF to {station}{error_detail}")
                self._add_custom_message(
                    f"Could not send LOGOFF to {station}{error_detail}", "SYSTEM"
                )

        self.cpdlc_session.reset()
```

In `_on_fatal_link_error`, replace

```python
        # Package 3 replaces these three lines with CpdlcSession.reset().
        self.cpdlc_session.current_station = ""
        self.cpdlc_session.pending_logon_min = None
        self.cpdlc_session.pending_logon_station = None
```

with

```python
        self.cpdlc_session.reset()
```

In `on_close`, replace

```python
            self.logger.info("Exit confirmed, performing clean disconnect")
            self._cancel_pending_retry()

            # If logged on to a station, send logoff message first
            if self.cpdlc_session.is_logged_on():
                success, message = self.cpdlc_session.send_logoff_message()
                if success and message:
                    self._add_custom_message(message)
```

with

```python
            self.logger.info("Exit confirmed, performing clean disconnect")
            self._cancel_pending_retry()
            self._end_dialogue()
```

In `src/model/cpdlc_session.py`, delete the `send_logoff_message` method (its docstring says it was kept for backward compatibility; the two callers above were the only ones).

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, ten more than after Task 5.

- [ ] **Step 5: Update the test README**

In `tests/README.md`:

- Replace the `test_cpdlc_session.py` row with `| \`test_cpdlc_session.py\` | Session state: logon acceptance and rejection, the handover window, pending expiry, reset and identity |`
- Replace the `test_logon_status.py` row with `| \`test_logon_status.py\` | Logon state as reported to the user, including a logon nobody answered |`
- Replace the `test_polling_controller.py` row with `| \`test_polling_controller.py\` | Poll intervals, the back-off ladder while the link is lost, batch delivery, the tick callback |`
- Add after the `test_polling_controller.py` row: `| \`test_session_lifecycle.py\` | Where the dialogue ends: disconnect, exit, a rejected logon code; and that a lost link is not one |`
- Replace the `test_uplink_handling.py` row with `| \`test_uplink_handling.py\` | HANDOVER, LOGOFF, LOGON REJECTED, protocol noise and auto-tune through the window, including the station that handed over |`
- In the `support.py` sentence, replace `\`make_main_window\`, ...` with `\`make_main_window\`, \`FakeClock\`, \`answerable\`, ...`.

- [ ] **Step 6: Commit**

```bash
git add src/gui/main_window.py src/model/cpdlc_session.py tests/support.py tests/test_session_lifecycle.py tests/README.md
git commit -m "End the dialogue on disconnect and exit, and start a clean one for a new identity"
```

---

## Self-review

- **Spec coverage.** `reset` (T1), `handle_handover` and `is_answerable_sender` (T2), `handle_logon_rejected` and `expire_pending` (T2), LOGOFF-first `logon` (T1, with deviation 1), `logoff`/`handle_handover` clearing the pending logon (T1/T2), `begin_session` replacing `set_callsign` (T1), the injectable clock (T1), the predicate through `MessageManager` and `MessageView` (T3), the `isinstance` gate, prefix match, rejection routing, `handle_handover` call and answerable-sender auto-tune in `_on_message_received` (T4), `tick_callback` and the "not answered" announcement (T5), `begin_session` on connect, the LOGOFF attempt with its row and the unconditional `reset()` on disconnect and exit, and `reset()` on the fatal path (T6). Spec tests: the window rule beside the strict-scoping tests and the log's handover sequence verbatim (T4), reset on disconnect with a failed LOGOFF (T6), no reset on a lost-and-restored link (T6), reset on a different callsign (T1, T6), logon while logged on (T1), rejection and expiry (T2, T4, T5), a telex reading LOGON ACCEPTED changing nothing (T4).
- **Placeholders.** None; every step carries its code.
- **Type consistency.** `handle_handover` returns `logon()`'s `(bool, str | None)` tuple and the window unpacks it the same way it unpacked `logon()`; `is_answerable_sender` is passed uncalled to `MessageView` and to `needs_acknowledgement` in every test; `FakeClock` is reached as `session.clock` everywhere; `expire_pending()` returns the station string the window formats.
