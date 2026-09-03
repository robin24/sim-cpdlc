# Package 2: Link Resilience and Message Integrity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A poll failure is reported honestly, never silently ends the session, and never loses a message the server has already handed over.

**Architecture:** `ConnectionManager.poll()` returns a `PollResult` (messages, undecodable uplinks captured from the library's warnings, failure count, server reason, fatal flag). A new `LinkState` derives CONNECTED / DEGRADED / LOST / FATAL from those results and owns a back-off ladder; `PollingController` feeds it every poll, follows the ladder while the link is lost, never stops on its own except on FATAL, and delivers every message of a batch even when one callback fails. `MainWindow` turns link transitions and unreadable uplinks into SYSTEM rows with the notification sound, tears the connection down on a rejected logon code, and retries a rate-limited acknowledgement once. The exception reporter moves into a small testable module that defers its dialog and never stacks a second one.

**Tech Stack:** Python 3.12+, wxPython 4.2.5, hoppie-connector 0.2.1, pytest 9.1.1 with pytest-timeout.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 216 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg2-link-resilience`, cut from `main` at `228e86b`, in its own git worktree. Never touch `C:\Claude\sim-cpdlc` itself.
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog (the autouse fixtures in `tests/conftest.py` enforce this; keep using `tests.support` doubles).
- Files this package may change: `src/model/connection_manager.py`, `src/controller/polling_controller.py`, `src/controller/link_state.py` (new), `src/gui/main_window.py`, `src/config.py`, `src/error_reporting.py` (new), `app.py`, and anything under `tests/`. Nothing else under `src/` changes.
- Exact values (from the spec): `LINK_BACKOFF_MS = (20000, 60000, 120000, 300000)`; `MAX_CONNECTION_FAILURES = 3` stays the LOST threshold; status texts are `"Connection problem (n/3) - retrying..."` (DEGRADED), `"Connection lost - retrying in N s"` (LOST), `"Connection restored."` (back to CONNECTED); SYSTEM rows are `"Connection lost, retrying"`, `"Connection restored"`, `"Connection problem: callsign already in use"`, `"Unreadable message from <sender>: <raw>"`, `"Disconnected: the server rejected the logon code"`; the rate-limit retry waits `RATE_LIMIT_RETRY_MS = 5000`.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 2". Audit: `docs/audit/2026-09-03-codebase-audit.md` (H-1, H-2, M-3, M-4, M-6, L-1).

## Deviations from the spec (decided while planning; the spec's "Package 2" section is otherwise followed)

1. **No ping-based re-verification.** The spec had `PollingController` call `attempt_reconnection()` (rebuild the connector, ping) on each LOST tick and a `record_reverify()` on `LinkState`. A `HoppieConnector` holds no connection state (each call is a fresh `requests` call), so rebuilding it proves nothing a poll does not, and a poll additionally delivers queued messages. While LOST the controller therefore keeps polling on the back-off ladder and a successful poll restores the link. `ConnectionManager.attempt_reconnection`, `should_attempt_reconnection`, `failure_count` and `poll_failed` become dead code and are removed (M-4's stuck-state-machine case disappears with them).
2. **"Connection restored" row and sound only after a loss.** A DEGRADED blip (one or two failed polls, then success) changes only the status bar; a SYSTEM row plus chime for every blip would be noise.
3. **No pull-forward while LOST.** `set_active_polling()` must not restart the pending poll while the ladder is active, or a send with 250 s of a 300 s rung elapsed would push the poll back to a fresh 300 s.
4. **The optional non-ASCII decode shim (M-2) is left out.** Six months of logs show no decode failure; the spec marked it optional.
5. **The exception reporter moves to `src/error_reporting.py`** so its deferral and coalescing can be tested; `app.py` only installs it.

---

## File structure

| File | Responsibility after this plan |
|---|---|
| `src/model/connection_manager.py` | Network boundary. `poll()` returns `PollResult`; `UnreadableMessage`, `unreadable_from_warning()`; inforeq envelope handling fixed; reconnection predicates removed. |
| `src/controller/link_state.py` (new) | `LinkState`: state derived from poll results, back-off ladder, transition callback. |
| `src/controller/polling_controller.py` | Timer state machine. Feeds `LinkState`, follows the ladder, delivers whole batches, status texts, `link_callback` / `unreadable_callback`. |
| `src/gui/main_window.py` | Link transitions → SYSTEM rows, sound, fatal teardown; unreadable rows; rate-limit retry; `_defer`, `_retry_later` seams. |
| `src/config.py` | `LINK_BACKOFF_MS`, `RATE_LIMIT_RETRY_MS`. |
| `src/error_reporting.py` (new) | `ExceptionReporter`: log, deferred single dialog, hook installation. |
| `app.py` | Installs `ExceptionReporter`. |
| `tests/support.py` | `FakeConnectionManager.poll()` with scripted results, `disconnect()`; `FakePollingController.stop()`; `FakeWeatherMonitor`, `FakeMenuItem`, `FakeSound`; `make_main_window` wires them plus `_defer`/`_retry_later` seams. |
| `tests/test_connection_manager.py`, `tests/test_polling_controller.py`, `tests/test_acknowledge_path.py`, `tests/test_main_window.py` | Updated for the new result type and behaviour. |
| `tests/test_link_state.py`, `tests/test_link_status.py`, `tests/test_error_reporting.py` (new) | The new units. |
| `tests/README.md` | Three new rows. |

---

### Task 1: `PollResult` — polls report what happened, including the uplinks the library dropped

**Files:**
- Modify: `src/model/connection_manager.py:1-16` (imports), `:76-92` (class docstring), `:273-308` (`poll`); add the dataclasses and `unreadable_from_warning` after `redact()` (after line 73)
- Modify: `src/controller/polling_controller.py:147-153` (read the new result type; nothing else yet)
- Modify: `tests/support.py:32-68` (`FakeConnectionManager` gains `poll()`)
- Modify: `tests/test_polling_controller.py:85-102, 184-200` (fakes return `PollResult`)
- Modify: `tests/test_connection_manager.py` (imports; the poll tests in the "failure counting" and "session state" sections)

**Interfaces:**
- Produces (used by every later task):
  - `UnreadableMessage(sender: str, raw: str)` dataclass, equality by value
  - `PollResult(ok: bool, messages: list = [], unreadable: list = [], reason: str | None = None, fatal: bool = False, failures: int = 0)` dataclass
  - `unreadable_from_warning(text: str) -> UnreadableMessage`
  - `ConnectionManager.poll() -> PollResult`; never raises; `failures` is the manager's consecutive poll-failure count after this poll (0 on success); `fatal` is True when the server reason contains "invalid logon"; a poll while disconnected returns `PollResult(ok=False, reason="Not connected", failures=<unchanged count>)` without counting
  - `FakeConnectionManager.poll_results: list[PollResult]` (served in order; a clean `PollResult(ok=True)` once empty)

- [ ] **Step 1: Write the failing tests**

In `tests/test_connection_manager.py` change the `src.model.connection_manager` import to:

```python
from src.model.connection_manager import (
    ConnectionManager,
    PollResult,
    UnreadableMessage,
    install_request_timeout,
    redact,
    unreadable_from_warning,
)
```

Replace the section from the comment `# --- failure counting drives reconnection ---` down to (and including) `test_a_rejected_message_is_not_counted_as_a_link_failure` with:

```python
# --- poll results -------------------------------------------------------------


def test_a_clean_poll_returns_its_messages(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "ok {EDUU cpdlc {/data2/5//WU/CLIMB TO FL350}}")

    result = cm.poll()

    assert result.ok is True
    assert [message.get_message() for message in result.messages] == ["CLIMB TO FL350"]
    assert (result.unreadable, result.failures, result.fatal, result.reason) == ([], 0, False, None)


def test_an_unparseable_uplink_is_reported_not_dropped(logger, monkeypatch):
    """hoppie_connector downgrades a message it cannot parse to a warning and
    drops it, after the server has already marked it delivered. The pilot has
    to be told something arrived."""
    cm = connected(logger, monkeypatch)
    serving(
        monkeypatch,
        "ok {EDUU cpdlc {/data2/5//WU/CLIMB TO FL350}}"
        " {EDUU cpdlc {/data2/6//R/QNH 1013 / TRL 70}}",
    )

    result = cm.poll()

    assert [message.get_message() for message in result.messages] == ["CLIMB TO FL350"]
    assert result.unreadable == [UnreadableMessage("EDUU", "/data2/6//R/QNH 1013 / TRL 70")]


def test_the_same_unreadable_shape_is_reported_every_time(logger, monkeypatch):
    """Python's default warning filter shows a repeated warning once per call
    site, which would make the second dropped message vanish again."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "ok {EDUU cpdlc {/data2/6//R/QNH 1013 / TRL 70}}")

    cm.poll()

    assert len(cm.poll().unreadable) == 1


def test_a_rejected_logon_code_is_fatal(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "error {invalid logon code}")

    result = cm.poll()

    assert (result.ok, result.fatal) == (False, True)
    assert "invalid logon code" in result.reason


def test_a_callsign_already_in_use_is_a_failure_with_its_reason(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "error {callsign already in use}")

    result = cm.poll()

    assert (result.ok, result.fatal, result.failures) == (False, False, 1)
    assert result.reason == "callsign already in use"


def test_polling_while_disconnected_counts_nothing(logger):
    cm = ConnectionManager(logger)

    result = cm.poll()

    assert (result.ok, result.reason, result.failures) == (False, "Not connected", 0)


def test_unreadable_from_warning_parses_the_library_text():
    text = (
        "Unable to parse {'from': 'EDUU', 'type': 'cpdlc', "
        "'packet': '/data2/6//R/QNH 1013 / TRL 70'}: Invalid CPDLC message format"
    )

    assert unreadable_from_warning(text) == UnreadableMessage(
        "EDUU", "/data2/6//R/QNH 1013 / TRL 70"
    )


def test_unreadable_from_warning_keeps_unexpected_text_whole():
    assert unreadable_from_warning("something else") == UnreadableMessage("?", "something else")


# --- failure counting ---------------------------------------------------------


def test_transport_failures_during_polling_are_counted(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    for _ in range(cm.max_connection_failures):
        result = cm.poll()

    assert cm.connection_failures == cm.max_connection_failures
    assert result.failures == cm.max_connection_failures


def test_an_unparseable_poll_response_also_counts(logger, monkeypatch):
    """This failure is not a transport error, so _call does not count it. If
    poll() did not count it either, a captive portal would look like a healthy
    link forever."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "<html>Login required</html>")

    for _ in range(cm.max_connection_failures):
        cm.poll()

    assert cm.connection_failures == cm.max_connection_failures


def test_poll_reports_failure_without_raising(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    result = cm.poll()

    assert (result.ok, result.failures) == (False, 1)


def test_a_successful_poll_clears_the_failure_count(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)
    cm.poll()

    serving(monkeypatch, "ok")
    result = cm.poll()

    assert (result.ok, result.failures, cm.connection_failures) == (True, 0, 0)


def test_send_failures_survive_a_successful_poll(logger, monkeypatch):
    """Proxies routinely pass GETs and block POSTs. Polls once reset the
    shared counter, so a link that could not send anything looked healthy."""
    cm = connected(logger, monkeypatch)

    for _ in range(cm.max_connection_failures):
        monkeypatch.setattr(requests, "post", responder("", status_code=502))
        with pytest.raises(HoppieError):
            cm.send_telex("EDDF", "HELLO")
        monkeypatch.setattr(requests, "get", responder("ok"))
        cm.poll()

    assert cm.send_failures == cm.max_connection_failures


def test_a_rejected_message_is_not_counted_as_a_link_failure(logger, monkeypatch):
    """The server was reachable and answered; the message was simply invalid."""
    cm = connected(logger, monkeypatch)

    with pytest.raises(HoppieError):
        cm.send_telex("EDDF", "A" * 221)

    assert cm.send_failures == 0
```

In the "session state" section replace `test_disconnect_clears_everything_connect_set`'s last assertion (`assert cm.should_attempt_reconnection() is False`) with `assert cm.connection_failures == 0`, and delete `test_no_reconnection_without_a_live_connection` entirely (the disconnected case is now `test_polling_while_disconnected_counts_nothing`).

In `test_a_failing_weather_request_does_not_trip_reconnection` replace the three assertions after `assert cm.info_failures == 3` with:

```python
    assert (cm.connection_failures, cm.send_failures) == (0, 0)
```

- [ ] **Step 2: Run the file to verify the new tests fail**

Run: `$PY -m pytest tests/test_connection_manager.py -q -p no:cacheprovider`
Expected: `ImportError: cannot import name 'PollResult'` at collection.

- [ ] **Step 3: Implement `PollResult` and the new `poll()`**

In `src/model/connection_manager.py` replace the import block (lines 1-16) with:

```python
"""Connection management for the CPDLC client."""

import ast
import functools
import re
import warnings
from dataclasses import dataclass, field

import requests

from hoppie_connector import HoppieConnector, HoppieError, HoppieWarning

from src.config import (
    SAYINTENTIONS_API_URL,
    HOPPIE_API_URL,
    MAX_CONNECTION_FAILURES,
    NETWORK_TIMEOUT,
)
from src.utils.weather_parsing import report_type_label, report_type_packet
```

After the `redact()` function (after line 73) add:

```python
_UNPARSEABLE_PATTERN = re.compile(r"^Unable to parse (\{.*\}): (.*)$", re.DOTALL)

# The server's reasons that no retry can fix. Matched case-insensitively
# against the reason text of a failed poll.
_FATAL_REASONS = ("invalid logon",)


@dataclass
class UnreadableMessage:
    """An uplink the server delivered but hoppie_connector could not decode."""

    sender: str
    raw: str


@dataclass
class PollResult:
    """What one poll produced.

    Attributes:
        ok: True if the server answered and the response parsed
        messages: HoppieMessage objects, in the order the server sent them
        unreadable: UnreadableMessage records for items the library dropped
        reason: Server reason or error text when the poll failed
        fatal: True when the reason is one no retry can fix
        failures: Consecutive failed polls, as counted by the manager, after
            this poll (0 after a success)
    """

    ok: bool
    messages: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    reason: str | None = None
    fatal: bool = False
    failures: int = 0


def unreadable_from_warning(text):
    """Recover sender and packet from hoppie_connector's "Unable to parse" warning.

    The library formats the warning as ``Unable to parse {<item dict>}: <error>``
    where the item dict is the poll entry ``{'from': ..., 'type': ..., 'packet':
    ...}``. Anything else is kept whole so nothing is lost.

    Args:
        text: The warning message

    Returns:
        UnreadableMessage: sender and raw packet, or "?" and the whole text
    """
    match = _UNPARSEABLE_PATTERN.match(text)
    if match:
        try:
            item = ast.literal_eval(match.group(1))
            return UnreadableMessage(str(item.get("from", "?")), str(item.get("packet", "")))
        except (ValueError, SyntaxError, AttributeError):
            pass
    return UnreadableMessage("?", text)
```

Replace the class docstring's last paragraph (lines 88-91, "Transport failures are also counted ... is no evidence the CPDLC link is down.") with:

```python
    Transport failures are also counted -- polls into connection_failures,
    sends into send_failures, and information requests into info_failures.
    poll() reports its count in the PollResult it returns; the link state
    machine in the polling controller decides what the count means. Weather
    runs on a worker thread and a failing ATIS is no evidence the CPDLC link
    is down, so info_failures gates nothing.
    """
```

Replace `poll()` (lines 273-308) with:

```python
    def poll(self):
        """Poll for new messages from the network.

        Never raises. Uplinks that hoppie_connector cannot parse are dropped by
        the library with a HoppieWarning after the server has already marked
        them delivered; they are captured here and reported as unreadable so
        the pilot can be told something arrived.

        Returns:
            PollResult: The messages, the unreadable items, and the failure
                state after this poll.
        """
        if not self.cnx:
            return PollResult(ok=False, reason="Not connected", failures=self.connection_failures)

        try:
            self.logger.debug("Polling for new messages")
            with warnings.catch_warnings(record=True) as caught:
                # "always": the default filter shows a repeated warning once
                # per call site, which would hide the second dropped message.
                warnings.simplefilter("always", HoppieWarning)
                messages, _delay = self._call(self.cnx.poll)
        except Exception as exc:
            # Deliberately broad: anything that escapes here would otherwise
            # skip the counter entirely and disable the link state for good.
            reason = redact(exc)
            self.logger.error(f"Poll error: {reason}")
            if not getattr(exc, "is_transport", False):
                # _call already counted transport failures. A poll carries no
                # user input, so any other failure -- an unparseable body from a
                # captive portal, a server-side error -- is equally a dead link.
                self.connection_failures += 1
                self.logger.warning(
                    f"Connection failure count: {self.connection_failures}/{self.max_connection_failures}"
                )
            fatal = any(marker in reason.lower() for marker in _FATAL_REASONS)
            return PollResult(
                ok=False, reason=reason, fatal=fatal, failures=self.connection_failures
            )

        unreadable = [
            unreadable_from_warning(str(warning.message))
            for warning in caught
            if issubclass(warning.category, HoppieWarning)
        ]
        for item in unreadable:
            self.logger.error(f"Unreadable message from {item.sender}: {item.raw}")

        if self.connection_failures > 0:
            self.logger.debug(
                f"Resetting connection failures from {self.connection_failures} to 0"
            )
        self.connection_failures = 0

        return PollResult(ok=True, messages=messages, unreadable=unreadable)
```

In `src/controller/polling_controller.py` replace lines 148-152 (the inner `try` around `poll()`) with:

```python
            try:
                result = self.connection_manager.poll()
            except Exception as e:
                self.logger.error(f"Unexpected error during poll: {e}")
                return
            messages = result.messages
```

(the rest of the handler keeps using `messages`; `poll_status` is gone).

- [ ] **Step 4: Update the test doubles**

In `tests/support.py` add `from src.model.connection_manager import PollResult` after the `src.config` import, and in `FakeConnectionManager.__init__` add `self.poll_results = []`, then add after `send_info_request`:

```python
    def poll(self):
        """Serve the next scripted PollResult, or a clean empty poll."""
        if self.poll_results:
            return self.poll_results.pop(0)
        return PollResult(ok=True)
```

In `tests/test_polling_controller.py` add `from src.model.connection_manager import PollResult` after the `PollingController` import, and change the two fakes' `poll()` bodies:

```python
    def poll(self):
        self.polls += 1
        return PollResult(ok=True, messages=["UPLINK"])
```

```python
    def poll(self):
        return PollResult(ok=True, messages=[self.message])
```

(leave their `poll_failed`/`should_attempt_reconnection` methods in place; Task 3 removes them.)

- [ ] **Step 5: Run the touched files, then the suite**

Run: `$PY -m pytest tests/test_connection_manager.py tests/test_polling_controller.py -q -p no:cacheprovider`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: green (216 − 1 deleted + 8 new = 223 passed).

- [ ] **Step 6: Commit**

```bash
git add src/model/connection_manager.py src/controller/polling_controller.py tests/support.py tests/test_polling_controller.py tests/test_connection_manager.py
git commit -m "Report what a poll produced, including the uplinks the library dropped

poll() returns a PollResult instead of a tuple: the messages, the items
hoppie_connector could not parse (captured from its warnings, which the
packaged build otherwise sends nowhere), the server reason, whether that
reason is fatal, and the failure count after the poll.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `LinkState` — link health and the back-off ladder

**Files:**
- Create: `src/controller/link_state.py`
- Create: `tests/test_link_state.py`
- Modify: `src/config.py:111-112` (add the two constants after `MAX_CONNECTION_FAILURES`)

**Interfaces:**
- Consumes: `PollResult` from Task 1.
- Produces:
  - `LinkState.CONNECTED / DEGRADED / LOST / FATAL` string constants
  - `LinkState(on_change=None, max_failures=MAX_CONNECTION_FAILURES, backoff_ms=LINK_BACKOFF_MS)`
  - `record_poll(result: PollResult) -> bool` (True when the state changed; calls `on_change(old, new, reason)` on a change)
  - `next_delay_ms() -> int | None` (ladder delay while LOST, else None)
  - `reset() -> None` (back to CONNECTED without firing `on_change`)
  - attributes `state`, `failures`, `reason`, `max_failures`
  - `config.LINK_BACKOFF_MS = (20000, 60000, 120000, 300000)`, `config.RATE_LIMIT_RETRY_MS = 5000`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_state.py`:

```python
"""Tests for the link state machine and its back-off ladder."""

from src.config import LINK_BACKOFF_MS, MAX_CONNECTION_FAILURES
from src.controller.link_state import LinkState
from src.model.connection_manager import PollResult

OK = PollResult(ok=True)


def failed(count, reason="timed out", fatal=False):
    return PollResult(ok=False, reason=reason, fatal=fatal, failures=count)


def make():
    changes = []
    link = LinkState(on_change=lambda old, new, reason: changes.append((old, new, reason)))
    return link, changes


def test_the_link_starts_connected():
    link, changes = make()

    assert (link.state, link.failures, link.next_delay_ms(), changes) == (
        LinkState.CONNECTED, 0, None, []
    )


def test_the_first_failures_degrade_the_link():
    link, changes = make()

    assert link.record_poll(failed(1)) is True
    assert link.record_poll(failed(2)) is False

    assert (link.state, link.failures, link.reason) == (LinkState.DEGRADED, 2, "timed out")
    assert changes == [(LinkState.CONNECTED, LinkState.DEGRADED, "timed out")]
    assert link.next_delay_ms() is None


def test_the_third_failure_loses_the_link_and_starts_the_ladder():
    link, changes = make()

    for count in range(1, MAX_CONNECTION_FAILURES + 1):
        link.record_poll(failed(count))

    assert link.state == LinkState.LOST
    assert link.next_delay_ms() == LINK_BACKOFF_MS[0] == 20000
    assert changes[-1] == (LinkState.DEGRADED, LinkState.LOST, "timed out")


def test_each_further_failure_climbs_the_ladder_to_its_cap():
    link, changes = make()
    for count in range(1, 4):
        link.record_poll(failed(count))

    delays = []
    for count in range(4, 9):
        link.record_poll(failed(count))
        delays.append(link.next_delay_ms())

    assert delays == [60000, 120000, 300000, 300000, 300000]
    assert link.state == LinkState.LOST
    assert len(changes) == 2, "climbing the ladder is not a transition"


def test_a_successful_poll_restores_the_link_and_resets_the_ladder():
    link, changes = make()
    for count in range(1, 6):
        link.record_poll(failed(count))

    assert link.record_poll(OK) is True

    assert (link.state, link.failures, link.reason, link.next_delay_ms()) == (
        LinkState.CONNECTED, 0, None, None
    )
    assert changes[-1] == (LinkState.LOST, LinkState.CONNECTED, None)

    for count in range(1, 4):
        link.record_poll(failed(count))
    assert link.next_delay_ms() == 20000, "the ladder starts over after a recovery"


def test_a_fatal_result_wins_from_any_state():
    link, changes = make()
    link.record_poll(failed(1))

    link.record_poll(failed(2, "invalid logon code", fatal=True))

    assert link.state == LinkState.FATAL
    assert link.next_delay_ms() is None
    assert changes[-1] == (LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")


def test_reset_returns_to_connected_without_announcing_it():
    link, changes = make()
    for count in range(1, 4):
        link.record_poll(failed(count))
    announced = len(changes)

    link.reset()

    assert (link.state, link.failures, link.next_delay_ms()) == (LinkState.CONNECTED, 0, None)
    assert len(changes) == announced


def test_the_threshold_and_ladder_are_configurable():
    link = LinkState(max_failures=2, backoff_ms=(5, 10))

    link.record_poll(failed(1))
    assert link.state == LinkState.DEGRADED
    link.record_poll(failed(2))
    assert (link.state, link.next_delay_ms()) == (LinkState.LOST, 5)
    link.record_poll(failed(3))
    assert link.next_delay_ms() == 10
    link.record_poll(failed(4))
    assert link.next_delay_ms() == 10
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$PY -m pytest tests/test_link_state.py -q -p no:cacheprovider`
Expected: `ImportError: cannot import name 'LINK_BACKOFF_MS'`.

- [ ] **Step 3: Add the constants and the module**

In `src/config.py`, directly after `MAX_CONNECTION_FAILURES = 3` (line 112) add:

```python

# Once the link is lost (MAX_CONNECTION_FAILURES consecutive failed polls) the
# next polls wait these long, in order, staying on the last value until a poll
# succeeds. Polling never stops on its own: a six-minute outage must not end
# the session.
LINK_BACKOFF_MS = (20000, 60000, 120000, 300000)

# SayIntentions answers "rate_limit" to a second message sent within a few
# seconds of the first. A rate-limited acknowledgement is retried once after
# this delay.
RATE_LIMIT_RETRY_MS = 5000
```

Create `src/controller/link_state.py`:

```python
"""Link health derived from poll results, with a back-off ladder while lost.

Neither Hoppie nor SayIntentions keeps a connection open: every poll is a
fresh HTTP request, so the only evidence about the link is whether the last
few polls succeeded. This class turns that evidence into four states and, while
the link is lost, tells the polling controller how long to wait before trying
again.
"""

from src.config import LINK_BACKOFF_MS, MAX_CONNECTION_FAILURES


class LinkState:
    """Four states, driven by successive PollResults.

    CONNECTED: the last poll succeeded.
    DEGRADED: one or more polls failed, fewer than max_failures in a row.
    LOST: max_failures or more in a row; the back-off ladder is active.
    FATAL: the server rejected the logon code; no retry can fix that.
    """

    CONNECTED = "connected"
    DEGRADED = "degraded"
    LOST = "lost"
    FATAL = "fatal"

    def __init__(self, on_change=None, max_failures=MAX_CONNECTION_FAILURES, backoff_ms=LINK_BACKOFF_MS):
        """Initialize the state machine.

        Args:
            on_change: Callback(old_state, new_state, reason) run on every
                transition, with the poll's reason text (None on recovery)
            max_failures: Consecutive failed polls that lose the link
            backoff_ms: Delays before the next poll while lost, climbed one
                rung per further failure and held at the last value
        """
        self.on_change = on_change
        self.max_failures = max_failures
        self.backoff_ms = tuple(backoff_ms)
        self.state = self.CONNECTED
        self.failures = 0
        self.reason = None
        self._rung = 0

    def reset(self):
        """Return to CONNECTED without announcing it, for a new session."""
        self.state = self.CONNECTED
        self.failures = 0
        self.reason = None
        self._rung = 0

    def record_poll(self, result):
        """Fold one poll into the state.

        Args:
            result: The PollResult the connection manager returned

        Returns:
            bool: True if the state changed
        """
        if result.fatal:
            new_state = self.FATAL
        elif result.ok:
            new_state = self.CONNECTED
        elif result.failures >= self.max_failures:
            new_state = self.LOST
        else:
            new_state = self.DEGRADED

        self.failures = 0 if result.ok else result.failures
        self.reason = None if result.ok else result.reason

        if new_state == self.LOST and self.state == self.LOST:
            self._rung = min(self._rung + 1, len(self.backoff_ms) - 1)
        else:
            self._rung = 0

        if new_state == self.state:
            return False

        old_state, self.state = self.state, new_state
        if self.on_change:
            self.on_change(old_state, new_state, self.reason)
        return True

    def next_delay_ms(self):
        """Return the back-off delay for the next poll, or None when not lost."""
        if self.state != self.LOST:
            return None
        return self.backoff_ms[self._rung]
```

- [ ] **Step 4: Run the new tests and the suite**

Run: `$PY -m pytest tests/test_link_state.py -q -p no:cacheprovider`
Expected: `8 passed`.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `231 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/controller/link_state.py tests/test_link_state.py
git commit -m "Add LinkState: link health from poll results, with a back-off ladder

Three consecutive failed polls lose the link; each further failure climbs
20 s, 60 s, 120 s, 300 s and stays there; any successful poll restores it
and a rejected logon code is fatal. The controller adopts it next.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The polling controller follows the link state and never gives up on its own

**Files:**
- Modify: `src/controller/polling_controller.py` (whole file; the complete new content is below)
- Modify: `src/model/connection_manager.py:310-350` (remove `failure_count`, `poll_failed`, `should_attempt_reconnection`, `attempt_reconnection`)
- Modify: `tests/test_polling_controller.py` (fakes lose their two stub methods; new tests appended)
- Modify: `tests/test_connection_manager.py:207-224` (the two `attempt_reconnection` tests are removed; section comment renamed)

**Interfaces:**
- Consumes: `LinkState`, `PollResult`, `UnreadableMessage`.
- Produces:
  - `PollingController(logger, connection_manager, message_callback=None, default_poll_interval=60000, active_poll_interval=20000, inactivity_timeout=300000, poll_interval_range=None, link_callback=None, unreadable_callback=None)`
  - `poller.link: LinkState`; `link_callback(old, new, reason)` is called on every transition after the controller has set its own status text; `unreadable_callback(list[UnreadableMessage])` is called once per poll that had any
  - Status texts: DEGRADED `"Connection problem (n/3) - retrying..."`, LOST `"Connection lost - retrying in N s"` (refreshed every LOST tick), restored `"Connection restored."`
  - Behaviour: a LOST tick schedules the next poll after `link.next_delay_ms()`; FATAL stops the timer; the message loop continues past a failing callback and re-raises the first error after the batch; `set_active_polling()` leaves a pending poll alone while LOST

- [ ] **Step 1: Write the failing tests**

In `tests/test_polling_controller.py` remove the `poll_failed` and `should_attempt_reconnection` methods from `RaisingConnection` and `ClearanceConnection`, change the connection-manager import line to `from src.model.connection_manager import PollResult, UnreadableMessage`, add `from src.controller.link_state import LinkState` after it, and append:

```python
# --- link state and back-off --------------------------------------------------


class ScriptedConnection:
    """Connected; serves a scripted sequence of poll results, then clean polls."""

    def __init__(self, *results):
        self.results = list(results)
        self.polls = 0

    def is_connected(self):
        return True

    def poll(self):
        self.polls += 1
        return self.results.pop(0) if self.results else PollResult(ok=True)


def failed(count, reason="timed out", fatal=False):
    return PollResult(ok=False, reason=reason, fatal=fatal, failures=count)


def tick(poller):
    """Run one timer tick the way wx would: the one-shot has already stopped."""
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)


def test_three_failed_polls_lose_the_link_and_start_the_back_off_ladder(logger, frame):
    """The Jul 17 outage in the maintainer's log lasted six minutes and cleared
    by itself; the old controller would have stopped polling after two."""
    statuses = []
    frame.SetStatusText = statuses.append
    transitions = []
    poller = PollingController(
        logger,
        ScriptedConnection(*[failed(count) for count in range(1, 8)]),
        link_callback=lambda old, new, reason: transitions.append((old, new)),
    )
    poller.start(frame)

    intervals = []
    for _ in range(7):
        tick(poller)
        intervals.append(poller.poll_timer.GetInterval())

    assert all(45000 <= interval <= 75000 for interval in intervals[:2])
    assert intervals[2:] == [20000, 60000, 120000, 300000, 300000]
    assert transitions == [
        (LinkState.CONNECTED, LinkState.DEGRADED),
        (LinkState.DEGRADED, LinkState.LOST),
    ]
    assert statuses[:3] == [
        "Connection problem (1/3) - retrying...",
        "Connection problem (2/3) - retrying...",
        "Connection lost - retrying in 20 s",
    ]
    assert statuses[-1] == "Connection lost - retrying in 300 s"
    assert poller.is_running() is True


def test_a_successful_poll_restores_a_lost_link(logger, frame):
    statuses = []
    frame.SetStatusText = statuses.append
    transitions = []
    poller = PollingController(
        logger,
        ScriptedConnection(failed(1), failed(2), failed(3)),
        link_callback=lambda old, new, reason: transitions.append((old, new)),
    )
    poller.start(frame)

    for _ in range(4):
        tick(poller)

    assert transitions[-1] == (LinkState.LOST, LinkState.CONNECTED)
    assert statuses[-1] == "Connection restored."
    assert 45000 <= poller.poll_timer.GetInterval() <= 75000
    assert poller.is_running() is True


def test_a_rejected_logon_code_stops_polling_for_good(logger, frame):
    transitions = []
    poller = PollingController(
        logger,
        ScriptedConnection(failed(1, "invalid logon code", fatal=True)),
        link_callback=lambda old, new, reason: transitions.append((old, new, reason)),
    )
    poller.start(frame)

    tick(poller)

    assert transitions == [(LinkState.CONNECTED, LinkState.FATAL, "invalid logon code")]
    assert poller.is_running() is False


def test_activity_does_not_shorten_the_back_off_while_the_link_is_lost(logger, frame):
    """Restarting the pending poll would push it back by a whole rung: with
    250 s of a 300 s wait elapsed, a send would make it 300 s again."""
    poller = PollingController(logger, ScriptedConnection(failed(1), failed(2), failed(3)))
    poller.start(frame)
    for _ in range(3):
        tick(poller)
    deadline = poller._next_poll_at

    poller.set_active_polling()

    assert poller._next_poll_at == deadline


def test_a_failing_callback_does_not_lose_the_rest_of_the_batch(logger, frame):
    """The server has already marked the whole batch relayed."""
    delivered = []

    def callback(message):
        delivered.append(message)
        if message == "FIRST":
            raise RuntimeError("boom")

    poller = PollingController(
        logger, ScriptedConnection(PollResult(ok=True, messages=["FIRST", "SECOND"])), callback
    )
    poller.start(frame)

    with pytest.raises(RuntimeError):
        tick(poller)

    assert delivered == ["FIRST", "SECOND"]
    assert poller.is_running() is True


def test_unreadable_uplinks_reach_their_own_callback(logger, frame):
    unreadable = [UnreadableMessage("EDGG", "/data2/6//R/QNH 1013 / TRL 70")]
    received = []
    poller = PollingController(
        logger,
        ScriptedConnection(PollResult(ok=True, unreadable=unreadable)),
        unreadable_callback=received.extend,
    )
    poller.start(frame)

    tick(poller)

    assert received == unreadable


def test_start_forgets_the_previous_sessions_link_state(logger, frame):
    poller = PollingController(logger, ScriptedConnection(failed(1), failed(2), failed(3)))
    poller.start(frame)
    for _ in range(3):
        tick(poller)
    poller.stop()

    poller.start(frame)

    assert poller.link.state == LinkState.CONNECTED
    assert 45000 <= poller.poll_timer.GetInterval() <= 75000
```

In `tests/test_connection_manager.py` delete `test_reconnection_reports_failure_when_the_server_is_still_down` and `test_reconnection_succeeds_once_the_server_recovers` (lines 207-224) and rename the section comment above them to `# --- connect actually verifies the link ---------------------------------------`.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `$PY -m pytest tests/test_polling_controller.py -q -p no:cacheprovider`
Expected: the new tests fail (`TypeError: ... unexpected keyword argument 'link_callback'`, and `AttributeError: 'ScriptedConnection' object has no attribute 'poll_failed'` from the old handler).

- [ ] **Step 3: Replace `src/controller/polling_controller.py`**

```python
"""Controller for managing CPDLC polling behavior."""

import random
import time
import wx

from hoppie_connector import HoppieMessage, CpdlcMessage, TelexMessage
from src.config import MAX_POLL_INTERVAL, MIN_POLL_INTERVAL
from src.controller.link_state import LinkState
from src.model.connection_manager import ConnectionManager
from src.model.message_manager import CPDLC_RESPONSES
from src.utils.message_formatting import extract_message_content


class PollingController:
    """Controls polling behavior for CPDLC communications.

    Hoppie asks clients to poll "once between every 45 and 75 seconds, randomly
    timed so that the average server load is stable", and allows a faster
    once-per-20-seconds burst while a reply is expected. Each tick therefore
    schedules the next one itself rather than running on a fixed repeat, so the
    idle interval can be re-randomised every time.

    Link health lives in a LinkState fed with every poll result. While the link
    is lost the tick interval follows its back-off ladder, and a successful poll
    restores it. Polling never stops on its own except when the server rejects
    the logon code, which no retry can fix.
    """

    def __init__(
        self,
        logger,
        connection_manager: ConnectionManager,
        message_callback=None,
        default_poll_interval=60000,  # 60 seconds
        active_poll_interval=20000,  # 20 seconds
        inactivity_timeout=300000,  # 5 minutes
        poll_interval_range=None,
        link_callback=None,
        unreadable_callback=None,
    ):
        """Initialize the polling controller.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            message_callback: Callback for received messages
            default_poll_interval: Nominal idle interval in milliseconds, used
                only when a jitter range is not available
            active_poll_interval: Interval used while a reply is expected
            inactivity_timeout: How long to stay in the faster mode after the
                last activity, in milliseconds
            poll_interval_range: (minimum, maximum) idle interval in
                milliseconds that each idle poll is randomised within
            link_callback: Callback(old_state, new_state, reason) for every
                link transition, after the status bar has been updated
            unreadable_callback: Callback(list of UnreadableMessage) for
                uplinks the library could not decode
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.message_callback = message_callback
        self.link_callback = link_callback
        self.unreadable_callback = unreadable_callback
        self.default_poll_interval = default_poll_interval
        self.active_poll_interval = active_poll_interval
        self.inactivity_timeout = inactivity_timeout
        self.poll_interval_range = poll_interval_range or (
            MIN_POLL_INTERVAL,
            MAX_POLL_INTERVAL,
        )
        self.last_activity_time = 0
        self.poll_timer = None
        # When the pending one-shot is due, as time.monotonic(). wx.Timer
        # cannot report how much of a one-shot interval remains, so
        # set_active_polling() needs this to tell a poll that is already
        # imminent from one that is a minute off.
        self._next_poll_at = None
        self._active_mode = False
        self._stopped = True
        self.parent_window = None
        self.link = LinkState(on_change=self._on_link_change)

    def next_interval(self):
        """Return the delay to wait before the next poll.

        Returns:
            int: Milliseconds until the next poll. Fixed while a reply is
                expected, randomised within the permitted band otherwise.
        """
        if self._active_mode:
            return self.active_poll_interval

        minimum, maximum = self.poll_interval_range
        if minimum >= maximum:
            return minimum
        return random.randint(minimum, maximum)

    def is_active_mode(self):
        """Check whether the faster polling rate is currently in use."""
        return self._active_mode

    def start(self, parent_window):
        """Start the polling timer.

        Args:
            parent_window: The parent window for the timer
        """
        self.parent_window = parent_window
        if self.poll_timer is None:
            self.poll_timer = wx.Timer(parent_window)
            parent_window.Bind(wx.EVT_TIMER, self.on_poll_timer, self.poll_timer)

        self._active_mode = False
        self._stopped = False
        self.link.reset()
        self._schedule_next()
        self.logger.info(
            "Started polling timer, idle interval randomised between "
            f"{self.poll_interval_range[0]}ms and {self.poll_interval_range[1]}ms"
        )

    def stop(self):
        """Stop the polling timer."""
        self._stopped = True
        self._next_poll_at = None
        if self.poll_timer and self.poll_timer.IsRunning():
            self.poll_timer.Stop()
            self.logger.info("Stopped polling timer")

    def is_running(self):
        """Check if the polling timer is running.

        Returns:
            bool: True if running, False otherwise
        """
        return bool(self.poll_timer and self.poll_timer.IsRunning())

    def _schedule_next(self):
        """Arrange the next poll, unless polling has been stopped.

        While the link is lost the LinkState's back-off ladder decides the
        delay; otherwise the active or randomised idle interval does.
        """
        if self._stopped or self.poll_timer is None:
            return

        delay = self.link.next_delay_ms()
        interval = delay if delay is not None else self.next_interval()
        self._next_poll_at = time.monotonic() + interval / 1000
        self.poll_timer.StartOnce(interval)
        self.logger.debug(f"Next poll in {interval}ms")

    def on_poll_timer(self, event):
        """Handle poll timer event."""
        if not self.connection_manager.is_connected():
            self.logger.warning("Connection lost, stopping poll timer")
            self.stop()
            return

        # The timer is one-shot, so the next tick only happens if this handler
        # arranges it. Message handling reaches into the GUI, SimConnect and a
        # nested logon, so anything raising there would otherwise end polling
        # for the rest of the session. stop() sets _stopped, so the fatal
        # branch below still ends polling deliberately.
        try:
            result = self.connection_manager.poll()
            self.link.record_poll(result)
            self._show_link_status()

            if self.link.state == LinkState.FATAL:
                # The server rejected the logon code. The link callback has
                # already let the window tear the connection down.
                self.stop()
                return

            self._deliver(result)
            self.check_polling_timeout()
        finally:
            self._schedule_next()

    def _deliver(self, result):
        """Hand every message of a poll to the callbacks.

        The server marked the whole batch relayed when it served it, so a
        callback failing on one message must not cost the others. The first
        error is re-raised after the batch so it still reaches the reporter.

        Args:
            result: The PollResult being processed
        """
        first_error = None

        if result.messages:
            self.logger.info(f"Received {len(result.messages)} new message(s)")
        for message in result.messages:
            self.logger.info(f"Received message: {message}")
            if self.message_callback:
                try:
                    self.message_callback(message)
                except Exception as exc:
                    # app.spec builds with console=False, so without this the
                    # traceback reaches neither the log file nor the pilot.
                    self.logger.exception("Error in message callback")
                    if first_error is None:
                        first_error = exc

            # Check if this message should trigger faster polling
            if self.should_increase_polling_rate(message):
                self.set_active_polling()

        if result.unreadable and self.unreadable_callback:
            try:
                self.unreadable_callback(result.unreadable)
            except Exception as exc:
                self.logger.exception("Error in unreadable-message callback")
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error

    def _set_status(self, text):
        """Show a short connection message in the parent window's status bar."""
        if self.parent_window and hasattr(self.parent_window, "SetStatusText"):
            self.parent_window.SetStatusText(text)

    def _on_link_change(self, old_state, new_state, reason):
        """React to a link transition: the status bar first, then the window."""
        if new_state == LinkState.CONNECTED and old_state != LinkState.CONNECTED:
            self._set_status("Connection restored.")
        if self.link_callback:
            self.link_callback(old_state, new_state, reason)

    def _show_link_status(self):
        """Keep the status bar honest about a degraded or lost link.

        The failure count and the back-off delay move between ticks without a
        state transition, so this runs after every poll rather than only in
        _on_link_change.
        """
        if self.link.state == LinkState.DEGRADED:
            self._set_status(
                f"Connection problem ({self.link.failures}/{self.link.max_failures}) - retrying..."
            )
        elif self.link.state == LinkState.LOST:
            self._set_status(
                f"Connection lost - retrying in {self.link.next_delay_ms() // 1000} s"
            )

    def set_active_polling(self):
        """Switch to more frequent polling during active communication."""
        was_active = self._active_mode
        self._active_mode = True

        # Update the last activity timestamp
        self.last_activity_time = time.time()
        self.logger.debug(f"Updated last activity time: {self.last_activity_time}")

        if not was_active:
            self.logger.debug(
                f"Switching to active polling interval: {self.active_poll_interval}ms"
            )

        # Bring the next poll forward if it is further off than the active
        # rate, and otherwise leave it alone. Restarting unconditionally would
        # push a poll that is nearly due out to a fresh active interval, so a
        # pilot acting faster than that interval would never get one at all.
        if not self.is_running() or self._next_poll_at is None:
            return

        if self.link.state == LinkState.LOST:
            # The pending poll sits on the back-off ladder; restarting it
            # would push it back by a whole rung.
            return

        if self._next_poll_at - time.monotonic() > self.active_poll_interval / 1000:
            self.poll_timer.Stop()
            self._schedule_next()

    def check_polling_timeout(self):
        """Check if we should return to default polling after period of inactivity."""
        if not self._active_mode:
            return

        current_time = time.time()
        elapsed = current_time - self.last_activity_time
        elapsed_ms = elapsed * 1000  # Convert seconds to milliseconds

        # If more than inactivity_timeout has passed, return to default polling
        if elapsed_ms > self.inactivity_timeout:
            self.logger.info(
                f"Inactivity timeout reached ({elapsed:.1f}s). Returning to the "
                "randomised idle polling interval"
            )
            self._active_mode = False

    def should_increase_polling_rate(self, message):
        """Determine if this message should trigger faster polling.

        Args:
            message: The message to check

        Returns:
            bool: True if polling rate should be increased, False otherwise
        """
        # Don't increase polling for acknowledgements or telex messages
        if not isinstance(message, HoppieMessage):
            return False

        # For telex messages
        if isinstance(message, TelexMessage):
            return False

        # For CPDLC acknowledgements (WILCO, UNABLE, ROGER, etc.)
        if isinstance(message, CpdlcMessage):
            content = message.get_packet_content()
            if content:
                clean_content = extract_message_content(content)

                # If the message only contains an acknowledgement, don't
                # increase polling. CPDLC_RESPONSES is shared with
                # MessageManager so the two lists cannot drift apart.
                if clean_content in CPDLC_RESPONSES:
                    return False

        # For all other message types, increase polling rate
        return True
```

- [ ] **Step 4: Remove the dead reconnection API from `ConnectionManager`**

In `src/model/connection_manager.py` delete the four methods `failure_count`, `poll_failed`, `should_attempt_reconnection` and `attempt_reconnection` (the block from `def failure_count(self):` through the end of `attempt_reconnection`, originally lines 310-350). Nothing in `src/` calls them any more (check with `grep -rn "attempt_reconnection\|should_attempt_reconnection\|failure_count\|poll_failed" src tests` — the only remaining hits must be none).

- [ ] **Step 5: Run the touched files, then the suite**

Run: `$PY -m pytest tests/test_polling_controller.py tests/test_connection_manager.py -q -p no:cacheprovider`
Expected: all pass, including the pre-existing `test_a_poll_that_raises_still_schedules_the_next_one` (the batch loop now re-raises after the loop) and `test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once`.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `236 passed` (231 − 2 deleted + 7 new).

- [ ] **Step 6: Commit**

```bash
git add src/controller/polling_controller.py src/model/connection_manager.py tests/test_polling_controller.py tests/test_connection_manager.py
git commit -m "Keep polling through an outage on a back-off ladder

Three failed polls no longer end the session: the controller follows
LinkState, waits 20 s, 60 s, 120 s, 300 s between attempts while the link
is lost, and returns to the idle band as soon as a poll succeeds. Only a
rejected logon code stops the timer. A batch is delivered in full even
when one message's callback fails, and unreadable uplinks get a callback
of their own. Rebuilding the stateless connector proved nothing a poll
does not, so attempt_reconnection and its predicates go.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The window announces link changes and tears down on a rejected logon code

**Files:**
- Modify: `src/gui/main_window.py:26-31` (import `LinkState`), `:106-113` (controller construction), add four methods after `_on_weather_error` (after line 796)
- Modify: `tests/support.py` (`FakeConnectionManager.disconnect`, `FakePollingController.stop`, `FakeWeatherMonitor`, `FakeMenuItem`, `FakeSound`, `make_main_window` wiring)
- Create: `tests/test_link_status.py`
- Modify: `tests/test_main_window.py` (one wiring test appended to the guards section)

**Interfaces:**
- Consumes: `LinkState`, `UnreadableMessage`, `PollingController(link_callback=, unreadable_callback=)`.
- Produces:
  - `MainWindow._on_link_change(old, new, reason)`, `MainWindow._on_unreadable_messages(unreadable)`, `MainWindow._on_fatal_link_error(reason)`, `MainWindow._defer(callback, *args, **kwargs)` (wx.CallAfter; replaced by a direct call in `make_main_window`)
  - Test doubles: `FakeConnectionManager.disconnect()` sets `.disconnected = True` and `is_connected()` False; `FakePollingController.stop()` sets `.stopped = True`; `FakeWeatherMonitor` with `stop()`/`clear()` setting `.stopped`/`.cleared`; `FakeMenuItem` with `SetItemLabel(label)`/`SetHelp(text)` recording `.label`/`.help`; `FakeSound` with `Play(flags)` counting `.played`; `make_main_window` sets `window.connection_manager = cpdlc_session.connection_manager`, `window.weather_monitor`, `window.menu_item_connect`, `window.new_message_sound = FakeSound()`, `window._defer`

- [ ] **Step 1: Extend the test doubles**

In `tests/support.py`:

Add to `FakeConnectionManager.__init__`: `self.disconnected = False`, and the method:

```python
    def disconnect(self):
        self._connected = False
        self.disconnected = True
```

Replace `FakePollingController` with:

```python
class FakePollingController:
    """Records polling-rate changes and stops without owning a wx.Timer."""

    def __init__(self):
        self.active_calls = 0
        self.stopped = False

    def set_active_polling(self):
        self.active_calls += 1

    def stop(self):
        self.stopped = True
```

After `FakeSimConnectManager` add:

```python
class FakeWeatherMonitor:
    """Records the lifecycle calls the window makes on the weather monitor."""

    def __init__(self):
        self.stopped = False
        self.cleared = False

    def stop(self):
        self.stopped = True

    def clear(self):
        self.cleared = True


class FakeMenuItem:
    """Records the label and help text the window sets on a menu item."""

    def __init__(self, label="&Disconnect"):
        self.label = label
        self.help = ""

    def SetItemLabel(self, label):
        self.label = label

    def SetHelp(self, text):
        self.help = text


class FakeSound:
    """Counts the notification chimes instead of playing them."""

    def __init__(self):
        self.played = 0

    def Play(self, flags=0):
        self.played += 1
        return True
```

In `make_main_window`, replace the block from `window.polling_controller = FakePollingController()` to `window.new_message_sound = None` with:

```python
    window.connection_manager = cpdlc_session.connection_manager
    window.polling_controller = FakePollingController()
    window.weather_monitor = FakeWeatherMonitor()
    window.menu_item_connect = FakeMenuItem()
    window.simconnect_manager = (
        simconnect if simconnect is not None else FakeSimConnectManager()
    )
    window.new_message_sound = FakeSound()
    # wx.CallAfter needs a running wx.App; run deferred callbacks at once.
    window._defer = lambda callback, *args, **kwargs: callback(*args, **kwargs)
```

and extend the docstring's Args with `simconnect` unchanged plus a line: "The window's deferred and delayed callbacks (`_defer`, `_retry_later`) run or are recorded synchronously, since there is no event loop."

- [ ] **Step 2: Write the failing tests**

Create `tests/test_link_status.py`:

```python
"""How the window reports link health: rows and chimes, not just the status bar.

README.md documents the status bar as the surface a screen-reader user queries
by hand, so a lost link that only changed the status bar went unnoticed.
"""

from src.controller.link_state import LinkState
from src.model.connection_manager import UnreadableMessage
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeConnectionManager, make_main_window

STATION = "EDYY"


def build(logger):
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection)
    session.set_callsign("DLH123")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, session, connection, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def test_a_lost_link_gets_a_row_and_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.DEGRADED, LinkState.LOST, "timed out")

    assert rows(manager) == [("SYSTEM", "Connection lost, retrying")]
    assert window.new_message_sound.played == 1


def test_a_link_restored_after_a_loss_gets_a_row_and_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.LOST, LinkState.CONNECTED, None)

    assert rows(manager) == [("SYSTEM", "Connection restored")]
    assert window.new_message_sound.played == 1


def test_a_brief_blip_only_touches_the_status_bar(logger):
    """One failed poll then a good one is not worth interrupting the pilot."""
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "timed out")
    window._on_link_change(LinkState.DEGRADED, LinkState.CONNECTED, None)

    assert rows(manager) == []
    assert window.new_message_sound.played == 0


def test_a_callsign_already_in_use_is_named_once(logger):
    """The log shows five of these; the pilot was never told which of the two
    clients had the callsign."""
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "callsign already in use")

    assert rows(manager) == [("SYSTEM", "Connection problem: callsign already in use")]
    assert window.new_message_sound.played == 0


def test_a_rejected_logon_code_tears_the_connection_down(logger, message_boxes):
    window, session, connection, manager = build(logger)

    window._on_link_change(LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")

    assert window.polling_controller.stopped is True
    assert (window.weather_monitor.stopped, window.weather_monitor.cleared) == (True, True)
    assert connection.disconnected is True
    assert session.is_logged_on() is False
    assert (window.menu_item_connect.label, window.menu_item_connect.help) == (
        "&Connect", "Connect to the CPDLC network"
    )
    assert window.status_texts[-1] == "Disconnected: logon code rejected."
    assert rows(manager)[-1] == ("SYSTEM", "Disconnected: the server rejected the logon code")
    assert window.new_message_sound.played == 1
    assert message_boxes.captions == ["Logon Code Rejected"]


def test_unreadable_uplinks_become_rows_with_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_unreadable_messages(
        [UnreadableMessage("EDGG", "/data2/6//R/QNH 1013 / TRL 70")]
    )

    assert rows(manager) == [
        ("SYSTEM", "Unreadable message from EDGG: /data2/6//R/QNH 1013 / TRL 70")
    ]
    assert window.new_message_sound.played == 1
```

Append to the guards section of `tests/test_main_window.py`:

```python
def test_the_real_window_listens_to_its_polling_controller(window):
    """The link and unreadable callbacks are how a lost link and a dropped
    uplink reach the message list at all."""
    controller = window.polling_controller

    assert controller.link_callback == window._on_link_change
    assert controller.unreadable_callback == window._on_unreadable_messages
```

- [ ] **Step 3: Run to verify they fail**

Run: `$PY -m pytest tests/test_link_status.py tests/test_main_window.py -q -p no:cacheprovider`
Expected: `AttributeError: 'MainWindow' object has no attribute '_on_link_change'` and the wiring test failing on `link_callback` being None.

- [ ] **Step 4: Implement the window side**

In `src/gui/main_window.py` add after the `PollingController` import (line 30):

```python
from src.controller.link_state import LinkState
```

Replace the controller construction (lines 106-113) with:

```python
        self.polling_controller = PollingController(
            logger,
            self.connection_manager,
            self._on_message_received,
            DEFAULT_POLL_INTERVAL,
            ACTIVE_POLL_INTERVAL,
            INACTIVITY_TIMEOUT,
            link_callback=self._on_link_change,
            unreadable_callback=self._on_unreadable_messages,
        )
```

After `_on_weather_error` (after line 796) add:

```python
    def _defer(self, callback, *args, **kwargs):
        """Run a callback on the next pass of the event loop.

        A modal dialog opened from inside a timer tick nests an event loop under
        the handler, and the next tick then runs inside it; deferring keeps
        every tick short.
        """
        wx.CallAfter(callback, *args, **kwargs)

    def _on_link_change(self, old_state, new_state, reason):
        """Announce the link transitions the status bar alone would hide.

        NVDA does not announce status bar changes on its own, so losing the
        link, getting it back and a rejected logon code each get a SYSTEM row
        and the notification sound. A degraded link (one or two failed polls)
        only changes the status bar, except that a callsign already in use is
        named once so the pilot can look for the other client.

        Args:
            old_state: The LinkState before the transition
            new_state: The LinkState after it
            reason: The poll's reason text, None on recovery
        """
        if new_state == LinkState.LOST:
            self._add_custom_message("Connection lost, retrying", "SYSTEM", play_sound=True)
        elif new_state == LinkState.CONNECTED and old_state == LinkState.LOST:
            self._add_custom_message("Connection restored", "SYSTEM", play_sound=True)
        elif new_state == LinkState.DEGRADED and reason and "callsign already in use" in reason.lower():
            self._add_custom_message(
                "Connection problem: callsign already in use", "SYSTEM"
            )
        elif new_state == LinkState.FATAL:
            self._on_fatal_link_error(reason)

    def _on_fatal_link_error(self, reason):
        """Tear the connection down after the server rejected the logon code.

        Args:
            reason: The server's reason text
        """
        self.logger.error(f"Disconnecting after a fatal link error: {reason}")
        self.polling_controller.stop()
        self.weather_monitor.stop()
        self.weather_monitor.clear()
        self.connection_manager.disconnect()
        # Package 3 replaces these three lines with CpdlcSession.reset().
        self.cpdlc_session.current_station = ""
        self.cpdlc_session.pending_logon_min = None
        self.cpdlc_session.pending_logon_station = None
        self.menu_item_connect.SetItemLabel("&Connect")
        self.menu_item_connect.SetHelp("Connect to the CPDLC network")
        self.SetStatusText("Disconnected: logon code rejected.")
        self._add_custom_message(
            "Disconnected: the server rejected the logon code", "SYSTEM", play_sound=True
        )
        self._defer(
            wx.MessageBox,
            "The server rejected the logon code. Check it under File > Settings, "
            "then connect again.",
            "Logon Code Rejected",
            wx.OK | wx.ICON_ERROR,
        )

    def _on_unreadable_messages(self, unreadable):
        """Tell the pilot about uplinks that arrived but could not be decoded.

        The server has already marked them delivered, so the controller will
        be waiting for a response the pilot never saw. The raw packet is shown
        so it can be read out or asked about by voice.

        Args:
            unreadable: List of UnreadableMessage records from one poll
        """
        for item in unreadable:
            self._add_custom_message(
                f"Unreadable message from {item.sender}: {item.raw}",
                "SYSTEM",
                play_sound=True,
            )
```

- [ ] **Step 5: Run the touched files, then the suite**

Run: `$PY -m pytest tests/test_link_status.py tests/test_main_window.py tests/test_uplink_handling.py tests/test_acknowledge_path.py tests/test_logon_status.py -q -p no:cacheprovider`
Expected: all pass (the `make_main_window` changes must not disturb the existing window tests).

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `243 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/gui/main_window.py tests/support.py tests/test_link_status.py tests/test_main_window.py
git commit -m "Announce a lost or restored link and a rejected logon code

The status bar was the only place a dying link showed, and a screen reader
does not announce it. Losing the link, getting it back and an unreadable
uplink now add a SYSTEM row and play the notification sound; a callsign
already in use is named once; a rejected logon code disconnects, resets
the session, flips the menu back to Connect and explains itself.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: A rate-limited acknowledgement is retried once

**Files:**
- Modify: `src/gui/main_window.py:16-24` (import `RATE_LIMIT_RETRY_MS`), `_on_acknowledge_message` (originally lines 1029-1064)
- Modify: `tests/support.py` (`make_main_window` records delayed callbacks)
- Modify: `tests/test_acknowledge_path.py` (`build()` takes a connection; two tests appended)

**Interfaces:**
- Consumes: `config.RATE_LIMIT_RETRY_MS` (Task 2), `FakeConnectionManager(raise_with=...)`.
- Produces: `MainWindow._retry_later(delay_ms, callback, *args)` (wx.CallLater; `make_main_window` replaces it with a recorder that appends `(delay_ms, callback, args)` to `window.retries`); `_on_acknowledge_message(message_id, response, retried=False)`; status text `"Rate limited - retrying <RESPONSE> in 5 s"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_acknowledge_path.py` change the imports to:

```python
from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

from tests.support import FakeConnectionManager, make_main_window, uplink

from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
```

change `build` to:

```python
def build(logger, connection=None):
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection)
    session.set_callsign("DLH123")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager, connection
```

and append:

```python
def test_a_rate_limited_acknowledgement_is_retried_once_after_five_seconds(logger):
    """SayIntentions answers rate_limit to a second message within a few
    seconds of the first; the log shows a ROGER lost that way."""
    connection = FakeConnectionManager(raise_with=HoppieError("rate_limit"))
    window, manager, _ = build(logger, connection)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == []
    assert window.status_texts[-1] == "Rate limited - retrying WILCO in 5 s"
    assert manager.needs_acknowledgement(message_id, STATION)[0] is True
    delay, callback, args = window.retries[0]
    assert (delay, args) == (5000, (message_id, "WILCO", True))

    connection.raise_with = None
    callback(*args)

    assert connection.sent[-1][3] == "WILCO"
    assert manager.needs_acknowledgement(message_id, STATION) == (False, [])


def test_a_second_rate_limit_is_reported_rather_than_retried_again(logger, message_boxes):
    connection = FakeConnectionManager(raise_with=HoppieError("rate_limit"))
    window, manager, _ = build(logger, connection)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO", True)

    assert window.retries == []
    assert message_boxes.captions == ["Error"]
    assert "rate_limit" in message_boxes.calls[0][0]
```

In `tests/support.py` `make_main_window`, after the `_defer` line add:

```python
    # wx.CallLater needs a running wx.App; record delayed callbacks instead.
    window.retries = []
    window._retry_later = lambda delay_ms, callback, *args: window.retries.append(
        (delay_ms, callback, args)
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `$PY -m pytest tests/test_acknowledge_path.py -q -p no:cacheprovider`
Expected: the two new tests fail (`IndexError` on `window.retries[0]` / `message_boxes.captions == ["Error"]` mismatch); the older tests still pass.

- [ ] **Step 3: Implement the retry**

In `src/gui/main_window.py` add `RATE_LIMIT_RETRY_MS,` to the `from src.config import (...)` block, add after `_defer`:

```python
    def _retry_later(self, delay_ms, callback, *args):
        """Run a callback once after a delay, on the event loop."""
        wx.CallLater(delay_ms, callback, *args)
```

and replace `_on_acknowledge_message` with:

```python
    def _on_acknowledge_message(self, message_id: int, response: str, retried=False):
        """Handle message acknowledgement.

        Args:
            message_id: The ID of the message being acknowledged
            response: The response text
            retried: True when this is the automatic second attempt after a
                rate_limit answer, which is not retried again
        """
        addressing = self.message_manager.get_cpdlc_addressing(message_id)
        if addressing is None:
            self.logger.warning(f"Cannot acknowledge unknown message ID {message_id}")
            self.SetStatusText("Could not send response: message unavailable.")
            return

        sender, min_value = addressing

        success, returned_message = self.cpdlc_session.send_acknowledgement(
            sender, min_value, response
        )
        if success:
            # MessageManager decides whether this response retires the message;
            # STANDBY is sent but leaves it answerable.
            self.message_manager.mark_acknowledged(message_id, response)

            # Add custom message only if a message was returned from the session
            if returned_message:
                self._add_custom_message(returned_message)

            # Set active polling
            self.polling_controller.set_active_polling()
        elif not retried and returned_message and "rate_limit" in returned_message.lower():
            # SayIntentions refuses a second message sent within a few seconds
            # of the first. One automatic retry covers the common case of two
            # quick acknowledgements; a second refusal is reported like any
            # other failure.
            seconds = RATE_LIMIT_RETRY_MS // 1000
            self.logger.warning(f"Rate limited sending {response}; retrying in {seconds} s")
            self.SetStatusText(f"Rate limited - retrying {response} in {seconds} s")
            self._retry_later(
                RATE_LIMIT_RETRY_MS, self._on_acknowledge_message, message_id, response, True
            )
        else:
            error_detail = f": {returned_message}" if returned_message else ""
            wx.MessageBox(
                f"Failed to send acknowledgement{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
```

- [ ] **Step 4: Run the file and the suite**

Run: `$PY -m pytest tests/test_acknowledge_path.py -q -p no:cacheprovider`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `245 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/gui/main_window.py tests/support.py tests/test_acknowledge_path.py
git commit -m "Retry a rate-limited acknowledgement once after five seconds

SayIntentions refuses a second message sent within a few seconds of the
first; the log shows a ROGER lost that way. One automatic retry covers
two quick acknowledgements, and a second refusal is reported as before.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Weather envelope edge cases

**Files:**
- Modify: `src/model/connection_manager.py` (`_SERVER_INFO_PATTERN`; the body handling in `_send_info_request`)
- Modify: `tests/test_connection_manager.py` ("information requests" section)

**Interfaces:**
- Produces: `send_info_request()` raises `HoppieError("No <label> available for <ICAO>")` for a bare `ok`, `ok ` and an empty or blank envelope; server errors read `"<label> request error: <reason>"` without braces.

- [ ] **Step 1: Write the failing tests**

In `tests/test_connection_manager.py` replace `test_an_information_request_reports_a_server_error` with:

```python
@pytest.mark.parametrize("kind", ["metar", "vatatis"])
def test_an_information_request_reports_a_server_error_without_the_braces(
    logger, monkeypatch, kind
):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "error {invalid logon}")

    with pytest.raises(HoppieError, match=r"request error: invalid logon$"):
        cm.send_info_request(kind, "EDDF")


@pytest.mark.parametrize(
    "body",
    ["ok", "ok ", "ok {server info {}}", "ok {server info { }}"],
    ids=["bare-ok", "ok-with-space", "empty-envelope", "blank-envelope"],
)
def test_a_station_with_nothing_to_report_is_reported_as_unavailable(
    logger, monkeypatch, body
):
    """The empty envelope used to be returned as the literal text
    "{server info {}}", which the weather monitor then announced as a report."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, body)

    with pytest.raises(HoppieError, match="No METAR available for EDDF"):
        cm.send_info_request("metar", "EDDF")
```

- [ ] **Step 2: Run to verify they fail**

Run: `$PY -m pytest tests/test_connection_manager.py -q -p no:cacheprovider -k "server_error_without or nothing_to_report"`
Expected: the braces test fails on the match, `bare-ok`/`ok-with-space` fail with "Unexpected response", `empty-envelope` fails because no error is raised.

- [ ] **Step 3: Fix the envelope handling**

In `src/model/connection_manager.py` change the pattern to:

```python
_SERVER_INFO_PATTERN = re.compile(r"^\{server info \{(.*)\}\}$", re.DOTALL)
```

and replace the body handling in `_send_info_request` (from `body = response.text.strip()` to the end of the method) with:

```python
        body = response.text.strip()

        if body == "ok" or body.startswith("ok "):
            text = body[2:].strip()
            # The report is wrapped as {server info {actual text}}; a station
            # with nothing to report answers with an empty envelope, or with a
            # bare "ok", both of which come back as "" for the caller to name.
            match = _SERVER_INFO_PATTERN.match(text)
            if match:
                text = match.group(1).strip()
            self.logger.info(f"Received {label} for {icao}")
            return text
        elif body.startswith("error"):
            error_reason = body[5:].strip().strip("{}").strip()
            self.logger.error(f"{label} request error: {error_reason}")
            raise HoppieError(f"{label} request error: {error_reason}")
        else:
            self.logger.error(f"Unexpected {label} response: {body}")
            raise HoppieError(f"Unexpected response: {body}")
```

- [ ] **Step 4: Run the file and the suite**

Run: `$PY -m pytest tests/test_connection_manager.py -q -p no:cacheprovider`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `249 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/model/connection_manager.py tests/test_connection_manager.py
git commit -m "Treat an empty weather envelope as no report, not as report text

The unwrapping pattern needed at least one character, so a station with
nothing to report came back as the literal "{server info {}}" and the
weather monitor announced it. A bare "ok" now means the same, and server
error reasons lose their braces.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: One deferred error dialog at a time

**Files:**
- Create: `src/error_reporting.py`
- Create: `tests/test_error_reporting.py`
- Modify: `app.py` (whole file; new content below)

**Interfaces:**
- Produces: `ExceptionReporter(logger)` with `install()`, `report(exc_type, exc_value, exc_tb, source)`, `_show_dialog(text)`, `_dialog_open`; `app.py` calls `ExceptionReporter(logger).install()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_error_reporting.py`:

```python
"""The last-resort exception reporter: log first, one deferred dialog at a time.

A fault that repeats on every poll tick used to open a new modal dialog inside
the previous one, because the dialog was shown synchronously from the failing
handler and timers keep firing under a modal loop.
"""

import sys
import threading

import wx

from src.error_reporting import ExceptionReporter


def test_a_report_logs_and_defers_its_dialog(logger, wx_app, message_boxes):
    reporter = ExceptionReporter(logger)

    reporter.report(RuntimeError, RuntimeError("boom"), None, "main thread")

    assert message_boxes.calls == [], "the dialog must not open inside the failing handler"
    wx_app.ProcessPendingEvents()
    assert message_boxes.captions == ["Unexpected Error"]
    assert "RuntimeError: boom" in message_boxes.calls[0][0]


def test_a_report_while_the_dialog_is_open_only_logs(logger, wx_app, monkeypatch):
    reporter = ExceptionReporter(logger)
    shown = []

    def message_box(text, *args, **kwargs):
        shown.append(text)
        if len(shown) == 1:
            # A timer tick fails again under the open dialog.
            reporter._show_dialog("second")
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", message_box)

    reporter._show_dialog("first")

    assert shown == ["first"]
    assert reporter._dialog_open is False


def test_a_report_with_no_application_running_is_logged_only(logger, message_boxes):
    """Background threads can outlive the wx.App; wx.CallAfter would raise."""
    assert wx.GetApp() is None
    reporter = ExceptionReporter(logger)

    reporter.report(RuntimeError, RuntimeError("late"), None, "background thread")

    assert message_boxes.calls == []


def test_install_routes_both_hooks_to_the_reporter(logger, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    reporter = ExceptionReporter(logger)

    reporter.install()

    assert sys.excepthook == reporter.handle_uncaught
    assert threading.excepthook == reporter.handle_thread
```

- [ ] **Step 2: Run to verify it fails**

Run: `$PY -m pytest tests/test_error_reporting.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'src.error_reporting'`.

- [ ] **Step 3: Create the module and use it from `app.py`**

Create `src/error_reporting.py`:

```python
"""Last-resort reporting of unhandled exceptions to the log and to the user.

wxPython discards exceptions raised inside event handlers, and the packaged
build runs with console=False so stderr goes nowhere. Without a last-resort
handler a failing handler looks exactly like a button that does nothing.

The dialog is always deferred to the next pass of the event loop and never
stacked: a fault that repeats on every poll tick would otherwise open a new
modal dialog inside the previous one.
"""

import sys
import threading
import traceback

import wx


class ExceptionReporter:
    """Routes otherwise-unhandled exceptions to the log and to one dialog."""

    def __init__(self, logger):
        """Initialize the reporter.

        Args:
            logger: Application logger
        """
        self.logger = logger
        self._dialog_open = False

    def install(self):
        """Become the process-wide handler for main-thread and thread exceptions."""
        sys.excepthook = self.handle_uncaught
        threading.excepthook = self.handle_thread

    def report(self, exc_type, exc_value, exc_tb, source):
        """Log an exception with its traceback and queue the dialog.

        Args:
            exc_type: Exception class
            exc_value: Exception instance
            exc_tb: Traceback, or None
            source: Where it came from, for the log line
        """
        self.logger.error(
            f"Unhandled exception in {source}: {exc_type.__name__}: {exc_value}\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        text = (
            f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
            "The details have been written to the log file."
        )
        if wx.GetApp() is None:
            # A background thread outliving the application, or a failure
            # before the application exists: there is nothing to show it on.
            self.logger.error("No application running; the error dialog was not shown")
            return
        # Deferred even on the GUI thread, so the failing handler unwinds
        # before a modal loop starts.
        wx.CallAfter(self._show_dialog, text)

    def _show_dialog(self, text):
        """Show the dialog unless one is already open. Runs on the GUI thread."""
        if self._dialog_open:
            self.logger.warning("Error dialog already open; a further error was logged only")
            return
        self._dialog_open = True
        try:
            wx.MessageBox(text, "Unexpected Error", wx.OK | wx.ICON_ERROR)
        except Exception:
            # Never let the reporter itself take the application down.
            self.logger.exception("Failed to display the unhandled-exception dialog")
        finally:
            self._dialog_open = False

    def handle_uncaught(self, exc_type, exc_value, exc_tb):
        """sys.excepthook replacement."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        self.report(exc_type, exc_value, exc_tb, "main thread")

    def handle_thread(self, args):
        """threading.excepthook replacement."""
        self.report(args.exc_type, args.exc_value, args.exc_traceback, "background thread")
```

Replace `app.py` with:

```python
#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai and Hoppie's ACARS

This is the main entry point for the application.
"""

import sys

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir
from src.error_reporting import ExceptionReporter
from src.model.connection_manager import install_request_timeout


class SimCpdlcApp(wx.App):
    """wx.App that reports exceptions escaping an event handler."""

    def __init__(self, logger):
        self.logger = logger
        super().__init__(False)

    def OnExceptionInMainLoop(self):
        """Log and show any exception raised inside a wx event handler."""
        sys.excepthook(*sys.exc_info())
        return True


def main():
    """Main entry point for the application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Application starting")

    # Log user data directory location
    user_data_dir = get_user_data_dir()
    logger.info(f"Using user data directory: {user_data_dir}")

    ExceptionReporter(logger).install()

    # hoppie_connector passes no timeout to requests, so a server that accepts
    # the connection and then goes silent would otherwise block the GUI thread
    # forever. This gives those calls a default timeout.
    install_request_timeout()

    # Create and start the application
    app = SimCpdlcApp(logger)
    frame = MainWindow(None, "Sim-CPDLC", logger)

    try:
        logger.debug("Entering main application loop")
        app.MainLoop()
    except KeyboardInterrupt:
        logger.info("Application terminated by keyboard interrupt")
        frame.on_exit(None)
    finally:
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
```

(`OnExceptionInMainLoop` and the `KeyboardInterrupt` branch are left as they are; package 4 removes them.)

- [ ] **Step 4: Run the file and the suite; import-check `app.py`**

Run: `$PY -m pytest tests/test_error_reporting.py -q -p no:cacheprovider`
Expected: `4 passed`.

Run: `$PY -c "import app; print('app imports')"` from the worktree root.
Expected: `app imports` (no application starts; `main()` is guarded).

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `253 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/error_reporting.py app.py tests/test_error_reporting.py
git commit -m "Defer the unhandled-error dialog and never stack a second one

A fault that repeated on every poll tick opened a new modal dialog inside
the previous one, because the dialog was shown from inside the failing
handler and timers keep firing under a modal loop. The reporter now logs
first, shows the dialog on the next pass of the event loop, logs further
errors while it is open, and does nothing when no wx.App is running.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: README rows and final verification

**Files:**
- Modify: `tests/README.md` (three rows; one description)

- [ ] **Step 1: Update the table**

In `tests/README.md` change the `test_connection_manager.py` row to:

```markdown
| `test_connection_manager.py` | The network boundary: errors, timeouts, poll results, unreadable uplinks, the wire packets |
```

change the `test_polling_controller.py` row to:

```markdown
| `test_polling_controller.py` | Poll intervals, the back-off ladder while the link is lost, batch delivery |
```

and insert, keeping alphabetical order:

```markdown
| `test_error_reporting.py` | The last-resort exception reporter: one deferred dialog at a time |
| `test_link_state.py` | The link state machine and its back-off ladder |
| `test_link_status.py` | How the window announces a lost, restored or fatal link and unreadable uplinks |
```

- [ ] **Step 2: Run the whole suite and check the change set**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: `253 passed`, no warnings.

Run: `git diff --stat main...HEAD -- src app.py`
Expected: exactly `app.py`, `src/config.py`, `src/controller/link_state.py`, `src/controller/polling_controller.py`, `src/error_reporting.py`, `src/gui/main_window.py`, `src/model/connection_manager.py`.

Run: `grep -rn "attempt_reconnection\|should_attempt_reconnection\|failure_count\|poll_failed\|_report_connection_state\|_reported_failure" src tests`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add tests/README.md
git commit -m "List the link-state, link-status and error-reporting tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec coverage (Package 2): `LinkState` with the four states, ladder, `on_change`, `next_delay_ms`, `reset` (Task 2); `PollResult`/`UnreadableMessage`, warning capture, fatal detection, `callsign already in use` reason carried (Task 1); controller: ladder scheduling, no `stop()` while lost, FATAL stops the timer, `start()` resets, status texts, batch continuation, `unreadable_callback`, `link_callback` (Task 3); window: SYSTEM rows and sound on lost/restored, callsign-in-use once, fatal teardown with dialog, unreadable rows, `rate_limit` retry (Tasks 4–5); `_SERVER_INFO_PATTERN` and envelope cases (Task 6); reporter deferral and coalescing (Task 7). `_report_connection_state` reading poll failures only (L-1) is subsumed by the LinkState texts, which are driven by poll results alone. Deviations are listed at the top.
- Names used across tasks: `PollResult`, `UnreadableMessage`, `unreadable_from_warning` (Task 1) are used unchanged in Tasks 2–4; `LinkState` constants and `next_delay_ms`/`reset`/`record_poll`/`failures`/`max_failures` (Task 2) are used unchanged in Tasks 3–4; `link_callback`/`unreadable_callback` (Task 3) are the keyword names Task 4 passes; `FakeConnectionManager.disconnect`, `FakePollingController.stop`, `FakeWeatherMonitor`, `FakeMenuItem`, `FakeSound`, `_defer`, `_retry_later`, `window.retries` (Tasks 4–5) match between `tests/support.py` and the tests that read them.
- Test counts per task are arithmetic on the tests each step adds or removes; if a count differs by one or two, report the real number rather than forcing it.
