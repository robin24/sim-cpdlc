# Package 4: One Network Worker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The GUI thread never waits on the network, sends are paced and serialised, and a background result can never touch a dead window.

**Architecture:** A new `NetworkWorker` owns the one thread that performs every network call: polls, sends, connect and disconnect, weather and SimBrief fetches, the update check. Callers submit a zero-argument job with a priority; the worker runs jobs in priority order, spaces sends 5 s and information requests 1 s apart, catches every exception into a `JobResult`, and hands results back to the GUI thread through `wx.CallAfter`, guarded by an alive flag and a generation number so a disconnected session's work is dropped. `PollingController` submits a poll per tick and processes the result when it arrives; `WeatherMonitor` loses its thread and submits one job per subscription; `CpdlcSession`'s send methods build the frame and spend the MIN synchronously, queue the transmission and report through an `on_done(success, text_or_error)` callback; `MainWindow` keeps its success and failure handling inside those callbacks, connects and disconnects in two phases with the menu item disabled in between, counts open modal dialogs so the update prompt waits its turn, and drains the worker on exit. SimBrief moves out of the dialog constructors, the update checker reports an outcome instead of showing dialogs, and SimConnect connects once per network connection on a thread of its own.

**Tech Stack:** Python 3.12+, wxPython 4.2.5, hoppie-connector 0.2.1, `queue.PriorityQueue` and `threading` from the standard library, pytest 9.1.1 with pytest-timeout.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 316 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg4-network-worker`, cut from `main` at `ca41c01`, in the worktree `C:\Claude\sim-cpdlc\.claude\worktrees\pkg4-network-worker`. Never touch `C:\Claude\sim-cpdlc` itself.
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog (the autouse fixtures in `tests/conftest.py` enforce this; keep using `tests.support` doubles). Tests never start the worker's thread except the one test that proves the thread runs and stops; everything else uses `tests.support.inline_worker()` and drives it with `run_pending()`.
- Nothing in `src/model/network_worker.py` may touch a wx object; `wx.CallAfter` is only the default value of its `dispatch` argument.
- Files this package may change: `src/model/network_worker.py` (new), `src/model/cpdlc_session.py`, `src/model/weather_monitor.py`, `src/controller/polling_controller.py`, `src/gui/main_window.py`, `src/gui/dialogs/connect_dialog.py`, `src/gui/dialogs/pdc_dialog.py`, `src/utils/update_checker.py`, `src/utils/simconnect_manager.py`, `src/config.py`, `app.py`, and anything under `tests/`. Nothing else under `src/` changes.
- Exact values (from the spec): `SEND_SPACING_SECONDS = 5`, `INFOREQ_SPACING_SECONDS = 1`, `NETWORK_TIMEOUT = (10, 15)` in `src/config.py`; job priorities `PRIORITY_SEND = 0`, `PRIORITY_LINK = 1` (connect, poll, disconnect), `PRIORITY_INFO = 2` (inforeq, SimBrief, update check); `worker.shutdown(timeout=5)` on exit. Status texts: `"Sending <text>..."` while a downlink is queued and `"Sent <text>."` once it went out; `"Connecting as X..."`, `"Not connected."`, `"Disconnecting..."`, `"Requesting <label> for <icao>..."`; SYSTEM row `"Could not send LOGOFF to X: <reason>"` stays. The update prompt reads `"Open the release page in your browser?"`, is parented to the main window and never closes the application.
- `RATE_LIMIT_RETRY_MS`, the `wx.CallLater` retry and its `_pending_retry` plumbing are removed with the send path: pacing makes `rate_limit` unreachable and a residual one is reported like any other failure.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 4" (with its "Landing order") and the "Cross-cutting" notification table. Audit: `docs/audit/2026-09-03-codebase-audit.md` (H-3, M-5, M-9, L-4, L-5, L-9, L-13, L-14, L-15).

## Deviations from the spec (decided while planning; the spec's "Package 4" section is otherwise followed)

1. **SimConnect connects on a thread of its own, not in the queue.** Upstream `SimConnect()` busy-waits for the simulator's OPEN reply without a timeout (audit M-9); a stuck call inside the serial queue would stall every send and poll for the rest of the session. `NetworkWorker.run_detached()` runs one job on a short-lived daemon thread through the same result path.
2. **Disconnect is two-phase.** Tearing the connection down on the GUI thread would fail the LOGOFF still queued behind it, so `on_disconnect` queues the LOGOFF (priority 0), then a `disconnect` job (priority 1), and finishes the UI work when that job reports; `worker.new_generation()` runs there. The Connect menu item is disabled in between, as it is during a connect.
3. **A logon while logged on queues both frames.** Package 3 made a LOGOFF that could not be sent abort the new logon; with queued sends that outcome is not known when the request is built, and pacing removes the reason for the rule. `logon()` queues LOGOFF then REQUEST LOGON, each reporting through `on_done`, as the spec first described. A failed REQUEST LOGON clears the pending logon it would have opened.
4. **The status bar reads "Sent X." after a downlink** rather than being cleared: screen-reader users query the status bar, and an empty one tells them nothing.
5. **`UpdateChecker` reports an outcome and shows nothing itself.** The window owns every prompt (the spec had it own only the "update available" state), so the modal counter sees all of them.
6. **The first-launch prompt moves to the end of `__init__`**, after the controllers exist and the close handler is bound, instead of to a deferred call: `load_config()` already copes with a missing file, and the harness test that builds the window synchronously keeps seeing the prompt.
7. **`wx.MessageBox` calls inside dialogs stay as they are.** `WeatherSubscriptionsDialog` asks its questions from inside its own modal loop, where the window's counter is already positive.
8. **Manual `Requests > Logoff` no longer switches to active polling.** No answer to a LOGOFF is expected.

## Design notes

- **The `on_done` contract.** Every `CpdlcSession` send returns `bool`: True once the frame is queued, False when a precondition refused it (the caller shows its "not connected / not logged on" dialog at once). `on_done(success, text_or_error)` runs later on the GUI thread: the element text on success, the error text on failure. The MIN is spent and the session state changed at enqueue time; a failed send leaves a gap in the MIN sequence, which stations do not mind.
- **Generations.** `submit()` stamps each job with the worker's current generation; `new_generation()` makes every older job skip when it reaches the front of the queue and drops the result of one already running. Disconnect and the fatal teardown bump it; nothing queued for the old session can run against or report into the next.
- **In tests** the worker has no thread: `run_pending()` runs the queue on the test's thread, and `dispatch` calls each callback inline, so a test reads "submit, `run_pending()`, assert". `shutdown()` without a thread runs the queue too, so the LOGOFF `on_close` queues still goes out in a test.
- **The poll tick.** `on_poll_timer` submits the poll and returns; the timer is re-armed only when the result arrives, so a slow server never stacks polls. A tick that fires while a poll is out re-arms the timer and does nothing else.
- **Interim behaviour that later packages change:** none. Package 5 (dialog validation) and package 6 (hygiene) do not touch the worker.

## File structure

| File | Responsibility after this plan |
|---|---|
| `src/model/network_worker.py` (new) | `Job`, `JobResult`, `NetworkWorker`: the queue, the thread, pacing, generations, result dispatch, `run_detached`. |
| `src/config.py` | `SEND_SPACING_SECONDS`, `INFOREQ_SPACING_SECONDS`, `NETWORK_TIMEOUT = (10, 15)`; `RATE_LIMIT_RETRY_MS` removed. |
| `src/controller/polling_controller.py` | Submits a poll per tick; `_on_poll_result` processes it; one poll in flight at a time. |
| `src/model/weather_monitor.py` | No thread: one inforeq job per subscription per cycle, cycle ids, results applied on the GUI thread. |
| `src/model/cpdlc_session.py` | Sends through the worker with `on_done`; `_send_request` behind the four requests; `request_weather` through the worker. |
| `src/gui/main_window.py` | Owns the worker; callbacks for every downlink; two-phase connect and disconnect; `_show_dialog` / `_message_box` with the modal counter; `pending_update`; SimBrief fetch; SimConnect connect and retry; `on_close` drains the worker. |
| `src/gui/dialogs/connect_dialog.py`, `src/gui/dialogs/pdc_dialog.py` | Open at once; `fetch_simbrief(on_done)` fills the fields later if the dialog is still alive. |
| `src/utils/update_checker.py` | `check(on_done)` through the worker; an `UpdateOutcome`, no dialogs. |
| `src/utils/simconnect_manager.py` | `connect()` off the GUI thread; `set_com1_standby_mhz` checks `send_event`'s answer and never connects itself. |
| `app.py` | Plain `wx.App`; no `OnExceptionInMainLoop`, no `KeyboardInterrupt` branch. |
| `tests/support.py` | `inline_worker()`; `FakeConnectionManager.connect_error`; `FakeMenuItem.Enable/IsEnabled`; `FakeWeatherMonitor` subscriptions; `FakeCloseEvent.CanVeto`; `make_main_window` wires the worker and the modal counter; `FakeCallLater` and the retry shim removed. |
| `tests/test_network_worker.py`, `tests/test_update_checker.py`, `tests/test_weather_requests.py` (new) | The worker; the checker; the manual weather request through the window. |
| `tests/test_polling_controller.py`, `tests/test_weather_monitor.py`, `tests/test_downlink_requests.py`, `tests/test_cpdlc_session.py`, `tests/test_acknowledge_path.py`, `tests/test_uplink_handling.py`, `tests/test_session_lifecycle.py`, `tests/test_logon_status.py`, `tests/test_link_status.py`, `tests/test_main_window_wiring.py`, `tests/test_main_window.py`, `tests/test_harness.py`, `tests/test_dialogs.py`, `tests/conftest.py` | Updated for the worker, the callbacks and the new seams. |
| `tests/README.md` | Three new rows, several reworded. |

---

### Task 1: `NetworkWorker` — one thread, a priority queue, pacing, generations

**Files:**
- Create: `src/model/network_worker.py`
- Modify: `src/config.py:120-123` (spacing constants after `RATE_LIMIT_RETRY_MS`; `NETWORK_TIMEOUT` becomes a tuple)
- Modify: `tests/support.py` (add `inline_worker()` after `answerable()`)
- Create: `tests/test_network_worker.py`

**Interfaces:**
- Consumes: `FakeClock` from `tests/support.py`; `HoppieError` from hoppie_connector.
- Produces (used by every later task):
  - Constants `PRIORITY_SEND = 0`, `PRIORITY_LINK = 1`, `PRIORITY_INFO = 2`, `DEFAULT_SPACING = {"send": SEND_SPACING_SECONDS, "inforeq": INFOREQ_SPACING_SECONDS}`.
  - `Job(priority, sequence, kind, fn, on_done, generation)` (ordered by priority then sequence); `JobResult(ok, value=None, error=None, job=None)`.
  - `NetworkWorker(logger, dispatch=wx.CallAfter, start_thread=True, spacing=None, clock=time.monotonic, sleep=time.sleep)`.
  - `submit(kind, fn, on_done=None, priority=PRIORITY_INFO) -> Job`; `new_generation() -> int`; property `generation`; `pending() -> int`; `run_pending()`; `shutdown(timeout=2.0)`; `run_detached(kind, fn, on_done=None)` (a one-off daemon thread through the same result path; in test mode, queued like any job).
  - Semantics: jobs run in priority order, FIFO within a priority; a job whose generation is older than the worker's is skipped before it runs and its result dropped if it was already running; before a `send` or `inforeq` job the worker sleeps until the spacing has passed since the previous job of that kind finished; `fn()` exceptions become `JobResult(ok=False, error=...)` (`str(exc)` for `HoppieError`, `"<Name>: <text>"` plus a logged traceback otherwise); results reach `on_done` through `dispatch(on_done, result)` unless the worker was shut down; a `dispatch` that raises is logged and dropped.
  - `tests.support.inline_worker(logger)`: `NetworkWorker(logger, dispatch=lambda fn, *args: fn(*args), start_thread=False)`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, add after `answerable()`:

```python
def inline_worker(logger):
    """A NetworkWorker with no thread.

    Jobs run when the test calls run_pending(), on the test's own thread, and
    each result is handed straight to its callback, so a test drives the
    asynchronous path deterministically: submit, run_pending(), assert.
    """
    return NetworkWorker(logger, dispatch=lambda fn, *args: fn(*args), start_thread=False)
```

and add `from src.model.network_worker import NetworkWorker` to its imports (after the `PollResult` import).

Create `tests/test_network_worker.py`:

```python
"""Tests for the network worker: ordering, generations, pacing, failure capture.

Everything the app does on the network goes through this one queue, so its
ordering and its failure handling are what make the GUI thread safe to keep
using while a request is out.
"""

import logging
import threading

from hoppie_connector import HoppieError

from src.model.network_worker import (
    PRIORITY_INFO,
    PRIORITY_LINK,
    PRIORITY_SEND,
    NetworkWorker,
)
from tests.support import FakeClock, inline_worker


def raising(exc):
    def fn():
        raise exc

    return fn


def inline(fn, *args):
    fn(*args)


# --- ordering -----------------------------------------------------------------


def test_jobs_run_in_priority_order_then_submission_order(logger):
    """A pilot's response must not queue behind a weather refresh."""
    worker = inline_worker(logger)
    ran = []
    worker.submit("inforeq", lambda: ran.append("weather"), priority=PRIORITY_INFO)
    worker.submit("send", lambda: ran.append("first send"), priority=PRIORITY_SEND)
    worker.submit("poll", lambda: ran.append("poll"), priority=PRIORITY_LINK)
    worker.submit("send", lambda: ran.append("second send"), priority=PRIORITY_SEND)

    worker.run_pending()

    assert ran == ["first send", "second send", "poll", "weather"]


def test_a_result_carries_the_value_and_the_job(logger):
    worker = inline_worker(logger)
    results = []
    job = worker.submit("poll", lambda: 42, results.append, PRIORITY_LINK)

    worker.run_pending()

    assert (results[0].ok, results[0].value, results[0].error) == (True, 42, None)
    assert results[0].job is job
    assert worker.pending() == 0


def test_run_detached_is_queued_like_any_job_without_a_thread(logger):
    worker = inline_worker(logger)
    results = []

    worker.run_detached("simconnect", lambda: "connected", results.append)

    assert worker.pending() == 1
    worker.run_pending()
    assert results[0].value == "connected"


# --- generations --------------------------------------------------------------


def test_a_new_generation_drops_queued_jobs(logger):
    """Work queued for a session the pilot has disconnected must neither run
    against the next session nor report into it."""
    worker = inline_worker(logger)
    ran = []
    worker.submit("send", lambda: ran.append("old"), lambda result: ran.append("old reported"))

    assert worker.new_generation() == 1
    assert worker.generation == 1
    worker.submit("send", lambda: ran.append("new"))
    worker.run_pending()

    assert ran == ["new"]


def test_a_job_that_outlives_its_generation_is_not_reported(logger):
    """A poll already running when the pilot disconnects finishes on the
    worker; its result must not reach the window."""
    worker = inline_worker(logger)
    reported = []

    def poll_then_disconnect():
        worker.new_generation()
        return "late"

    worker.submit("poll", poll_then_disconnect, reported.append)

    worker.run_pending()

    assert reported == []


# --- pacing -------------------------------------------------------------------


def test_sends_and_information_requests_are_spaced_out(logger):
    """SayIntentions answers rate_limit to a second send within a few seconds;
    weather requests are spaced a second apart so a handful of subscriptions
    does not hit the server as a burst. Polls are not paced."""
    clock = FakeClock()
    slept = []

    def sleep(seconds):
        slept.append(round(seconds, 3))
        clock.advance(seconds)

    worker = NetworkWorker(
        logger,
        dispatch=inline,
        start_thread=False,
        spacing={"send": 5, "inforeq": 1},
        clock=clock,
        sleep=sleep,
    )
    worker.submit("send", lambda: clock.advance(0.5), priority=PRIORITY_SEND)
    worker.submit("send", lambda: None, priority=PRIORITY_SEND)
    worker.submit("poll", lambda: None, priority=PRIORITY_LINK)
    worker.submit("inforeq", lambda: None, priority=PRIORITY_INFO)
    worker.submit("inforeq", lambda: None, priority=PRIORITY_INFO)

    worker.run_pending()

    assert slept == [5.0, 1.0]


def test_a_send_after_a_long_pause_is_not_delayed(logger):
    clock = FakeClock()
    slept = []
    worker = NetworkWorker(
        logger, dispatch=inline, start_thread=False, clock=clock, sleep=slept.append
    )
    worker.submit("send", lambda: None, priority=PRIORITY_SEND)
    worker.run_pending()
    clock.advance(30)
    worker.submit("send", lambda: None, priority=PRIORITY_SEND)

    worker.run_pending()

    assert slept == []


# --- failures -----------------------------------------------------------------


def test_a_hoppie_error_becomes_a_failed_result_with_its_text(logger):
    worker = inline_worker(logger)
    results = []
    worker.submit("send", raising(HoppieError("rate_limit")), results.append)

    worker.run_pending()

    assert (results[0].ok, results[0].error, results[0].value) == (False, "rate_limit", None)


def test_any_other_exception_is_captured_and_logged_with_its_traceback(logger, caplog):
    """A bug in a job must reach the log file with its traceback and the
    window as a failure, never kill the worker thread."""
    worker = inline_worker(logger)
    results = []
    worker.submit("poll", raising(KeyError("cnx")), results.append)

    # The shared `logger` fixture disables propagation so tests stay silent;
    # caplog's handler has to be attached to it directly.
    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.addHandler(caplog.handler)
        worker.run_pending()

    assert (results[0].ok, results[0].error) == (False, "KeyError: 'cnx'")
    assert "Traceback" in caplog.text


def test_a_dispatch_failure_is_logged_and_dropped(logger, caplog):
    """wx.CallAfter raises once the wx.App is gone; the worker must not die of it."""

    def dead_dispatch(fn, *args):
        raise AssertionError("No wx.App created yet")

    worker = NetworkWorker(logger, dispatch=dead_dispatch, start_thread=False)
    worker.submit("poll", lambda: 1, lambda result: None)

    with caplog.at_level(logging.WARNING, logger=logger.name):
        logger.addHandler(caplog.handler)
        worker.run_pending()

    assert "Dropped the result of a poll job" in caplog.text


# --- shutdown -----------------------------------------------------------------


def test_shutdown_without_a_thread_runs_what_is_queued(logger):
    """The LOGOFF queued by on_close must still go out."""
    worker = inline_worker(logger)
    ran = []
    worker.submit("send", lambda: ran.append("LOGOFF"))

    worker.shutdown()

    assert ran == ["LOGOFF"]


def test_nothing_is_delivered_after_shutdown(logger):
    """At exit the window is gone; a late result is dropped, not dispatched."""
    worker = inline_worker(logger)
    reported = []
    worker.shutdown()
    worker.submit("poll", lambda: 1, lambda result: reported.append(result.value))

    worker.run_pending()

    assert reported == []


def test_the_real_thread_runs_jobs_and_stops_on_shutdown(logger):
    done = threading.Event()
    worker = NetworkWorker(logger, dispatch=inline)
    worker.submit("poll", lambda: 7, lambda result: done.set())

    assert done.wait(5) is True

    worker.shutdown(timeout=5)

    assert worker._thread.is_alive() is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_network_worker.py`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'src.model.network_worker'` (raised through `tests/support.py`).

- [ ] **Step 3: Add the constants**

In `src/config.py`, after the `RATE_LIMIT_RETRY_MS = 5000` line, add:

```python

# Every network call runs on one worker thread, which keeps this much time
# between two sends (SayIntentions answers "rate_limit" to a second message
# within a few seconds of the first) and between two information requests
# (so a handful of weather subscriptions does not reach the server as a
# burst). Polls are not paced; the polling interval already spaces them.
SEND_SPACING_SECONDS = 5
INFOREQ_SPACING_SECONDS = 1
```

Replace the `NETWORK_TIMEOUT = 15` line (and the comment above it, if any) with:

```python
# (connect, read) timeouts in seconds for every request the app makes. A
# short connect timeout so a dead host fails fast; the read timeout applies
# per response chunk, so it bounds a server that accepts the connection and
# then goes silent.
NETWORK_TIMEOUT = (10, 15)
```

- [ ] **Step 4: Write the worker**

Create `src/model/network_worker.py`:

```python
"""One worker thread for every network call, so the GUI thread never waits.

Hoppie and SayIntentions are plain HTTP: a poll, a send or a weather request
is a blocking round trip of up to NETWORK_TIMEOUT. Run on the GUI thread those
round trips freeze the window, and with it every screen-reader query. This
module owns the one thread that performs them. Callers submit a job (a
zero-argument callable) with a priority; the worker runs jobs in priority
order, spaces sends and information requests out as the servers ask, and
hands each result back to the GUI thread through wx.CallAfter. Nothing here
touches a wx object.
"""

import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import wx

from hoppie_connector import HoppieError

from src.config import INFOREQ_SPACING_SECONDS, SEND_SPACING_SECONDS

# Job priorities: lower runs first. A pilot's response must not queue behind
# a weather refresh.
PRIORITY_SEND = 0
PRIORITY_LINK = 1
PRIORITY_INFO = 2

# The kinds the worker paces, and the minimum gap in seconds after the
# previous job of the same kind finished.
DEFAULT_SPACING = {"send": SEND_SPACING_SECONDS, "inforeq": INFOREQ_SPACING_SECONDS}

_STOP = "stop"
_STOP_PRIORITY = 99


@dataclass(order=True)
class Job:
    """One unit of network work, ordered by priority and then by submission."""

    priority: int
    sequence: int
    kind: str = field(compare=False)
    fn: Callable = field(compare=False)
    on_done: Optional[Callable] = field(compare=False)
    generation: int = field(compare=False)


@dataclass
class JobResult:
    """What a job produced.

    Attributes:
        ok: True if fn returned, False if it raised
        value: fn's return value when ok
        error: The HoppieError text, or "<ExceptionName>: <text>" for any
            other exception
        job: The job this result belongs to
    """

    ok: bool
    value: object = None
    error: Optional[str] = None
    job: Optional[Job] = None


class NetworkWorker:
    """Runs network jobs on one daemon thread and reports back to the GUI thread.

    Args:
        logger: Application logger
        dispatch: Callable(fn, *args) that runs fn(*args) on the GUI thread;
            wx.CallAfter in the application, an inline call in tests
        start_thread: False in tests, where run_pending() runs the queue on
            the calling thread instead
        spacing: {kind: seconds} minimum gap between two jobs of a kind;
            DEFAULT_SPACING when None
        clock: Monotonic time source; injectable for the spacing tests
        sleep: Sleep function; injectable for the spacing tests
    """

    def __init__(
        self,
        logger,
        dispatch=wx.CallAfter,
        start_thread=True,
        spacing=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.logger = logger
        self._dispatch = dispatch
        self._spacing = dict(DEFAULT_SPACING if spacing is None else spacing)
        self._clock = clock
        self._sleep = sleep
        self._queue = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._generation = 0
        self._alive = True
        self._last_finished = {}
        self._thread = None
        if start_thread:
            self._thread = threading.Thread(
                target=self._run, name="network-worker", daemon=True
            )
            self._thread.start()

    @property
    def generation(self):
        """The current generation; jobs from an older one are dropped."""
        return self._generation

    def submit(self, kind, fn, on_done=None, priority=PRIORITY_INFO):
        """Queue a job.

        Args:
            kind: What the job is ("send", "poll", "connect", "disconnect",
                "inforeq", "simbrief", "update", "simconnect"); "send" and
                "inforeq" are paced
            fn: Zero-argument callable, run on the worker thread
            on_done: Callable(JobResult), run on the GUI thread; None to
                discard the result
            priority: PRIORITY_SEND, PRIORITY_LINK or PRIORITY_INFO

        Returns:
            Job: The queued job
        """
        job = Job(priority, next(self._sequence), kind, fn, on_done, self._generation)
        self._queue.put(job)
        return job

    def run_detached(self, kind, fn, on_done=None):
        """Run one job on a thread of its own, outside the queue.

        For a call that may block without a timeout (SimConnect's connect):
        stuck in the queue it would stall every send and poll, stuck on its
        own thread it costs nothing. The result comes back the same way.
        Without a worker thread (tests) the job is queued like any other.
        """
        if self._thread is None:
            return self.submit(kind, fn, on_done, PRIORITY_INFO)

        job = Job(PRIORITY_INFO, next(self._sequence), kind, fn, on_done, self._generation)
        threading.Thread(
            target=self._execute, args=(job,), name=f"{kind}-detached", daemon=True
        ).start()
        return job

    def new_generation(self):
        """Drop every queued job and the result of any job now running.

        Called on disconnect: work queued for the old session must not run
        against the next one, nor report into it.

        Returns:
            int: The new generation number
        """
        self._generation += 1
        return self._generation

    def pending(self):
        """Return how many jobs are queued, not counting one already running."""
        return self._queue.qsize()

    def run_pending(self):
        """Test mode: run every queued job on the calling thread, in order."""
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            if job.kind == _STOP:
                return
            self._execute(job)

    def shutdown(self, timeout=2.0):
        """Let queued work drain, then stop delivering results.

        With a thread, a stop marker is queued behind everything pending and
        the thread is given `timeout` seconds to reach it; a job stuck in a
        network call is abandoned (the thread is a daemon). Without a thread
        the queue is run inline. Either way nothing is dispatched afterwards.

        Args:
            timeout: Seconds to wait for the queue to drain
        """
        if self._thread is None:
            self.run_pending()
        else:
            self._queue.put(
                Job(_STOP_PRIORITY, next(self._sequence), _STOP, None, None, self._generation)
            )
            self._thread.join(timeout)
        self._alive = False

    def _run(self):
        """The worker thread's loop."""
        while True:
            job = self._queue.get()
            if job.kind == _STOP:
                return
            self._execute(job)

    def _execute(self, job):
        """Run one job and deliver its result, unless it went stale."""
        if job.generation < self._generation:
            self.logger.debug(f"Skipping a {job.kind} job from an earlier session")
            return

        self._pace(job.kind)
        result = self._run_job(job)
        self._last_finished[job.kind] = self._clock()

        if job.generation < self._generation:
            self.logger.debug(f"Dropping the result of a {job.kind} job from an earlier session")
            return

        self._deliver(job, result)

    def _pace(self, kind):
        """Wait until the gap the servers ask for has passed since the last job of this kind."""
        gap = self._spacing.get(kind)
        last = self._last_finished.get(kind)
        if gap is None or last is None:
            return

        wait = gap - (self._clock() - last)
        if wait > 0:
            self.logger.debug(f"Spacing {kind}: waiting {wait:.1f} s")
            self._sleep(wait)

    def _run_job(self, job):
        """Run fn, turning any exception into a failed result."""
        try:
            value = job.fn()
        except HoppieError as exc:
            return JobResult(ok=False, error=str(exc), job=job)
        except Exception as exc:
            # A bug or a local fault rather than a network answer: keep the
            # traceback, because app.spec builds with console=False and the
            # log file is the only place it can surface.
            self.logger.exception(f"{job.kind} job failed")
            return JobResult(ok=False, error=f"{type(exc).__name__}: {exc}", job=job)
        return JobResult(ok=True, value=value, job=job)

    def _deliver(self, job, result):
        """Hand a result to its callback on the GUI thread."""
        if not self._alive or job.on_done is None:
            return

        try:
            self._dispatch(job.on_done, result)
        except Exception as exc:
            # wx.CallAfter raises once the wx.App is gone (AssertionError) and
            # a dead window proxy raises RuntimeError. At shutdown neither
            # matters, and the worker must never take the process down.
            self.logger.warning(f"Dropped the result of a {job.kind} job: {exc}")
```

- [ ] **Step 5: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, 316 plus the fourteen tests in the new module. `tests/test_connection_manager.py::test_an_information_request_sends_a_timeout` still passes with the tuple.

- [ ] **Step 6: Commit**

```bash
git add src/model/network_worker.py src/config.py tests/support.py tests/test_network_worker.py
git commit -m "Add the network worker: one thread, a priority queue, pacing and generations"
```

---

### Task 2: Polls run on the worker

**Files:**
- Modify: `src/controller/polling_controller.py:15-28` (class docstring), `:30-87` (constructor), `:108-126` (`start`), `:159-199` (`on_poll_timer` split into submit and `_on_poll_result`)
- Modify: `src/gui/main_window.py:31` area (import `NetworkWorker`), `:107-117` (create the worker, pass it to the controller)
- Modify: `tests/test_polling_controller.py` (a `build()` helper and a two-argument `tick()`; every test that drives `on_poll_timer`; four new tests)
- Modify: `tests/test_main_window.py:60-77` (`build_window` shuts the worker down at teardown), `:222-229` (wiring assertion)
- Modify: `tests/test_harness.py:68-81` (shut the worker down in the `finally`)

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `PRIORITY_LINK`, `JobResult`, `inline_worker` (Task 1); `PollResult`, `LinkState`.
- Produces:
  - `PollingController(..., tick_callback=None, worker=None)`; attribute `worker`; `on_poll_timer` submits `("poll", connection_manager.poll, self._on_poll_result, PRIORITY_LINK)` and returns; `_on_poll_result(job_result)` runs today's tick body and re-arms the timer; while a poll is out a tick only re-arms the timer; a result arriving after `stop()` is ignored; a poll job that raised counts as one failed poll.
  - `MainWindow.worker` (a real `NetworkWorker`, created in `__init__` before the controllers).

- [ ] **Step 1: Write the failing tests**

In `tests/test_polling_controller.py`:

Add `inline_worker` to the `tests.support` import. Replace the `controller()` helper and add `build()` and a module-level `tick()` right after the imports:

```python
def controller(logger):
    return PollingController(logger, connection_manager=None)


def build(logger, connection, message_callback=None, **kwargs):
    """A controller wired to an inline worker.

    Returns:
        tuple: (poller, worker)
    """
    worker = inline_worker(logger)
    poller = PollingController(logger, connection, message_callback, worker=worker, **kwargs)
    return poller, worker


def tick(poller, worker):
    """Run one timer tick the way wx would: the one-shot has already stopped,
    the poll runs on the worker, and its result comes back to the controller."""
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)
    worker.run_pending()
```

Delete the old one-argument `tick(poller)` helper in the "link state and back-off" section. Then update every test that constructs a `PollingController` with a connection and drives a tick, so that it builds through `build()` and runs the worker:

- `test_a_stopped_poller_does_not_reschedule_itself`: `poller, _ = build(logger, FakeConnectionManager())`.
- `test_a_poll_that_raises_still_schedules_the_next_one` and `test_a_dropped_message_is_logged_before_it_propagates`: `poller, worker = build(logger, connection, explode)`; inside the `pytest.raises(RuntimeError)` block call `poller.on_poll_timer(None)` and then `worker.run_pending()` (the callback now raises out of the worker's inline dispatch).
- `test_repeated_activity_does_not_defer_a_pending_poll`, `test_an_idle_poll_is_pulled_forward_to_the_active_rate`: `poller, _ = build(logger, IdleConnection())`.
- `test_a_message_that_speeds_up_polling_mid_tick_still_schedules_once`: `poller, worker = build(logger, ClearanceConnection(message))`; replace `poller.on_poll_timer(None)` with `poller.on_poll_timer(None)` followed by `worker.run_pending()`; the assertion `len(schedule_calls) == 1` stands.
- Every test in the "link state and back-off" and "tick callback" sections: build with `build(logger, ScriptedConnection(...), ..., link_callback=..., tick_callback=...)` as each needs, and call `tick(poller, worker)`. In `test_a_failing_link_callback_does_not_lose_the_batch` the `poller.link.record_poll(failed(3))` arrange step stays as it is.

Append to the file:

```python
# --- the worker ---------------------------------------------------------------


def test_a_poll_runs_on_the_worker_not_in_the_timer_handler(logger, frame):
    """The GUI thread submits the poll and gets on with the event loop; the
    result comes back through the worker."""
    connection = ScriptedConnection(PollResult(ok=True, messages=["CLEARANCE"]))
    delivered = []
    poller, worker = build(logger, connection, delivered.append)
    poller.start(frame)
    poller.poll_timer.Stop()

    poller.on_poll_timer(None)

    assert (connection.polls, delivered, worker.pending()) == (0, [], 1)

    worker.run_pending()

    assert (connection.polls, delivered) == (1, ["CLEARANCE"])
    assert poller.is_running() is True


def test_a_tick_while_a_poll_is_out_does_not_queue_a_second_poll(logger, frame):
    """A slow server answers in its own time; stacking polls behind it would
    only add load and confuse the link state. The tick still re-arms the timer."""
    poller, worker = build(logger, ScriptedConnection())
    poller.start(frame)
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)

    poller.poll_timer.Stop()
    poller.on_poll_timer(None)

    assert worker.pending() == 1
    assert poller.is_running() is True


def test_a_result_arriving_after_stop_is_ignored(logger, frame):
    """Disconnect while a poll is out: its answer must neither restart the
    timer nor reach the window."""
    delivered = []
    poller, worker = build(
        logger, ScriptedConnection(PollResult(ok=True, messages=["LATE"])), delivered.append
    )
    poller.start(frame)
    poller.poll_timer.Stop()
    poller.on_poll_timer(None)
    poller.stop()

    worker.run_pending()

    assert delivered == []
    assert poller.is_running() is False


class BrokenConnection:
    """A poll() that raises, which the real manager never does."""

    def is_connected(self):
        return True

    def poll(self):
        raise KeyError("cnx")


def test_a_poll_job_that_raises_counts_as_a_failed_poll(logger, frame):
    """connection_manager.poll() never raises, but a bug there must degrade
    the link, not stop polling."""
    frame.SetStatusText = lambda text: None
    poller, worker = build(logger, BrokenConnection())
    poller.start(frame)

    tick(poller, worker)

    assert poller.link.state == LinkState.DEGRADED
    assert poller.is_running() is True
```

In `tests/test_main_window.py`, in the `build_window` fixture's teardown loop, add `window.worker.shutdown(timeout=1)` as the first statement of the loop body (before `window.weather_monitor.clear()`), and replace `test_the_real_window_listens_to_its_polling_controller` with:

```python
def test_the_real_window_listens_to_its_polling_controller(window):
    """The link, unreadable and tick callbacks are how a lost link, a dropped
    uplink and an unanswered logon reach the message list at all, and the
    worker is where every poll runs."""
    controller = window.polling_controller

    assert controller.link_callback == window._on_link_change
    assert controller.unreadable_callback == window._on_unreadable_messages
    assert controller.tick_callback == window._on_poll_tick
    assert controller.worker is window.worker
```

In `tests/test_harness.py::test_a_first_launch_asks_through_the_recorder_not_a_real_dialog`, add `window.worker.shutdown(timeout=1)` as the first line of the `finally` block.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_polling_controller.py tests/test_main_window.py tests/test_harness.py`
Expected: FAIL with `TypeError: PollingController.__init__() got an unexpected keyword argument 'worker'` and `AttributeError: 'MainWindow' object has no attribute 'worker'`.

- [ ] **Step 3: Move the poll onto the worker**

In `src/controller/polling_controller.py`:

Add to the imports: `from src.model.network_worker import PRIORITY_LINK`.

Replace the last paragraph of the class docstring ("Link health lives in a LinkState ...") with:

```python
    Link health lives in a LinkState fed with every poll result. While the link
    is lost the tick interval follows its back-off ladder, and a successful poll
    restores it. Polling never stops on its own except when the server rejects
    the logon code, which no retry can fix.

    The poll itself runs on the network worker: a tick submits it and returns,
    the result comes back on the GUI thread and re-arms the timer. One poll is
    out at a time; a tick that fires while it is still out only re-arms.
```

Add `worker=None,` to the constructor signature after `tick_callback=None,`, and to its docstring:

```python
            worker: The NetworkWorker that runs the polls
```

After `self.tick_callback = tick_callback` add:

```python
        self.worker = worker
        # True from submitting a poll until its result arrives, so a slow
        # server never has two polls stacked behind it.
        self._poll_in_flight = False
```

In `start()`, after `self._stopped = False`, add `self._poll_in_flight = False`.

Replace `on_poll_timer` (from `def on_poll_timer` down to the `finally: self._schedule_next()`) with:

```python
    def on_poll_timer(self, event):
        """Handle poll timer event: submit the poll to the worker."""
        if not self.connection_manager.is_connected():
            self.logger.warning("Not connected; stopping poll timer")
            self.stop()
            return

        if self._poll_in_flight:
            # The previous poll has not answered yet. Polling again would only
            # queue a second request behind it; keep the timer alive instead.
            self.logger.debug("Poll still in flight; skipping this tick")
            self._schedule_next()
            return

        self._poll_in_flight = True
        self.worker.submit(
            "poll", self.connection_manager.poll, self._on_poll_result, PRIORITY_LINK
        )

    def _on_poll_result(self, job_result):
        """Process a poll's result. Runs on the GUI thread.

        Args:
            job_result: The worker's JobResult wrapping the PollResult
        """
        self._poll_in_flight = False
        if self._stopped:
            # Stopped (disconnect, or a fatal error) while the poll was out.
            return

        if job_result.ok:
            result = job_result.value
        else:
            # poll() never raises; a bug there is still one failed poll, not
            # the end of polling.
            result = PollResult(
                ok=False, reason=job_result.error, failures=self.link.failures + 1
            )

        # The timer is one-shot, so the next tick only happens if this handler
        # arranges it. Message handling reaches into the GUI, SimConnect and a
        # nested logon, so anything raising there would otherwise end polling
        # for the rest of the session. stop() sets _stopped, so the fatal
        # branch below still ends polling deliberately.
        try:
            link_error = None
            try:
                self.link.record_poll(result)
                self._show_link_status()
            except Exception as exc:
                # The link callback reaches into the window. A failure there
                # must not cost the batch the server has already handed over.
                self.logger.exception("Error in link callback")
                link_error = exc

            if self.link.state == LinkState.FATAL:
                # The server rejected the logon code. The link callback has
                # already let the window tear the connection down.
                self.stop()
                return

            self._deliver(result)
            self.check_polling_timeout()
            if self.tick_callback:
                try:
                    self.tick_callback()
                except Exception as exc:
                    # Logged like the other callbacks: app.spec builds with
                    # console=False, so the log file is where this surfaces.
                    self.logger.exception("Error in tick callback")
                    if link_error is None:
                        link_error = exc
            if link_error is not None:
                raise link_error
        finally:
            self._schedule_next()
```

Add `from src.model.connection_manager import ConnectionManager, PollResult` in place of the existing `ConnectionManager` import.

In `src/gui/main_window.py`:

- Add `from src.model.network_worker import NetworkWorker` after the `PollingController` import.
- In `__init__`, immediately before `# Initialize controller`, add:

```python
        # One thread for every network call, so the GUI thread never waits on
        # the network and every result comes back through the event loop.
        self.worker = NetworkWorker(logger)
```

- Add `worker=self.worker,` to the `PollingController(...)` call after `tick_callback=self._on_poll_tick,`.

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, four more than after Task 1.

- [ ] **Step 5: Commit**

```bash
git add src/controller/polling_controller.py src/gui/main_window.py tests/test_polling_controller.py tests/test_main_window.py tests/test_harness.py
git commit -m "Run every poll on the network worker, one at a time"
```

---

### Task 3: Weather through the worker — automatic cycles and the manual request

**Files:**
- Modify: `src/model/weather_monitor.py` (module docstring, imports, constructor, class docstring, `stop`, `_run_cycle`; delete `_fetch_worker`, `_post_result`, `_post_cycle_finished`, `_on_cycle_finished`; add `_on_job_done`)
- Modify: `src/model/cpdlc_session.py:22-46` (constructor gains `worker`), `:241-262` (delete `_request_info`), the `request_weather` method at the end of the file
- Modify: `src/gui/main_window.py:124-132` (`WeatherMonitor(..., worker=self.worker)`), `:746-789` (`on_weather_request` split with `_on_weather_requested`)
- Modify: `tests/support.py` (`FakeWeatherMonitor` keeps subscriptions; `make_main_window` wires `window.worker = cpdlc_session.worker`)
- Modify: `tests/test_weather_monitor.py` (imports, fixtures pass a worker, three new tests), `tests/test_downlink_requests.py:18-31, 57-67` (`make_session` builds a worker; weather tests)
- Create: `tests/test_weather_requests.py`

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `PRIORITY_INFO`, `inline_worker` (Task 1).
- Produces:
  - `WeatherMonitor(logger, connection_manager, on_update=None, on_error=None, interval_ms=300000, worker=None)`; `_run_cycle()` submits one `("inforeq", partial(send_info_request, info_type, icao), partial(self._on_job_done, cycle, icao, info_type), PRIORITY_INFO)` per subscription, tagged with a cycle id; `check_now()` still returns whether a cycle started and refuses while one is pending; `stop()` bumps the cycle id so results in flight are ignored; `_on_result(icao, info_type, text, error)` unchanged.
  - `CpdlcSession(logger, connection_manager, clock=time.monotonic, worker=None)`; attribute `worker`; `request_weather(info_type, icao, on_done=None) -> bool`, with `on_done(True, report_text)` or `on_done(False, error_text)` on the GUI thread.
  - `MainWindow.on_weather_request` closes the dialog at once, shows `"Requesting <label> for <icao>..."` and finishes in `_on_weather_requested(success, result, icao, info_type, auto_update, was_watched)`.
  - `FakeWeatherMonitor.subscribe(icao, info_type, initial_text=None)`, `unsubscribe`, `is_subscribed`, `count`, attribute `subscriptions` (dict `(icao, info_type) -> initial_text`).
  - `make_main_window` sets `window.worker = cpdlc_session.worker`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, replace `FakeWeatherMonitor` with:

```python
class FakeWeatherMonitor:
    """Records the lifecycle calls and subscriptions the window makes on the weather monitor."""

    def __init__(self):
        self.stopped = False
        self.cleared = False
        self.started = False
        self.shut_down = False
        self.subscriptions = {}

    def start(self, parent_window):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear(self):
        self.cleared = True
        self.subscriptions.clear()

    def shutdown(self):
        self.shut_down = True

    def subscribe(self, icao, info_type, initial_text=None):
        self.subscriptions[(icao.upper(), info_type)] = initial_text

    def unsubscribe(self, icao, info_type):
        return self.subscriptions.pop((icao.upper(), info_type), None) is not None

    def is_subscribed(self, icao, info_type):
        return (icao.upper(), info_type) in self.subscriptions

    def count(self):
        return len(self.subscriptions)
```

In `make_main_window`, after `window.connection_manager = cpdlc_session.connection_manager`, add:

```python
    window.worker = cpdlc_session.worker
```

In `tests/test_weather_monitor.py`:

- Change the imports to:

```python
import pytest
from hoppie_connector import HoppieError

from src.model.weather_monitor import WeatherMonitor
from tests.support import inline_worker
```

- In the `atis` and `metar` fixtures and in `test_repeated_failures_drop_the_subscription`, `test_the_monitor_can_be_stopped_and_started_again` and the three `check_now` tests, pass `worker=inline_worker(logger)` to `WeatherMonitor(...)`.
- Replace the section header comment `# --- reporting whether a cycle actually started ---` and everything below it with:

```python
# --- the update cycle runs on the worker --------------------------------------


def build(logger, frame, connection, **callbacks):
    worker = inline_worker(logger)
    monitor = WeatherMonitor(logger, connection, worker=worker, **callbacks)
    monitor.start(frame)
    return monitor, worker


def test_check_now_says_a_cycle_started(logger, frame):
    """The dialog tells the user reports are being checked, so it needs to know
    whether that is true."""
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))
    monitor.subscribe("EGLL", "metar")

    assert monitor.check_now() is True


def test_check_now_says_nothing_started_while_stopped(logger, frame):
    """Disconnecting stops the monitor but leaves the dialog reachable. Saying
    a check is under way when none is would be worse than saying nothing."""
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))
    monitor.subscribe("EGLL", "metar")
    monitor.stop()

    assert monitor.check_now() is False


def test_check_now_says_nothing_started_with_no_subscriptions(logger, frame):
    monitor, _ = build(logger, frame, ScriptedConnection(["EGLL 1150Z"]))

    assert monitor.check_now() is False


def test_a_cycle_asks_for_every_subscription_through_the_worker(logger, frame):
    """One inforeq job per subscription; the worker spaces them out. A second
    cycle waits until the first has reported in full."""
    connection = ScriptedConnection(["EGLL 1150Z"])
    monitor, worker = build(logger, frame, connection)
    monitor.subscribe("EGLL", "metar")
    monitor.subscribe("EDDF", "metar")

    assert monitor.check_now() is True
    assert worker.pending() == 2
    assert monitor.check_now() is False

    worker.run_pending()

    assert connection.calls == 2
    assert monitor.check_now() is True


def test_results_of_a_stopped_cycle_are_ignored(logger, frame):
    """Disconnecting stops the monitor while a cycle is out; its answers must
    neither announce anything nor count against a subscription."""
    errors = []
    monitor, worker = build(
        logger,
        frame,
        ScriptedConnection([HoppieError("no data")]),
        on_error=lambda subscription, error: errors.append(error),
    )
    monitor.subscribe("EGLL", "metar")
    monitor.check_now()
    monitor.stop()

    worker.run_pending()

    assert monitor.get_subscriptions()[0].error_count == 0
    assert errors == []


def test_a_failed_fetch_counts_against_the_subscription(logger, frame):
    monitor, worker = build(logger, frame, ScriptedConnection([HoppieError("no data")]))
    monitor.subscribe("EGLL", "metar")
    monitor.check_now()

    worker.run_pending()

    assert monitor.get_subscriptions()[0].error_count == 1
```

In `tests/test_downlink_requests.py`:

- Add `inline_worker` to the `tests.support` import.
- In `make_session`, build the session as `CpdlcSession(logger, FakeConnectionManager(connected=connected), worker=inline_worker(logger))`.
- Replace the two weather tests with:

```python
def test_a_weather_request_delivers_the_report_when_it_arrives(session):
    outcomes = []

    assert session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text))) is True
    assert outcomes == []

    session.worker.run_pending()

    assert outcomes == [(True, "EGLL REPORT FOR metar")]
    assert session.connection_manager.info_requests == [("metar", "EGLL")]


def test_a_weather_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.request_weather("metar", "EGLL", lambda ok, text: None) is False


def test_a_failed_weather_request_reports_the_error(logger):
    session = CpdlcSession(
        logger,
        FakeConnectionManager(raise_with=HoppieError("no data")),
        worker=inline_worker(logger),
    )
    outcomes = []
    session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text)))

    session.worker.run_pending()

    assert outcomes == [(False, "no data")]
```

Create `tests/test_weather_requests.py`:

```python
"""The manual weather request through the window: the dialog closes at once,
the report or the error arrives from the worker."""

import wx

import src.gui.main_window as mw
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import (
    CLIENT_CALLSIGN,
    FakeClock,
    FakeConnectionManager,
    inline_worker,
    make_main_window,
)


class FakeWeatherDialog:
    """Stands in for WeatherDialog: answers OK with fixed details, never shows."""

    details = ("EGLL", "metar", True)

    def __init__(self, parent, is_watched=None):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_weather_details(self):
        return self.details

    def Destroy(self):
        pass


def build(logger, monkeypatch, details=("EGLL", "metar", True), connection=None):
    monkeypatch.setattr(mw, "WeatherDialog", FakeWeatherDialog)
    monkeypatch.setattr(FakeWeatherDialog, "details", details)
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, clock=FakeClock(), worker=inline_worker(logger))
    session.begin_session(CLIENT_CALLSIGN, "hoppie")
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def test_the_report_arrives_after_the_dialog_has_closed(logger, monkeypatch):
    window, manager = build(logger, monkeypatch)

    window.on_weather_request(None)

    assert window.status_texts == ["Requesting METAR for EGLL..."]
    assert rows(manager) == []

    window.worker.run_pending()

    assert rows(manager)[0][0] == "METAR"
    assert "EGLL REPORT FOR metar" in rows(manager)[0][1]
    assert window.status_texts[-1] == "METAR for EGLL received."


def test_a_report_is_only_watched_once_it_has_been_fetched(logger, monkeypatch):
    window, manager = build(logger, monkeypatch)

    window.on_weather_request(None)
    assert window.weather_monitor.subscriptions == {}

    window.worker.run_pending()

    assert window.weather_monitor.subscriptions == {("EGLL", "metar"): "EGLL REPORT FOR metar"}
    assert rows(manager)[-1] == ("SYSTEM", "Now watching METAR EGLL for changes")


def test_unchecking_the_box_stops_updates_before_the_request_goes_out(logger, monkeypatch):
    window, manager = build(logger, monkeypatch, details=("EGLL", "metar", False))
    window.weather_monitor.subscribe("EGLL", "metar")

    window.on_weather_request(None)

    assert window.weather_monitor.subscriptions == {}
    assert rows(manager) == [("SYSTEM", "Stopped automatic updates for METAR EGLL")]


def test_a_failed_request_is_reported_when_it_fails(logger, monkeypatch, message_boxes):
    from hoppie_connector import HoppieError

    window, manager = build(
        logger, monkeypatch, connection=FakeConnectionManager(raise_with=HoppieError("no data"))
    )

    window.on_weather_request(None)
    assert message_boxes.calls == []

    window.worker.run_pending()

    assert message_boxes.captions == ["Error"]
    assert "Failed to retrieve METAR for EGLL: no data." in message_boxes.calls[0][0]
    assert window.status_texts[-1] == "Could not retrieve METAR for EGLL."
    assert window.weather_monitor.subscriptions == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_weather_monitor.py tests/test_downlink_requests.py tests/test_weather_requests.py`
Expected: FAIL with `TypeError: WeatherMonitor.__init__() got an unexpected keyword argument 'worker'` and `TypeError: CpdlcSession.__init__() got an unexpected keyword argument 'worker'`.

- [ ] **Step 3: Rewrite the weather cycle**

In `src/model/weather_monitor.py`:

Replace the module docstring with:

```python
"""Automatic weather updates for subscribed airports.

Neither Hoppie nor SayIntentions push weather to the aircraft, so an automatic
update is really a polite re-request on a timer. This module keeps the list of
subscribed airports, re-fetches each report through the network worker so the
GUI never blocks on network I/O, and only announces a report when it has
actually changed (a new ATIS letter, or amended METAR/TAF text).
"""
```

Replace the imports with:

```python
import functools
import time

import wx

from hoppie_connector import HoppieError

from src.model.network_worker import PRIORITY_INFO
from src.utils.weather_parsing import (
    describe_report,
    report_signature,
    report_type_label,
)
```

Delete the `_REQUEST_SPACING_SECONDS` constant and its comment (the worker's `INFOREQ_SPACING_SECONDS` replaces it); keep `MAX_CONSECUTIVE_ERRORS`.

Replace the `WeatherMonitor` class docstring and constructor (down to `self._shutting_down = False`) with:

```python
class WeatherMonitor:
    """Keeps subscribed weather reports up to date and reports the changes.

    All subscription state is owned by the GUI thread. The timer builds a
    snapshot and submits one information request per subscription to the
    network worker; each result comes back on the GUI thread tagged with the
    cycle it belongs to, so a cycle cancelled by stop() is ignored when it
    reports, and nothing here is touched from two threads at once.
    """

    def __init__(
        self,
        logger,
        connection_manager,
        on_update=None,
        on_error=None,
        interval_ms=300000,
        worker=None,
    ):
        """Initialize the weather monitor.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            on_update: Callback(subscription, text, description) for new reports
            on_error: Callback(subscription, error_text) for repeated failures
            interval_ms: How often to re-check each subscription
            worker: The NetworkWorker that performs the requests
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.on_update = on_update
        self.on_error = on_error
        self.interval_ms = interval_ms
        self.worker = worker

        self._subscriptions = {}
        self._timer = None
        self._parent = None
        self._shutting_down = False
        # Each cycle gets a number; a result tagged with an older one is
        # ignored. _cycle_pending counts the current cycle's outstanding jobs.
        self._cycle_id = 0
        self._cycle_pending = 0
```

Replace `stop()` with:

```python
    def stop(self):
        """Stop the update timer, leaving subscriptions in place.

        A cycle still out is abandoned: its results arrive tagged with the
        old cycle id and are ignored.
        """
        self._shutting_down = True
        self._cycle_id += 1
        self._cycle_pending = 0
        if self._timer and self._timer.IsRunning():
            self._timer.Stop()
            self.logger.info("Stopped weather monitor")
```

Replace everything from `def _run_cycle` to the end of `_on_cycle_finished` (keep `_on_result`) with:

```python
    def _run_cycle(self):
        """Submit a fetch for every subscription to the worker.

        Returns:
            bool: True if a cycle started, False if it was skipped.
        """
        if self._shutting_down or not self._subscriptions or self._parent is None:
            return False

        if self._cycle_pending:
            self.logger.debug("Weather update cycle still running, skipping this tick")
            return False

        if not self.connection_manager.is_connected():
            self.logger.debug("Not connected, skipping weather update cycle")
            return False

        # Snapshot on the GUI thread so the worker never touches the live dict.
        pending = [(s.icao, s.info_type) for s in self._subscriptions.values()]

        self._cycle_id += 1
        cycle = self._cycle_id
        self._cycle_pending = len(pending)
        for icao, info_type in pending:
            self.worker.submit(
                "inforeq",
                functools.partial(self.connection_manager.send_info_request, info_type, icao),
                functools.partial(self._on_job_done, cycle, icao, info_type),
                PRIORITY_INFO,
            )
        return True

    def _on_job_done(self, cycle, icao, info_type, result):
        """Apply one fetch result to the cycle it belongs to. Runs on the GUI thread.

        Args:
            cycle: The cycle id the job was submitted under
            icao: Airport ICAO code
            info_type: Report type key
            result: The worker's JobResult
        """
        if cycle != self._cycle_id:
            # stop() ran while the request was out; the pilot may be
            # disconnected or connected as someone else by now.
            return

        self._cycle_pending -= 1
        if result.ok:
            self._on_result(icao, info_type, result.value, None)
        else:
            self._on_result(icao, info_type, None, result.error)
```

Delete the now-unused `HoppieError` import if nothing else in the module uses it (check with a search; `_fetch_worker` was its only user).

In `src/model/cpdlc_session.py`:

- Constructor: add `worker=None,` after `clock: Callable[[], float] = time.monotonic,`; docstring entry `worker: The NetworkWorker that performs the requests and sends`; after `self.clock = clock` add `self.worker = worker`.
- Add `from src.model.network_worker import PRIORITY_INFO` to the imports (Task 4 adds `PRIORITY_SEND`).
- Delete `_request_info`.
- Replace `request_weather` with:

```python
    def request_weather(self, info_type, icao, on_done=None):
        """Request a weather/information report for an airport.

        Args:
            info_type: Report type key ("metar", "taf", "shorttaf", "vatatis")
            icao: Airport ICAO code
            on_done: Callable(success, report_text_or_error), run on the GUI
                thread when the report arrives

        Returns:
            bool: True if the request was queued, False if not connected
        """
        label = report_type_label(info_type)
        if not self.connection_manager.is_connected():
            self.logger.warning(f"{label} request attempted without active connection")
            return False

        def finished(result):
            if not result.ok:
                self.logger.error(f"Failed to request {label} for {icao}: {result.error}")
            if on_done is not None:
                on_done(result.ok, result.value if result.ok else result.error)

        self.worker.submit(
            "inforeq",
            lambda: self.connection_manager.send_info_request(info_type, icao),
            finished,
            PRIORITY_INFO,
        )
        return True
```

In `src/gui/main_window.py`:

- Pass `worker=self.worker,` to the `WeatherMonitor(...)` call (after `interval_ms=...`). The worker is created before the controllers in Task 2, so it exists here.
- Replace `on_weather_request` with:

```python
    def on_weather_request(self, _):
        """Request a METAR, TAF or ATIS, optionally keeping it up to date."""
        if not self._require_connection("request weather information"):
            return

        self.logger.debug("Opening weather information request dialog")

        dlg = WeatherDialog(self, is_watched=self._is_weather_watched)

        if dlg.ShowModal() == wx.ID_OK:
            icao, info_type, auto_update = dlg.get_weather_details()

            label = report_type_label(info_type)
            was_watched = self.weather_monitor.is_subscribed(icao, info_type)

            # Unchecking the box is how the user stops updates, so act on it
            # whether or not this request succeeds.
            if was_watched and not auto_update:
                self.weather_monitor.unsubscribe(icao, info_type)
                self._add_custom_message(
                    f"Stopped automatic updates for {label} {icao}", "SYSTEM"
                )

            self.SetStatusText(f"Requesting {label} for {icao}...")
            queued = self.cpdlc_session.request_weather(
                info_type,
                icao,
                lambda success, result: self._on_weather_requested(
                    success, result, icao, info_type, auto_update, was_watched
                ),
            )
            if not queued:
                wx.MessageBox(
                    f"Failed to retrieve {label} for {icao}: not connected.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def _on_weather_requested(self, success, result, icao, info_type, auto_update, was_watched):
        """Show a requested report, or say why it did not come. Runs on the GUI thread.

        Args:
            success: Whether the report arrived
            result: The report text, or the error text
            icao: Airport ICAO code
            info_type: Report type key
            auto_update: Whether the pilot asked to keep the report updated
            was_watched: Whether it was already being watched when asked
        """
        label = report_type_label(info_type)
        if not success:
            error_detail = f": {result}" if result else ""
            self.SetStatusText(f"Could not retrieve {label} for {icao}.")
            wx.MessageBox(
                f"Failed to retrieve {label} for {icao}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
            return

        self._add_weather_message(result, icao, info_type)
        self.SetStatusText(f"{label} for {icao} received.")

        # Only start watching a report we know we can actually fetch.
        if auto_update:
            self.weather_monitor.subscribe(icao, info_type, initial_text=result)
            if not was_watched:
                self._add_custom_message(
                    f"Now watching {label} {icao} for changes", "SYSTEM"
                )
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, eight more than after Task 2 (three monitor tests, one downlink test, four window tests).

- [ ] **Step 5: Commit**

```bash
git add src/model/weather_monitor.py src/model/cpdlc_session.py src/gui/main_window.py tests/support.py tests/test_weather_monitor.py tests/test_downlink_requests.py tests/test_weather_requests.py
git commit -m "Fetch weather through the network worker, for the timer and for the pilot"
```

---

### Task 4: Every downlink goes through the worker and reports through `on_done`

**Files:**
- Modify: `src/model/cpdlc_session.py` (imports; new `_next_min`, `_submit_send`, `_send_request`; rewrite `logon`, `logoff`, `send_altitude_change_request`, `send_acknowledgement`, `send_direct_request`, `send_speed_request`, `send_when_can_we_expect`, `send_telex`, `send_pdc_request`; `handle_handover` gains `on_done`)
- Modify: `src/gui/main_window.py` (imports: `functools`, drop `RATE_LIMIT_RETRY_MS`; `__init__` loses `_pending_retry`; `on_logon`, `on_logoff`, `_end_dialogue`, the six request handlers, `_on_acknowledge_message`, `_follow_handover`; delete `_retry_later` and `_cancel_pending_retry` and their three calls)
- Modify: `src/config.py` (delete `RATE_LIMIT_RETRY_MS` and its comment)
- Modify: `tests/support.py` (delete `FakeCallLater`; `make_main_window` loses the retry shim)
- Modify: `tests/test_downlink_requests.py`, `tests/test_cpdlc_session.py`, `tests/test_acknowledge_path.py`, `tests/test_uplink_handling.py`, `tests/test_session_lifecycle.py`, `tests/test_logon_status.py`, `tests/test_link_status.py`, `tests/test_main_window_wiring.py`

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `PRIORITY_SEND`, `inline_worker` (Task 1); `CpdlcSession.worker` (Task 3).
- Produces:
  - Every `CpdlcSession` send returns `bool` (queued, or refused by a precondition) and takes a trailing `on_done=None`: `logon(station, on_done=None)`, `logoff(on_done=None)`, `send_altitude_change_request(altitude, reason=None, on_done=None)`, `send_direct_request(fix, reason=None, on_done=None)`, `send_speed_request(speed, is_mach, reason=None, on_done=None)`, `send_when_can_we_expect(message_text, on_done=None)`, `send_telex(recipient, message, on_done=None)`, `send_pdc_request(origin_icao, destination_icao, aircraft_code, stand_designator, atis_code, on_done=None)`, `send_acknowledgement(sender, min_value, response, on_done=None)`, `handle_handover(old, new, on_done=None)`. `on_done(success, text_or_error)` runs on the GUI thread: the element text on success, the error text on failure.
  - State changes at enqueue time: the MIN is spent; `logoff()` clears the station, the pending logon and the handover window; `logon()` records the pending logon (and clears it again if the REQUEST LOGON fails to go out); `logon()` while logged on queues LOGOFF then REQUEST LOGON, both reporting to the same `on_done`.
  - `MainWindow`: `_send_callback(what)`, `_on_logon_frame(station, success, text_or_error)`, `_on_logoff_frame(station, success, text_or_error, quiet=False)`, `_on_acknowledgement_sent(message_id, response, success, text_or_error)`, `_on_handover_logon(new_station, success, text_or_error)`; `_on_acknowledge_message(message_id, response)` (no `retried`). Status texts `"Sending <what>..."` / `"Sent <text>."` / `"Could not send <what>."`, `"Logging on to X..."`, `"Sending LOGOFF to X..."`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`: delete the `FakeCallLater` class; in `make_main_window` delete the lines from `# wx.CallLater needs a running wx.App; record delayed callbacks instead.` through `window._retry_later = _retry_later` (keep `window._callsign_clash_announced = False` and what follows), and change the docstring's last paragraph to: `The window's deferred callbacks run synchronously, since there is no event loop; a queued send runs when the test calls window.worker.run_pending().`

Replace `tests/test_downlink_requests.py` in full with:

```python
"""Tests for the exact text of the downlinks the client can send.

The wire format is what a controller reads, so each message is asserted
literally rather than by shape: a reworded element shows up here instead of on
the network. Sends are queued on the worker, so each test runs the worker
before looking at what went out.
"""

import pytest
from hoppie_connector import HoppieError

from tests.support import FakeConnectionManager, inline_worker
from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER
from src.model.cpdlc_session import CpdlcSession

STATION = "EGGX"


@pytest.fixture
def make_session(logger):
    def build(connected=True, station=STATION, connection=None):
        if connection is None:
            connection = FakeConnectionManager(connected=connected)
        session = CpdlcSession(logger, connection, worker=inline_worker(logger))
        session.begin_session("BAW123", "hoppie")
        session.current_station = station
        return session

    return build


@pytest.fixture
def session(make_session):
    return make_session()


def sent(session):
    """Run the worker and return the CPDLC frames that went out."""
    session.worker.run_pending()
    return session.connection_manager.sent


def outcomes_of(session, send):
    """Queue a send with a recording callback, run the worker, return (queued, outcomes)."""
    outcomes = []
    queued = send(lambda success, text: outcomes.append((success, text)))
    session.worker.run_pending()
    return queued, outcomes


# --- addressing and preconditions ---------------------------------------------


def test_each_message_advances_the_min_counter(session):
    """A reused MIN makes the station read the second message as the first."""
    session.send_altitude_change_request("FL350")
    session.send_altitude_change_request("FL370")

    assert [frame[1] for frame in sent(session)] == [1, 2]


def test_a_request_without_a_station_is_refused(make_session):
    session = make_session(station="")

    assert session.send_altitude_change_request("FL350") is False
    assert sent(session) == []


def test_a_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.send_altitude_change_request("FL350") is False


def test_a_send_is_queued_not_transmitted_at_once(session):
    """The GUI thread only queues the frame; the worker transmits it."""
    assert session.send_altitude_change_request("FL350") is True
    assert session.connection_manager.sent == []

    session.worker.run_pending()

    assert session.connection_manager.sent == [(STATION, 1, "Y", "REQUEST FL350", None)]


# --- weather ------------------------------------------------------------------


def test_a_weather_request_delivers_the_report_when_it_arrives(session):
    outcomes = []

    assert session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text))) is True
    assert outcomes == []

    session.worker.run_pending()

    assert outcomes == [(True, "EGLL REPORT FOR metar")]
    assert session.connection_manager.info_requests == [("metar", "EGLL")]


def test_a_weather_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.request_weather("metar", "EGLL", lambda ok, text: None) is False


def test_a_failed_weather_request_reports_the_error(make_session):
    session = make_session(connection=FakeConnectionManager(raise_with=HoppieError("no data")))
    outcomes = []
    session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text)))

    session.worker.run_pending()

    assert outcomes == [(False, "no data")]


# --- reason wording -----------------------------------------------------------


def test_a_performance_reason_uses_the_full_standard_wording(session):
    """DM66 is "DUE TO AIRCRAFT PERFORMANCE". Each dialog used to spell the
    value out for itself, so the short "PERFORMANCE" had spread to all of them.
    """
    _, outcomes = outcomes_of(
        session,
        lambda done: session.send_altitude_change_request("FL350", REASON_AIRCRAFT_PERFORMANCE, done),
    )

    assert outcomes == [(True, "REQUEST FL350 DUE TO AIRCRAFT PERFORMANCE")]


def test_a_weather_reason_is_unchanged(session):
    _, outcomes = outcomes_of(
        session, lambda done: session.send_direct_request("MALOT", REASON_WEATHER, done)
    )

    assert outcomes == [(True, "REQUEST DIRECT TO MALOT DUE TO WEATHER")]


# --- the remaining downlinks --------------------------------------------------


def test_a_logon_request_uses_min_one_and_expects_an_answer(make_session):
    session = make_session(station="")

    queued, outcomes = outcomes_of(session, lambda done: session.logon("EGGX", done))

    assert (queued, outcomes) == (True, [(True, "REQUEST LOGON")])
    assert session.connection_manager.sent == [("EGGX", 1, "Y", "REQUEST LOGON", None)]
    assert (session.pending_logon_station, session.pending_logon_min) == ("EGGX", 1)


def test_a_logoff_needs_no_response_and_clears_the_station_at_once(session):
    assert session.logoff() is True
    assert session.get_current_station() == ""

    assert sent(session) == [(STATION, 1, "NE", "LOGOFF", None)]


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
    _, outcomes = outcomes_of(
        session, lambda done: session.send_speed_request(speed, is_mach, reason, done)
    )

    assert outcomes == [(True, expected)]


def test_a_when_can_we_expect_inquiry_is_sent_verbatim(session):
    text = "WHEN CAN WE EXPECT HIGHER LEVEL"

    _, outcomes = outcomes_of(session, lambda done: session.send_when_can_we_expect(text, done))

    assert outcomes == [(True, text)]


def test_every_request_goes_to_the_current_station_expecting_an_answer(session):
    session.send_altitude_change_request("FL350")
    session.send_direct_request("MALOT")
    session.send_speed_request("082", True)
    session.send_when_can_we_expect("WHEN CAN WE EXPECT LOWER LEVEL")

    frames = sent(session)
    assert [frame[0] for frame in frames] == [STATION] * 4
    assert [frame[2] for frame in frames] == ["Y"] * 4
    assert [frame[1] for frame in frames] == [1, 2, 3, 4]


def test_a_telex_goes_to_its_recipient_unchanged(session):
    _, outcomes = outcomes_of(session, lambda done: session.send_telex("EDDF", "HELLO THERE", done))

    assert outcomes == [(True, "HELLO THERE")]
    assert session.connection_manager.telexes == [("EDDF", "HELLO THERE")]


def test_a_pdc_request_is_a_telex_to_the_departure_airport(session):
    _, outcomes = outcomes_of(
        session, lambda done: session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K", done)
    )

    text = "REQUEST PREDEP CLEARANCE BAW123 A339 TO LIMC AT EGLL STAND 521 ATIS K"
    assert outcomes == [(True, text)]
    assert session.connection_manager.telexes == [("EGLL", text)]


def test_a_pdc_request_needs_a_callsign(make_session):
    session = make_session()
    session.callsign = ""

    assert session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K") is False


# --- failure paths ------------------------------------------------------------

SENDS = [
    # (name, station logged on before the send, the send taking on_done)
    ("logon", "", lambda s, done: s.logon("EGGX", done)),
    ("logoff", STATION, lambda s, done: s.logoff(done)),
    ("altitude", STATION, lambda s, done: s.send_altitude_change_request("FL350", on_done=done)),
    ("direct", STATION, lambda s, done: s.send_direct_request("MALOT", on_done=done)),
    ("speed", STATION, lambda s, done: s.send_speed_request("082", True, on_done=done)),
    ("when-can-we", STATION, lambda s, done: s.send_when_can_we_expect("WHEN CAN WE EXPECT HIGHER LEVEL", done)),
    ("acknowledgement", STATION, lambda s, done: s.send_acknowledgement(STATION, 7, "WILCO", done)),
    ("telex", STATION, lambda s, done: s.send_telex("EDDF", "HELLO", done)),
    ("pdc", STATION, lambda s, done: s.send_pdc_request("EGLL", "LIMC", "A339", "521", "K", done)),
]


@pytest.mark.parametrize(
    "station, send", [case[1:] for case in SENDS], ids=[case[0] for case in SENDS]
)
def test_a_transmission_failure_reaches_the_callback(make_session, station, send):
    """The error text reaches the dialog through on_done; nothing was recorded as sent."""
    session = make_session(
        station=station, connection=FakeConnectionManager(raise_with=HoppieError("boom"))
    )
    outcomes = []

    assert send(session, lambda success, text: outcomes.append((success, text))) is True
    session.worker.run_pending()

    assert outcomes == [(False, "boom")]
    assert (session.connection_manager.sent, session.connection_manager.telexes) == ([], [])


def test_a_failed_send_leaves_a_gap_in_the_min_sequence_rather_than_a_reused_number(make_session):
    """The MIN is spent when the frame is queued. A station does not mind a
    gap; it does mind seeing a number twice."""
    session = make_session(connection=FakeConnectionManager(raise_with=HoppieError("boom")))
    session.send_altitude_change_request("FL350")
    session.worker.run_pending()

    session.connection_manager.raise_with = None
    session.send_altitude_change_request("FL370")

    assert sent(session) == [(STATION, 2, "Y", "REQUEST FL370", None)]
```

In `tests/test_cpdlc_session.py`:

- Add `inline_worker` to the `tests.support` import and build every session in the file through `build()` (the five oldest tests construct `CpdlcSession(logger, FakeConnectionManager())` directly; change them to `build(logger)`); `build()` passes `worker=inline_worker(logger)` to the constructor.
- After any `logon`, `logoff` or `handle_handover` call whose frames a test asserts through `connection_manager.sent`, call `session.worker.run_pending()` first: `test_logging_on_while_logged_on_sends_logoff_first` (its `result` assertion becomes `assert result is True`), `test_relogging_on_to_the_same_station_closes_the_dialogue_first`, `test_a_handover_moves_the_logon_and_keeps_the_old_station_answerable` (`result is True`), `test_a_handover_from_a_station_that_is_not_logged_on_is_ignored` (`handle_handover(...) is False`), `test_a_handover_sends_no_logoff`.
- Replace `test_a_failed_logoff_aborts_the_new_logon` with:

```python
def test_a_failed_logoff_does_not_stop_the_new_logon(logger):
    """Both frames are queued before either goes out (the worker spaces
    them); each reports for itself, and a REQUEST LOGON that failed to go
    out leaves nothing pending."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    session = build(logger, connection)
    session.handle_logon_accepted("EDYY")
    outcomes = []

    assert session.logon("EDGG", lambda ok, text: outcomes.append((ok, text))) is True
    assert session.get_current_station() == ""
    assert session.pending_logon_station == "EDGG"

    session.worker.run_pending()

    assert outcomes == [(False, "timed out"), (False, "timed out")]
    assert session.pending_logon_station is None
```

Replace `tests/test_acknowledge_path.py` in full with:

```python
"""End-to-end tests for the acknowledgement path through MainWindow.

A response is queued on the worker; the message is retired and echoed only
once the frame has gone out.
"""

from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

from tests.support import FakeConnectionManager, answerable, inline_worker, make_main_window, uplink

from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

STATION = "LSAG"


def build(logger, connection=None):
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, worker=inline_worker(logger))
    session.begin_session("DLH123", "hoppie")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager, connection


def acknowledge(window, message_id, response):
    window._on_acknowledge_message(message_id, response)
    window.worker.run_pending()


def test_wilco_is_a_complete_response_frame(logger):
    """Recipient, own MIN, response requirement "N", text and the uplink's MIN
    as MRN. TODOS item 21: acknowledgements once went out as "NE", which some
    ATC clients ignore, and nothing asserted the requirement."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]


def test_each_acknowledgement_uses_the_next_own_min(logger):
    window, manager, connection = build(logger)
    first = manager.add_message(uplink(STATION, 53))
    second = manager.add_message(uplink(STATION, 54, "DESCEND TO AND MAINTAIN FL240"))

    acknowledge(window, first, "WILCO")
    acknowledge(window, second, "UNABLE")

    assert [(frame[1], frame[3], frame[4]) for frame in connection.sent] == [
        (1, "WILCO", 53),
        (2, "UNABLE", 54),
    ]


def test_an_acknowledgement_is_queued_and_the_status_bar_says_so(logger):
    """The GUI thread queues the response and carries on; the echo, the status
    and the retirement follow once it has gone out."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == []
    assert window.status_texts[-1] == "Sending WILCO..."
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True

    window.worker.run_pending()

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]
    assert window.status_texts[-1] == "Sent WILCO."
    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (False, [])
    assert window.polling_controller.active_calls == 1


def test_wilco_retires_the_message(logger):
    window, manager, _ = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (False, [])


def test_standby_is_sent_but_leaves_the_message_answerable(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "STANDBY")

    assert connection.sent[-1][3] == "STANDBY"
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True


def test_an_unknown_id_sends_nothing_and_tells_the_user(logger):
    window, _manager, connection = build(logger)

    acknowledge(window, 4242, "WILCO")

    assert connection.sent == []
    assert window.status_texts != []


def test_a_custom_message_id_sends_nothing_and_does_not_raise(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    acknowledge(window, message_id, "WILCO")

    assert connection.sent == []


def test_a_failed_acknowledgement_is_reported_and_stays_answerable(logger, message_boxes):
    """The worker paces sends, so SayIntentions' rate_limit should not recur;
    if it does, it is reported like any other failure and the message keeps
    its response menu."""
    connection = FakeConnectionManager(raise_with=HoppieError("rate_limit"))
    window, manager, _ = build(logger, connection)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert message_boxes.captions == ["Error"]
    assert "rate_limit" in message_boxes.calls[0][0]
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True
    assert window.status_texts[-1] == "Could not send WILCO."
```

In `tests/test_uplink_handling.py`: add `inline_worker` to the support import and `worker=inline_worker(logger)` to the `CpdlcSession(...)` call in `build()`. In `test_a_handover_logs_off_and_requests_logon_with_the_next_station` and `test_the_logged_handover_sequence_tunes_and_answers_the_late_contact`, call `window.worker.run_pending()` right after the HANDOVER uplink is delivered (before the assertions on `connection.sent`, the status texts and `active_calls`).

In `tests/test_session_lifecycle.py`: add `inline_worker` to the support import and `worker=inline_worker(logger)` to the session in `build()`. Then:

- `test_disconnect_logs_off_and_forgets_the_dialogue`: after `window.on_disconnect()` add `window.worker.run_pending()`; replace the `rows(manager) == [...]` assertion with `assert (CLIENT_CALLSIGN, "LOGOFF") in rows(manager)` and `assert ("SYSTEM", "Disconnected from CPDLC network") in rows(manager)` (Task 5 pins the order).
- `test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails`: add `window.worker.run_pending()` after `on_disconnect()`; replace `rows(manager)[0] == ...` with `assert ("SYSTEM", "Could not send LOGOFF to EDYY: timed out") in rows(manager)`.
- `test_disconnect_closes_a_handover_in_progress`: add `window.worker.run_pending()` after `on_disconnect()`.
- `test_exit_logs_off_and_forgets_the_dialogue`, `test_exit_reports_a_logoff_it_could_not_send`: add `window.worker.run_pending()` after `window.on_close(...)`.
- `test_a_manual_logon_while_logged_on_echoes_the_logoff_it_sends`: add `window.worker.run_pending()` after `window.on_logon(None)`; the three assertions stand.

In `tests/test_logon_status.py`: add `inline_worker` to the support import; every `CpdlcSession(logger, FakeConnectionManager(), ...)` gains `worker=inline_worker(logger)`.

In `tests/test_link_status.py`: add `inline_worker` to the support import and `worker=inline_worker(logger)` to the session in `build()`; delete `test_a_fatal_teardown_cancels_a_pending_retry`.

In `tests/test_main_window_wiring.py`: add `inline_worker` to the support import and `worker=inline_worker(logger)` to the session in the `window` fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_downlink_requests.py tests/test_cpdlc_session.py tests/test_acknowledge_path.py tests/test_session_lifecycle.py`
Expected: FAIL. The downlink tests fail on the return value (`(True, "REQUEST FL350") is True` is false) and on `TypeError: ... got an unexpected keyword argument 'on_done'`; the acknowledgement tests fail because the frame goes out synchronously (`connection.sent == []` fails).

- [ ] **Step 3: Send through the worker in the session**

In `src/model/cpdlc_session.py`:

Change the network worker import to `from src.model.network_worker import PRIORITY_INFO, PRIORITY_SEND`.

Add after `_clear_pending()`:

```python
    def _next_min(self):
        """Take the next MIN.

        Spent when a frame is queued, not when it is sent, so a send that
        fails leaves a gap in the sequence rather than a number the station
        has already seen.
        """
        value = self.cpdlc_min_counter
        self.cpdlc_min_counter += 1
        return value

    def _submit_send(self, text, operation, on_done):
        """Queue an outbound frame on the network worker and report its outcome.

        The frame is built, validated and given its MIN before this is called,
        so the session's state is settled at once; only the transmission
        waits. The worker spaces sends SEND_SPACING_SECONDS apart.

        Args:
            text: The frame's element text, handed to on_done on success
            operation: Zero-argument callable doing the send; runs on the worker
            on_done: Callable(success, text_or_error), run on the GUI thread,
                or None
        """

        def finished(result):
            if result.ok:
                self.logger.info(f"Sent {text}")
            else:
                self.logger.error(f"Failed to send {text}: {result.error}")
            if on_done is not None:
                on_done(result.ok, text if result.ok else result.error)

        self.worker.submit("send", operation, finished, PRIORITY_SEND)

    def _send_request(self, message, on_done, label):
        """Queue a request to the current station that expects a Y/N answer.

        Args:
            message: The element text
            on_done: Callable(success, text_or_error), or None
            label: What the request is, for the log

        Returns:
            bool: True if queued, False without a station or a connection
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(f"{label} attempted without active station or connection")
            return False

        station = self.current_station
        min_value = self._next_min()
        self.logger.info(f"Sending {message} to {station} (MIN {min_value})")
        self._submit_send(
            message,
            lambda: self.connection_manager.send_cpdlc(
                station, min_value, RR.YES.value, message
            ),
            on_done,
        )
        return True
```

Replace `logon()` with:

```python
    def logon(self, station: str, on_done=None) -> bool:
        """Log on to a CPDLC station.

        A station still logged on is sent LOGOFF first, so it learns the
        dialogue has ended before the next one starts (audit M-7); the worker
        spaces the two frames out. Both frames report through on_done.

        Args:
            station: The station to log on to
            on_done: Callable(success, text_or_error), run on the GUI thread
                once per frame

        Returns:
            bool: True if the request was queued, False if not connected or
                the station name is not four characters
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Logon attempted without active connection")
            return False

        # Validate station name is exactly 4 characters
        if len(station) != 4:
            self.logger.warning(
                f"Invalid station name: {station} (must be 4 characters)"
            )
            return False

        if self.current_station:
            self.logoff(on_done)

        self.logger.info(f"Attempting to logon to station: {station}")
        self.cpdlc_min_counter = 1
        min_value = self._next_min()
        # Track the pending logon for MRN validation on LOGON ACCEPTED, and
        # when it was sent so an unanswered request can be given up on
        self.pending_logon_min = min_value
        self.pending_logon_station = station
        self.pending_logon_at = self.clock()

        def finished(success, text_or_error):
            if not success and self.pending_logon_station == station:
                # The request never left, so nothing is pending.
                self._clear_pending()
            if on_done is not None:
                on_done(success, text_or_error)

        self._submit_send(
            "REQUEST LOGON",
            lambda: self.connection_manager.send_cpdlc(
                station, min_value, RR.YES.value, "REQUEST LOGON"
            ),
            finished,
        )
        return True
```

Replace `logoff()` with:

```python
    def logoff(self, on_done=None) -> bool:
        """Log off from the current station.

        The dialogue ends now, whether or not the frame gets through: the
        pilot is leaving it, and the caller reports a LOGOFF that could not be
        sent. The handover window closes with it.

        Args:
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the LOGOFF was queued, False without a station or a
                connection
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.debug("Logoff attempted without active station or connection")
            return False

        station = self.current_station
        min_value = self._next_min()
        self.logger.info(f"Logging off from station: {station}")
        self.current_station = ""
        self._clear_pending()
        self.previous_station = ""
        self.previous_station_until = None
        self._submit_send(
            "LOGOFF",
            lambda: self.connection_manager.send_cpdlc(
                station, min_value, RR.NOT_REQUIRED.value, "LOGOFF"
            ),
            on_done,
        )
        return True
```

Replace the four request senders with:

```python
    def send_altitude_change_request(self, altitude, reason=None, on_done=None) -> bool:
        """Request an altitude change.

        Args:
            altitude: The requested altitude (e.g. "FL350")
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the request was queued
        """
        message = f"REQUEST {altitude}"
        if reason:
            message += f" DUE TO {reason}"
        return self._send_request(message, on_done, "Altitude change")

    def send_direct_request(self, fix, reason=None, on_done=None) -> bool:
        """Request direct to a waypoint.

        Args:
            fix: The waypoint/fix name
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the request was queued
        """
        message = f"REQUEST DIRECT TO {fix}"
        if reason:
            message += f" DUE TO {reason}"
        return self._send_request(message, on_done, "Direct request")

    def send_speed_request(self, speed, is_mach, reason=None, on_done=None) -> bool:
        """Request a speed change.

        Args:
            speed: The speed value (e.g. "082" for Mach, "300" for knots)
            is_mach: True for Mach, False for knots
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the request was queued
        """
        message = f"REQUEST M{speed}" if is_mach else f"REQUEST {speed}K"
        if reason:
            message += f" DUE TO {reason}"
        return self._send_request(message, on_done, "Speed request")

    def send_when_can_we_expect(self, message_text, on_done=None) -> bool:
        """Send a WHEN CAN WE EXPECT inquiry.

        Args:
            message_text: The full message text (e.g. "WHEN CAN WE EXPECT HIGHER LEVEL")
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the inquiry was queued
        """
        return self._send_request(message_text, on_done, "When-can-we-expect request")
```

Replace `send_acknowledgement` with:

```python
    def send_acknowledgement(self, sender, min_value, response, on_done=None) -> bool:
        """Queue an acknowledgement response to a CPDLC message.

        Args:
            sender: The message sender
            min_value: The message identification number being answered
            response: The response text (WILCO, UNABLE, etc.)
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the response was queued, False if not connected
        """
        if not self.connection_manager.is_connected():
            self.logger.error("Cannot send acknowledgement: not connected")
            return False

        if self.current_station and not self.is_answerable_sender(sender):
            self.logger.warning(
                f"Acknowledgement sender {sender} is not part of the dialogue "
                f"(current station {self.current_station})"
            )

        own_min = self._next_min()
        self.logger.info(
            f"Acknowledging message from {sender} (MIN: {min_value}) with response: {response}"
        )
        self._submit_send(
            response,
            lambda: self.connection_manager.send_cpdlc(
                sender, own_min, RR.NO.value, response, mrn=min_value
            ),
            on_done,
        )
        return True
```

Replace `send_telex` with:

```python
    def send_telex(self, recipient, message, on_done=None) -> bool:
        """Queue a TELEX message.

        Args:
            recipient: The message recipient
            message: The message text
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the telex was queued, False if not connected
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Telex attempted without active connection")
            return False

        self.logger.info(f"Sending telex to {recipient}")
        self.logger.debug(f"Telex content: {message}")
        self._submit_send(
            message, lambda: self.connection_manager.send_telex(recipient, message), on_done
        )
        return True
```

Replace `send_pdc_request`'s signature with `def send_pdc_request(self, origin_icao, destination_icao, aircraft_code, stand_designator, atis_code, on_done=None) -> bool:`, add `on_done: Callable(success, text_or_error), run on the GUI thread` to its docstring, change the Returns entry to `bool: True if the request was queued`, and replace its `try:` block and `return True, message` with:

```python
        self._submit_send(
            message, lambda: self.connection_manager.send_telex(origin_icao, message), on_done
        )
        return True
```

and its precondition `return False, None` with `return False`.

In `handle_handover`, add `on_done=None` to the signature, `on_done: Callable(success, text_or_error) for the REQUEST LOGON, run on the GUI thread` to its docstring, change the Returns entry to `bool: logon()'s answer, or False when old is not the current station`, the early `return False, None` to `return False`, and the final line to `return self.logon(new, on_done)`.

- [ ] **Step 4: Keep the window's handling inside the callbacks**

In `src/gui/main_window.py`:

Add `import functools` after `import os`; remove `RATE_LIMIT_RETRY_MS,` from the `src.config` import. In `__init__`, delete the `_pending_retry` assignment and its two comment lines. Delete `_retry_later` and `_cancel_pending_retry`, and the `self._cancel_pending_retry()` calls in `on_disconnect`, `_on_fatal_link_error` and `on_close`.

Replace `on_logon`, `on_logoff` and `_end_dialogue` with:

```python
    def on_logon(self, _):
        """Initiate logon to a CPDLC station."""
        if not self._require_connection("log on to a station"):
            return

        self.logger.debug("Opening logon dialog")
        dlg = LogonDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            station = dlg.get_logon_details()

            # Validate station name is exactly 4 characters
            if len(station) != 4:
                wx.MessageBox(
                    "Station name must be exactly 4 characters long.",
                    "Invalid Station Name",
                    wx.OK | wx.ICON_ERROR,
                )
                dlg.Destroy()
                return

            self.SetStatusText(f"Logging on to {station}...")
            queued = self.cpdlc_session.logon(
                station, functools.partial(self._on_logon_frame, station)
            )
            if not queued:
                wx.MessageBox(
                    f"Failed to send logon request to {station}.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def _on_logon_frame(self, station, success, text_or_error):
        """Report one frame of a manual logon: the LOGOFF that may precede it,
        or the REQUEST LOGON itself. Runs on the GUI thread.

        Args:
            station: The station being logged on to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            self._add_custom_message(text_or_error)
            self.polling_controller.set_active_polling()
            if text_or_error == "REQUEST LOGON":
                self.SetStatusText(f"Pending logon to {station}.")
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.SetStatusText(f"Could not log on to {station}.")
        wx.MessageBox(
            f"Failed to send logon request to {station}{error_detail}.",
            "Error",
            wx.OK | wx.ICON_ERROR,
        )

    def on_logoff(self, _):
        """Initiate logoff from current CPDLC station."""
        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You are not currently logged on to any station.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        # Confirm logoff
        station = self.cpdlc_session.get_current_station()
        if (
            wx.MessageBox(
                f"Are you sure you want to log off from {station}?",
                "Confirm Logoff",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            self.logger.debug("Logoff cancelled by user")
            return

        self.SetStatusText(f"Sending LOGOFF to {station}...")
        if not self.cpdlc_session.logoff(functools.partial(self._on_logoff_frame, station)):
            wx.MessageBox(
                f"Failed to send logoff message to {station}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _on_logoff_frame(self, station, success, text_or_error, quiet=False):
        """Report the outcome of a LOGOFF. Runs on the GUI thread.

        Args:
            station: The station the LOGOFF went to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
            quiet: True on disconnect and exit, where a failure gets a SYSTEM
                row rather than a dialog and the status bar is left alone
        """
        if success:
            self._add_custom_message(text_or_error)
            if not quiet:
                self.SetStatusText(f"Logged off from {station}.")
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.logger.warning(f"Could not send LOGOFF to {station}{error_detail}")
        if quiet:
            self._add_custom_message(
                f"Could not send LOGOFF to {station}{error_detail}", "SYSTEM"
            )
        else:
            self.SetStatusText(f"Could not send LOGOFF to {station}.")
            wx.MessageBox(
                f"Failed to send logoff message to {station}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _end_dialogue(self):
        """Queue the LOGOFF for the current station, if any, then forget the dialogue.

        The session is reset at once, whether or not the LOGOFF gets through:
        after a disconnect the app must not believe it is still logged on
        (audit M-1). A LOGOFF that could not be sent gets a SYSTEM row when
        its result comes back, so the pilot knows the station was not told.
        """
        if self.cpdlc_session.is_logged_on():
            station = self.cpdlc_session.get_current_station()
            self.cpdlc_session.logoff(
                functools.partial(self._on_logoff_frame, station, quiet=True)
            )

        self.cpdlc_session.reset()
```

Add after `_require_connection`:

```python
    def _send_callback(self, what):
        """Build the on_done for a downlink: echo it and speed up polling, or
        say why it failed.

        Args:
            what: The request as the failure dialog names it, e.g.
                "altitude change request"
        """

        def done(success, text_or_error):
            if success:
                self._add_custom_message(text_or_error)
                self.SetStatusText(f"Sent {text_or_error}.")
                self.polling_controller.set_active_polling()
                return

            error_detail = f": {text_or_error}" if text_or_error else ""
            self.SetStatusText(f"Could not send {what}.")
            wx.MessageBox(
                f"Failed to send {what}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

        return done
```

In each of `on_altitude_change`, `on_direct_request`, `on_speed_request`, `on_when_can_we_expect`, `on_telex` and `on_pdc_request`, replace the block from `success, message = self.cpdlc_session.send_...(` down to the end of its `else:` `wx.MessageBox(...)` with the queue-and-report shape, keeping each handler's dialog, getter and `what` text. For the altitude handler that is:

```python
            what = "altitude change request"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_altitude_change_request(
                altitude, reason, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)
```

with `what` being `"direct request"` (`send_direct_request(fix, reason, ...)`), `"speed request"` (`send_speed_request(speed, is_mach, reason, ...)`), `"request"` (`send_when_can_we_expect(message_text, ...)`), `f"telex message to {recipient}"` (`send_telex(recipient, message, ...)`) and `f"PDC request to {origin_icao}"` (`send_pdc_request(origin_icao, destination_icao, aircraft_code, stand_designator, atis_code, ...)`).

Replace `_on_acknowledge_message` with:

```python
    def _on_acknowledge_message(self, message_id: int, response: str):
        """Queue a response to an uplink.

        Args:
            message_id: The ID of the message being acknowledged
            response: The response text
        """
        addressing = self.message_manager.get_cpdlc_addressing(message_id)
        if addressing is None:
            self.logger.warning(f"Cannot acknowledge unknown message ID {message_id}")
            self.SetStatusText("Could not send response: message unavailable.")
            return

        sender, min_value = addressing
        self.SetStatusText(f"Sending {response}...")
        queued = self.cpdlc_session.send_acknowledgement(
            sender,
            min_value,
            response,
            functools.partial(self._on_acknowledgement_sent, message_id, response),
        )
        if not queued:
            wx.MessageBox(
                "Failed to send acknowledgement: not connected.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _on_acknowledgement_sent(self, message_id, response, success, text_or_error):
        """Retire and echo a response once it has gone out. Runs on the GUI thread.

        Args:
            message_id: The ID of the message that was answered
            response: The response text
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            # MessageManager decides whether this response retires the message;
            # STANDBY is sent but leaves it answerable.
            self.message_manager.mark_acknowledged(message_id, response)
            self._add_custom_message(text_or_error)
            self.SetStatusText(f"Sent {response}.")
            self.polling_controller.set_active_polling()
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.SetStatusText(f"Could not send {response}.")
        wx.MessageBox(
            f"Failed to send acknowledgement{error_detail}.",
            "Error",
            wx.OK | wx.ICON_ERROR,
        )
```

Replace `_follow_handover` with:

```python
    def _follow_handover(self, sender, new_station):
        """Log on to the station a HANDOVER names.

        Args:
            sender: The station handing over (the current station)
            new_station: The station to log on to
        """
        self.logger.info(f"Handover detected from {sender} to {new_station}")
        self.SetStatusText(f"Logged off from {sender}.")
        self._add_custom_message(f"Logging on to {new_station}", "SYSTEM")

        queued = self.cpdlc_session.handle_handover(
            sender, new_station, functools.partial(self._on_handover_logon, new_station)
        )
        if not queued:
            self.logger.error(f"Failed to send logon request to {new_station} during handover")
            self._add_custom_message(
                f"Failed to logon to {new_station} during handover", "SYSTEM"
            )

    def _on_handover_logon(self, new_station, success, text_or_error):
        """Report the REQUEST LOGON a handover sent. Runs on the GUI thread.

        Args:
            new_station: The station being logged on to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            self._add_custom_message(text_or_error)
            self.SetStatusText(f"Pending logon to {new_station}.")
            self.polling_controller.set_active_polling()
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.logger.error(
            f"Failed to send logon request to {new_station} during handover{error_detail}"
        )
        self._add_custom_message(
            f"Failed to logon to {new_station} during handover{error_detail}",
            "SYSTEM",
        )
```

In `src/config.py`, delete `RATE_LIMIT_RETRY_MS = 5000` and the three comment lines above it.

- [ ] **Step 5: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green. Report the count: this task adds tests in the downlink and acknowledgement modules and removes the four rate-limit tests and the fatal-retry test.

- [ ] **Step 6: Commit**

```bash
git add src/model/cpdlc_session.py src/gui/main_window.py src/config.py tests/support.py tests/test_downlink_requests.py tests/test_cpdlc_session.py tests/test_acknowledge_path.py tests/test_uplink_handling.py tests/test_session_lifecycle.py tests/test_logon_status.py tests/test_link_status.py tests/test_main_window_wiring.py
git commit -m "Queue every downlink on the network worker and report it through a callback"
```

---

### Task 5: Connect and disconnect in two phases

**Files:**
- Modify: `src/gui/main_window.py:329-361` (`on_connect` split into `_begin_connect` and `_on_connect_result`), `:363-408` (`on_disconnect` and new `_on_disconnected`), `_on_fatal_link_error` (bump the generation)
- Modify: `tests/support.py` (`FakeConnectionManager.connect_error`; `FakeMenuItem.Enable`/`IsEnabled`)
- Modify: `tests/test_session_lifecycle.py` (connect and disconnect tests)

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `new_generation`, `generation`, `PRIORITY_LINK` (Task 1); `_end_dialogue` (Task 4).
- Produces:
  - `MainWindow._begin_connect(callsign, logon_code, network_type)`: disables the Connect item, shows `"Connecting as X..."`, submits `("connect", ..., PRIORITY_LINK)`; `_on_connect_result(callsign, network_type, result)`: re-enables the item, then either today's post-connect code or `"Not connected."` plus the "Connection failed: <error>" dialog.
  - `on_disconnect`: after the confirmation, disables the item, shows `"Disconnecting..."`, runs `_end_dialogue()` (the LOGOFF is queued at priority 0), stops polling and weather, and submits `("disconnect", connection_manager.disconnect, self._on_disconnected, PRIORITY_LINK)`; `_on_disconnected(result)` bumps the worker generation and does today's UI work (`"&Connect"`, `"Disconnected from CPDLC network."`, the SYSTEM row).
  - `_on_fatal_link_error` calls `worker.new_generation()` after stopping polling.
  - `FakeConnectionManager(connected=True, raise_with=None, connect_error=None)`: `connect()` raises `connect_error` when set. `FakeMenuItem.enabled` (True), `Enable(enable=True)`, `IsEnabled()`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`: give `FakeConnectionManager.__init__` a third parameter `connect_error=None` stored as `self.connect_error`, documented as `connect_error: An exception connect() raises instead of connecting`, and make `connect()` start with `if self.connect_error is not None: raise self.connect_error`. Give `FakeMenuItem.__init__` `self.enabled = True` and the methods:

```python
    def Enable(self, enable=True):
        self.enabled = enable

    def IsEnabled(self):
        return self.enabled
```

In `tests/test_session_lifecycle.py`, replace `test_disconnect_logs_off_and_forgets_the_dialogue`, `test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails` and `test_connecting_hands_the_identity_to_the_session` with:

```python
def test_disconnect_logs_off_and_forgets_the_dialogue(logger):
    """The LOGOFF is queued ahead of the disconnect, so the connection is only
    closed once it has gone out; the menu item comes back with the result."""
    window, session, connection, manager = build(logger)

    window.on_disconnect()

    assert dialogue(session) == ("", None, "", 1)
    assert window.status_texts[-1] == "Disconnecting..."
    assert window.menu_item_connect.enabled is False
    assert connection.disconnected is False

    window.worker.run_pending()

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert connection.disconnected is True
    assert rows(manager) == [
        (CLIENT_CALLSIGN, "LOGOFF"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert window.status_texts[-1] == "Disconnected from CPDLC network."
    assert (window.menu_item_connect.enabled, window.menu_item_connect.label) == (True, "&Connect")
    assert window.worker.generation == 1


def test_disconnect_forgets_the_dialogue_even_when_the_logoff_fails(logger):
    """Audit M-1: a dead link is the usual reason to disconnect, and the
    failed LOGOFF used to leave the app believing it was still logged on."""
    connection = FakeConnectionManager(raise_with=HoppieError("timed out"))
    window, session, connection, manager = build(logger, connection)

    window.on_disconnect()
    window.worker.run_pending()

    assert dialogue(session) == ("", None, "", 1)
    assert rows(manager) == [
        ("SYSTEM", "Could not send LOGOFF to EDYY: timed out"),
        ("SYSTEM", "Disconnected from CPDLC network"),
    ]
    assert connection.disconnected is True


def test_connecting_hands_the_identity_to_the_session(logger, monkeypatch):
    """The connect runs on the worker; the menu item is disabled until it
    reports. A different callsign or network starts a clean dialogue; the
    session decides, the window only passes both on."""
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    window, session, connection, manager = build(logger)

    window.on_connect()

    assert window.status_texts[-1] == "Connecting as BAW123..."
    assert window.menu_item_connect.enabled is False
    assert connection.connected_as is None

    window.worker.run_pending()

    assert connection.connected_as == ("BAW123", "sayintentions")
    assert (session.get_callsign(), session.network) == ("BAW123", "sayintentions")
    assert session.is_logged_on() is False
    assert window.polling_controller.started is True
    assert window.menu_item_connect.enabled is True
    assert window.status_texts[-1] == "Connected as BAW123."
    assert rows(manager) == [("SYSTEM", "Connected as BAW123")]


def test_a_failed_connection_is_reported_and_the_menu_item_comes_back(logger, monkeypatch, message_boxes):
    monkeypatch.setattr(mw, "ConnectDialog", FakeConnectDialog)
    connection = FakeConnectionManager(connect_error=HoppieError("invalid logon code"))
    window, session, connection, _ = build(logger, connection)

    window.on_connect()
    window.worker.run_pending()

    assert message_boxes.captions == ["Error"]
    assert "invalid logon code" in message_boxes.calls[0][0]
    assert window.menu_item_connect.enabled is True
    assert window.status_texts[-1] == "Not connected."
    assert window.polling_controller.started is False
```

In `test_a_rejected_logon_code_forgets_the_dialogue`, add `assert window.worker.generation == 1` as a last line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_session_lifecycle.py`
Expected: FAIL. `on_connect` connects synchronously (`connection.connected_as is None` fails, `enabled is False` fails); the disconnect tests fail on `"Disconnecting..."` and on the generation.

- [ ] **Step 3: Split connect and disconnect**

In `src/gui/main_window.py`, add `from src.model.network_worker import NetworkWorker, PRIORITY_LINK` in place of the Task 2 import, and replace `on_connect` and `on_disconnect` with:

```python
    def on_connect(self):
        """Ask for the connection details and connect on the worker."""
        self.logger.debug("Opening connection dialog")
        dlg = ConnectDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            callsign, logon_code, network_type = dlg.get_connection_details()
            self._begin_connect(callsign, logon_code, network_type)

        dlg.Destroy()

    def _begin_connect(self, callsign, logon_code, network_type):
        """Submit the connection attempt; the menu item stays disabled until it reports.

        Args:
            callsign: Aircraft callsign
            logon_code: CPDLC logon code
            network_type: "sayintentions" or "hoppie"
        """
        self.menu_item_connect.Enable(False)
        self.SetStatusText(f"Connecting as {callsign}...")
        self.worker.submit(
            "connect",
            lambda: self.connection_manager.connect(callsign, logon_code, network_type),
            functools.partial(self._on_connect_result, callsign, network_type),
            PRIORITY_LINK,
        )

    def _on_connect_result(self, callsign, network_type, result):
        """Finish a connection attempt. Runs on the GUI thread.

        Args:
            callsign: The callsign the attempt was made with
            network_type: The network it was made on
            result: The worker's JobResult
        """
        self.menu_item_connect.Enable(True)
        if not result.ok:
            self.SetStatusText("Not connected.")
            wx.MessageBox(
                f"Connection failed: {result.error}",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
            return

        # Start polling and automatic weather updates
        self.polling_controller.start(self)
        self.weather_monitor.start(self)

        # Hand the identity to the session; a different callsign or
        # network starts a clean dialogue, the same one keeps the logon
        self.cpdlc_session.begin_session(callsign, network_type)

        # Update UI
        self.SetStatusText(f"Connected as {callsign}.")
        self.menu_item_connect.SetItemLabel("&Disconnect")
        self.menu_item_connect.SetHelp("Disconnect from the CPDLC network")

        # Add system message
        self._add_custom_message(f"Connected as {callsign}", "SYSTEM")

    def on_disconnect(self):
        """Disconnect from the CPDLC network."""
        if not self.connection_manager.is_connected():
            return

        # Check if logged on to a station
        if self.cpdlc_session.is_logged_on():
            # Confirm disconnect with warning about active logon
            confirm_message = f"You are currently logged on to {self.cpdlc_session.get_current_station()}. If you disconnect, you will be logged off from this station.\n\nAre you sure you want to disconnect from the CPDLC network?"
        else:
            # Standard confirmation
            confirm_message = (
                "Are you sure you want to disconnect from the CPDLC network?"
            )

        # Confirm disconnect
        if (
            wx.MessageBox(
                confirm_message,
                "Confirm Disconnect",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            self.logger.debug("Disconnect cancelled by user")
            return

        self.logger.info("Disconnecting from CPDLC network")
        self.menu_item_connect.Enable(False)
        self.SetStatusText("Disconnecting...")
        self._end_dialogue()

        # Stop polling and automatic weather updates
        self.polling_controller.stop()
        self.weather_monitor.stop()
        self.weather_monitor.clear()

        # The LOGOFF queued by _end_dialogue runs at a higher priority than
        # this, so the connection is only closed once it has gone out.
        self.worker.submit(
            "disconnect", self.connection_manager.disconnect, self._on_disconnected, PRIORITY_LINK
        )

    def _on_disconnected(self, result):
        """Finish a disconnect once the LOGOFF has had its turn. Runs on the GUI thread.

        Args:
            result: The worker's JobResult (disconnect() cannot fail)
        """
        # Anything still queued belonged to the old session.
        self.worker.new_generation()

        # Update UI
        self.menu_item_connect.Enable(True)
        self.menu_item_connect.SetItemLabel("&Connect")
        self.menu_item_connect.SetHelp("Connect to the CPDLC network")
        self.SetStatusText("Disconnected from CPDLC network.")

        # Add system message
        self._add_custom_message("Disconnected from CPDLC network", "SYSTEM")
```

In `_on_fatal_link_error`, add `self.worker.new_generation()` right after `self.polling_controller.stop()`, with the comment `# Nothing queued for this session may run or report now.`

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, one more than after Task 4.

- [ ] **Step 5: Commit**

```bash
git add src/gui/main_window.py tests/support.py tests/test_session_lifecycle.py
git commit -m "Connect and disconnect on the network worker, with the menu item disabled in between"
```

---

### Task 6: SimBrief fills the dialogs in after they open

**Files:**
- Modify: `src/gui/dialogs/connect_dialog.py` (constructor takes `fetch_simbrief`; status label; `_on_simbrief`; `Destroy` override; drop the `get_latest_ofp` import)
- Modify: `src/gui/dialogs/pdc_dialog.py` (same shape; drop the `load_config` and `get_latest_ofp` imports)
- Modify: `src/gui/main_window.py` (import `get_latest_ofp` and `PRIORITY_INFO`; new `_fetch_simbrief`; `on_connect` and `on_pdc_request` pass it)
- Modify: `tests/conftest.py:63-81` (`no_simbrief` patches the window module), `tests/test_harness.py:55-65` (the SimBrief guarantee, now through the window), `tests/test_dialogs.py` (dialog tests)
- Modify: `tests/support.py` (`make_main_window` needs nothing new; `_fetch_simbrief` reads the isolated config)

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `PRIORITY_INFO` (Task 1); `get_latest_ofp(user_id)` from `src.utils.simbrief` (returns the OFP dict or None).
- Produces:
  - `ConnectDialog(parent, fetch_simbrief=None)` and `PDCDialog(parent, fetch_simbrief=None)`: `fetch_simbrief(on_done) -> bool` is called from the constructor; when it returns True the dialog's `simbrief_status` label reads `"Fetching SimBrief flight plan..."`; `on_done(ofp_or_None)` fills the fields if the dialog is still alive (`_alive`, cleared by `Destroy`), then the label reads `"Callsign taken from your SimBrief flight plan."` / `"Flight plan loaded from SimBrief."` or `"Could not fetch flight plan from SimBrief."`. No message boxes.
  - `MainWindow._fetch_simbrief(on_done) -> bool`: False when no `simbrief_userid` is configured; otherwise submits `("simbrief", lambda: get_latest_ofp(user_id), ..., PRIORITY_INFO)` and calls `on_done(result.value if result.ok else None)`.
  - The autouse `no_simbrief` fixture patches `src.gui.main_window.get_latest_ofp`.

- [ ] **Step 1: Write the failing tests**

In `tests/conftest.py`, replace the `no_simbrief` fixture with:

```python
@pytest.fixture(autouse=True)
def no_simbrief(monkeypatch):
    """Answer every SimBrief lookup with "no flight plan", recording the ids asked for.

    MainWindow imports get_latest_ofp by name and runs it on the worker, so
    the patch lands on the window module rather than on src.utils.simbrief.

    Returns:
        list: The SimBrief user ids the window asked for.
    """
    asked = []

    def fake(user_id):
        asked.append(user_id)
        return None

    monkeypatch.setattr("src.gui.main_window.get_latest_ofp", fake)
    return asked
```

In `tests/test_harness.py`, add `from src.model.cpdlc_session import CpdlcSession`, `from src.model.message_manager import MessageManager` and `from tests.support import FakeConnectionManager, inline_worker, make_main_window` to the imports, drop the `ConnectDialog` import if nothing else uses it, and replace `test_the_connect_dialog_never_reaches_simbrief` with:

```python
def test_the_simbrief_fetch_never_leaves_the_test(logger, no_simbrief):
    """With a SimBrief id configured the window fetches the flight plan on the
    worker; the lookup must land on the fake, and the dialog must be told."""
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    window = make_main_window(
        logger, session, MessageManager(logger), config={"simbrief_userid": "189007"}
    )
    answers = []

    assert window._fetch_simbrief(answers.append) is True
    window.worker.run_pending()

    assert no_simbrief == ["189007"]
    assert answers == [None]


def test_without_a_simbrief_id_nothing_is_fetched(logger, no_simbrief):
    session = CpdlcSession(logger, FakeConnectionManager(), worker=inline_worker(logger))
    window = make_main_window(logger, session, MessageManager(logger))

    assert window._fetch_simbrief(lambda ofp: None) is False
    assert window.worker.pending() == 0
    assert no_simbrief == []
```

In `tests/test_dialogs.py`, extend the imports to `from src.gui.dialogs import ConnectDialog, PDCDialog, WeatherDialog` and append:

```python
# --- SimBrief fills the Connect and PDC dialogs in after they open -------------


class RecordingFetch:
    """Stands in for MainWindow._fetch_simbrief: keeps the callback so the test can answer later."""

    def __init__(self, configured=True):
        self.configured = configured
        self.on_done = None

    def __call__(self, on_done):
        if not self.configured:
            return False
        self.on_done = on_done
        return True


def test_the_connect_dialog_opens_before_simbrief_answers(frame):
    """The fetch used to run inside the constructor, freezing the app for up
    to ten seconds before the dialog appeared."""
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    try:
        assert dialog.simbrief_status.GetLabel() == "Fetching SimBrief flight plan..."
        assert dialog.callsign_text.GetValue() == ""

        fetch.on_done({"atc": {"callsign": "BAW123"}})

        assert dialog.callsign_text.GetValue() == "BAW123"
        assert dialog.simbrief_status.GetLabel() == "Callsign taken from your SimBrief flight plan."
    finally:
        dialog.Destroy()


def test_a_failed_simbrief_fetch_is_shown_in_the_dialog_not_a_message_box(frame, message_boxes):
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    try:
        fetch.on_done(None)

        assert dialog.simbrief_status.GetLabel() == "Could not fetch flight plan from SimBrief."
        assert message_boxes.calls == []
    finally:
        dialog.Destroy()


def test_a_simbrief_answer_after_the_dialog_closed_is_ignored(frame):
    """The pilot may press OK or Cancel before SimBrief answers."""
    fetch = RecordingFetch()
    dialog = ConnectDialog(frame, fetch_simbrief=fetch)
    dialog.Destroy()

    fetch.on_done({"atc": {"callsign": "BAW123"}})


def test_without_a_simbrief_id_the_connect_dialog_says_nothing(frame):
    dialog = ConnectDialog(frame, fetch_simbrief=RecordingFetch(configured=False))
    try:
        assert dialog.simbrief_status.GetLabel() == ""
    finally:
        dialog.Destroy()


def test_the_pdc_dialog_fills_its_fields_from_simbrief(frame):
    fetch = RecordingFetch()
    dialog = PDCDialog(frame, fetch_simbrief=fetch)
    try:
        assert dialog.simbrief_status.GetLabel() == "Fetching SimBrief flight plan..."

        fetch.on_done(
            {
                "origin": {"icao_code": "EGLL"},
                "destination": {"icao_code": "LIMC"},
                "aircraft": {"icao_code": "A339"},
            }
        )

        assert (
            dialog.origin_icao_text.GetValue(),
            dialog.destination_icao_text.GetValue(),
            dialog.aircraft_text.GetValue(),
        ) == ("EGLL", "LIMC", "A339")
        assert dialog.simbrief_status.GetLabel() == "Flight plan loaded from SimBrief."
    finally:
        dialog.Destroy()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialogs.py tests/test_harness.py`
Expected: FAIL with `TypeError: ConnectDialog.__init__() got an unexpected keyword argument 'fetch_simbrief'`, `AttributeError: ... has no attribute '_fetch_simbrief'`, and the `no_simbrief` fixture failing to patch `src.gui.main_window.get_latest_ofp` (`AttributeError`).

- [ ] **Step 3: Move the fetch out of the constructors**

In `src/gui/dialogs/connect_dialog.py`:

- Remove `from src.utils.simbrief import get_latest_ofp`.
- Change the constructor signature to `def __init__(self, parent, fetch_simbrief=None):` and its docstring to:

```python
        """
        Initialize the connect dialog.

        Args:
            parent: The parent window
            fetch_simbrief: Callable(on_done) that fetches the latest SimBrief
                flight plan off the GUI thread and calls on_done(ofp_or_None)
                on it; returns False when no SimBrief id is configured. None
                skips the fetch. The dialog opens at once either way and fills
                the callsign in when the plan arrives.
        """
```

- After `self.logger = ...` add `self._alive = True`. Remove the `simbrief_userid = config.get(...)` line.
- Replace the whole `# Try to populate callsign from SimBrief ...` block (from that comment through the `except Exception as e:` handler's `wx.MessageBox(...)`) with nothing; then, right after `vbox.Add(self.callsign_text, 0, wx.ALL | wx.EXPAND, 5)`, add:

```python
        # The flight plan arrives after the dialog is open; this line says
        # where it stands so a screen-reader user is not left guessing.
        self.simbrief_status = wx.StaticText(self, label="")
        vbox.Add(self.simbrief_status, 0, wx.ALL, 5)
```

- At the very end of `__init__` (after `self.on_text_change(None)`), add:

```python
        if fetch_simbrief is not None and fetch_simbrief(self._on_simbrief):
            self.simbrief_status.SetLabel("Fetching SimBrief flight plan...")
```

- Add the methods:

```python
    def _on_simbrief(self, ofp_data):
        """Fill the callsign in from the flight plan, if the dialog is still open.

        Args:
            ofp_data: The SimBrief OFP dict, or None when the fetch failed
        """
        if not self._alive:
            return

        # The callsign is airline code plus flight number, e.g. "WAT2088".
        atc = (ofp_data or {}).get("atc") or {}
        callsign = atc.get("callsign", "")
        if callsign:
            self.logger.info(f"Found callsign in SimBrief OFP: {callsign}")
            self.callsign_text.SetValue(callsign)
            self.simbrief_status.SetLabel("Callsign taken from your SimBrief flight plan.")
        else:
            self.logger.warning("Could not fetch flight plan from SimBrief")
            self.simbrief_status.SetLabel("Could not fetch flight plan from SimBrief.")

        self.on_text_change(None)
        self.Layout()
        self.Fit()

    def Destroy(self):
        """Forget the dialog before wx does, so a late SimBrief answer is ignored."""
        self._alive = False
        return super().Destroy()
```

In `src/gui/dialogs/pdc_dialog.py`: remove the `load_config` and `get_latest_ofp` imports (and the `config = load_config()` / `simbrief_userid` lines); the constructor takes `fetch_simbrief=None` with the same docstring; `self._alive = True`; delete the `# Try to populate fields from SimBrief` block; add the `simbrief_status` label right after `vbox.Add(self.aircraft_text, ...)`; at the end of `__init__` the same `if fetch_simbrief is not None and fetch_simbrief(self._on_simbrief):` line; and the methods:

```python
    def _on_simbrief(self, ofp_data):
        """Fill the airports and aircraft in from the flight plan, if the dialog is still open.

        Args:
            ofp_data: The SimBrief OFP dict, or None when the fetch failed
        """
        if not self._alive:
            return

        if not ofp_data:
            self.logger.warning("Could not fetch flight plan from SimBrief")
            self.simbrief_status.SetLabel("Could not fetch flight plan from SimBrief.")
            return

        for field, key in (
            (self.origin_icao_text, "origin"),
            (self.destination_icao_text, "destination"),
            (self.aircraft_text, "aircraft"),
        ):
            value = (ofp_data.get(key) or {}).get("icao_code", "")
            if value:
                self.logger.info(f"Found {key} ICAO in SimBrief OFP: {value}")
                field.SetValue(value)
            else:
                self.logger.warning(f"Could not extract {key} ICAO from SimBrief OFP")

        self.simbrief_status.SetLabel("Flight plan loaded from SimBrief.")
        self.on_text_change(None)
        self.Layout()
        self.Fit()

    def Destroy(self):
        """Forget the dialog before wx does, so a late SimBrief answer is ignored."""
        self._alive = False
        return super().Destroy()
```

In `src/gui/main_window.py`:

- Add `from src.utils.simbrief import get_latest_ofp` after the `update_checker` import, and extend the network worker import to `from src.model.network_worker import NetworkWorker, PRIORITY_INFO, PRIORITY_LINK`.
- In `on_connect`, build the dialog as `ConnectDialog(self, fetch_simbrief=self._fetch_simbrief)`; in `on_pdc_request`, `PDCDialog(self, fetch_simbrief=self._fetch_simbrief)`.
- Add after `_require_connection`:

```python
    def _fetch_simbrief(self, on_done):
        """Fetch the latest SimBrief flight plan on the worker.

        Args:
            on_done: Callable(ofp_or_None), run on the GUI thread

        Returns:
            bool: True if a fetch was started, False when no SimBrief user id
                is configured
        """
        user_id = load_config().get("simbrief_userid", "")
        if not user_id:
            return False

        self.logger.debug(f"Fetching SimBrief OFP for user ID: {user_id}")
        self.worker.submit(
            "simbrief",
            lambda: get_latest_ofp(user_id),
            lambda result: on_done(result.value if result.ok else None),
            PRIORITY_INFO,
        )
        return True
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, six more than after Task 5.

- [ ] **Step 5: Commit**

```bash
git add src/gui/dialogs/connect_dialog.py src/gui/dialogs/pdc_dialog.py src/gui/main_window.py tests/conftest.py tests/test_harness.py tests/test_dialogs.py
git commit -m "Open the Connect and PDC dialogs at once and fill them from SimBrief when it answers"
```

---

### Task 7: Count open dialogs, and let the update prompt wait its turn

**Files:**
- Modify: `src/utils/update_checker.py` (rewrite: `UpdateOutcome`, `UpdateChecker(logger, worker).check(on_done)`, no dialogs)
- Modify: `src/gui/main_window.py` (imports `contextmanager`, `webbrowser`, `APP_VERSION`; `__init__`: the modal counter, `pending_update`, the worker created first, the from-source rule, the first-launch prompt moved to the end; `_show_dialog`, `_message_box`, `_flush_deferred`, `_open_release_page`, `_on_auto_update_check`, `_on_manual_update_check`, `on_check_updates`; every `ShowModal`/`Destroy` pair and every `wx.MessageBox` call converted)
- Modify: `tests/support.py` (`make_main_window` sets `_modal_depth = 0`, `pending_update = None`)
- Modify: `tests/test_main_window.py` (`build_window` takes config overrides; the ShowModal counter test; the from-source test)
- Create: `tests/test_update_checker.py`

**Interfaces:**
- Consumes: `NetworkWorker.submit`, `PRIORITY_INFO` (Task 1); `make_main_window`.
- Produces:
  - `UpdateOutcome(latest=None, url=None, newer=False, error=None)`; `UpdateChecker(logger=None, worker=None).check(on_done)` with `on_done(UpdateOutcome)` on the GUI thread; `_get_latest_version()` runs on the worker and raises on failure (the worker captures it).
  - `MainWindow._modal_depth` (int), `pending_update` (an `UpdateOutcome` or None); `_show_dialog(dlg)` context manager yielding `dlg.ShowModal()`'s answer and destroying the dialog; `_message_box(message, caption, style=wx.OK)`; `_flush_deferred()`; `_on_auto_update_check(outcome)`, `_on_manual_update_check(outcome)`, `_open_release_page(url)`. The automatic check runs only when `auto_check_updates` is on and `getattr(sys, "frozen", False)` is true.
  - `build_window(**config_overrides)` in `tests/test_main_window.py`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, in `make_main_window` after `window._callsign_clash_announced = False`, add:

```python
    window._modal_depth = 0
    window.pending_update = None
```

Create `tests/test_update_checker.py`:

```python
"""The update check: the checker reports an outcome off the GUI thread, and
the window's prompt waits for open dialogs and never closes the app (audit M-5)."""

import webbrowser

import requests
import wx

from src.config import APP_VERSION
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from src.utils.update_checker import UpdateChecker, UpdateOutcome
from tests.support import FakeClock, FakeConnectionManager, inline_worker, make_main_window


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def check(logger, monkeypatch, payload=None, error=None):
    """Run one check against a faked GitHub and return its outcome."""

    def get(url, timeout=None):
        if error is not None:
            raise error
        return FakeResponse(payload)

    monkeypatch.setattr(requests, "get", get)
    worker = inline_worker(logger)
    outcomes = []
    UpdateChecker(logger, worker).check(outcomes.append)
    assert outcomes == [], "the lookup must not run on the calling thread"
    worker.run_pending()
    return outcomes[0]


# --- the checker --------------------------------------------------------------


def test_a_newer_release_is_reported(logger, monkeypatch):
    outcome = check(
        logger, monkeypatch, {"tag_name": "v99.0.0", "html_url": "https://example.invalid/release"}
    )

    assert (outcome.latest, outcome.url, outcome.newer, outcome.error) == (
        "99.0.0",
        "https://example.invalid/release",
        True,
        None,
    )


def test_the_running_version_is_not_newer_than_itself(logger, monkeypatch):
    outcome = check(logger, monkeypatch, {"tag_name": f"v{APP_VERSION}", "html_url": "u"})

    assert (outcome.latest, outcome.newer) == (APP_VERSION, False)


def test_a_failed_lookup_is_reported_not_raised(logger, monkeypatch):
    outcome = check(logger, monkeypatch, error=requests.ConnectionError("offline"))

    assert (outcome.latest, outcome.newer) == (None, False)
    assert "offline" in outcome.error


# --- the window's prompt ------------------------------------------------------


def build(logger):
    session = CpdlcSession(
        logger, FakeConnectionManager(), clock=FakeClock(), worker=inline_worker(logger)
    )
    return make_main_window(logger, session, MessageManager(logger))


NEWER = UpdateOutcome(latest="99.0.0", url="https://example.invalid/release", newer=True)


def test_the_update_prompt_waits_for_an_open_dialog(logger, message_boxes):
    """It used to pop over whatever was open and could close the app from
    under it; now it waits until no dialog is open."""
    window = build(logger)
    window._modal_depth = 1

    window._on_auto_update_check(NEWER)

    assert message_boxes.calls == []
    assert window.pending_update is NEWER

    window._modal_depth = 0
    window._flush_deferred()

    assert message_boxes.captions == ["Update Available"]
    assert "Open the release page in your browser?" in message_boxes.calls[0][0]
    assert window.pending_update is None


def test_saying_yes_opens_the_release_page_and_nothing_else(logger, message_boxes, monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    window = build(logger)
    message_boxes.answer = wx.YES

    window._on_manual_update_check(NEWER)

    assert opened == ["https://example.invalid/release"]
    assert message_boxes.captions == ["Update Available"]


def test_a_manual_check_reports_when_there_is_nothing_new(logger, message_boxes):
    window = build(logger)

    window._on_manual_update_check(UpdateOutcome(latest=APP_VERSION, url="u", newer=False))

    assert message_boxes.captions == ["No Updates Available"]


def test_a_manual_check_reports_a_failed_lookup(logger, message_boxes):
    window = build(logger)

    window._on_manual_update_check(UpdateOutcome(error="offline"))

    assert message_boxes.captions == ["Update Check Failed"]


def test_an_automatic_check_stays_silent_when_there_is_nothing_new(logger, message_boxes):
    window = build(logger)

    window._on_auto_update_check(UpdateOutcome(latest=APP_VERSION, newer=False))

    assert message_boxes.calls == []


def test_a_message_box_counts_as_an_open_dialog_while_it_shows(logger, monkeypatch):
    window = build(logger)
    depths = []

    def recording(message, caption="Message", style=wx.OK, *args, **kwargs):
        depths.append(window._modal_depth)
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", recording)

    window._message_box("Hello", "Test")

    assert depths == [1]
    assert window._modal_depth == 0
```

In `tests/test_main_window.py`:

- Change the `build_window` fixture's inner function to `def build(**overrides):` and its `save_config` line to `assert save_config({**DEFAULT_CONFIG, "auto_check_updates": False, **overrides})`.
- Add `import sys` to the imports and `from tests.support import FakeConnectionManager, FakeSimConnectManager`.
- Append:

```python
# --- open dialogs are counted --------------------------------------------------


def test_every_dialog_is_counted_while_it_is_open(window, monkeypatch):
    """The update prompt waits for _modal_depth to reach zero, so every dialog
    the window opens must be counted while ShowModal runs; a handler that
    bypassed _show_dialog would let the prompt pop over its dialog (audit M-5)."""
    depths = []

    def counted_show_modal(dialog):
        depths.append(window._modal_depth)
        return wx.ID_CANCEL

    # Every dialog class is a Python subclass of wx.Dialog, so one patch
    # covers them all.
    monkeypatch.setattr(wx.Dialog, "ShowModal", counted_show_modal)
    window.connection_manager = FakeConnectionManager()
    window.cpdlc_session.connection_manager = window.connection_manager
    window.cpdlc_session.handle_logon_accepted("EDYY")
    window.weather_monitor.subscribe("EGLL", "metar")

    window.on_connect()
    for handler in (
        window.on_settings,
        window.on_pdc_request,
        window.on_logon,
        window.on_altitude_change,
        window.on_direct_request,
        window.on_speed_request,
        window.on_when_can_we_expect,
        window.on_telex,
        window.on_weather_request,
        window.on_weather_subscriptions,
    ):
        handler(None)

    assert len(depths) == 11
    assert all(depth >= 1 for depth in depths)
    assert window._modal_depth == 0


# --- the automatic update check ------------------------------------------------


def test_the_automatic_update_check_is_skipped_when_running_from_source(build_window, monkeypatch):
    """A developer running from a checkout is not a user to tell about
    releases, and the check would hit GitHub on every start."""
    checks = []
    monkeypatch.setattr(mw.UpdateChecker, "check", lambda self, on_done: checks.append(on_done))
    monkeypatch.delattr(sys, "frozen", raising=False)

    build_window(auto_check_updates=True)

    assert checks == []


def test_the_automatic_update_check_runs_in_a_packaged_build(build_window, monkeypatch):
    checks = []
    monkeypatch.setattr(mw.UpdateChecker, "check", lambda self, on_done: checks.append(on_done))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    window = build_window(auto_check_updates=True)

    assert checks == [window._on_auto_update_check]
```

If wx refuses `monkeypatch.setattr(wx.Dialog, "ShowModal", ...)` (an `AttributeError` or `TypeError` from the sip type), patch each dialog class instead: `for cls in (ConnectDialog, SettingsDialog, PDCDialog, LogonDialog, AltitudeChangeDialog, DirectRequestDialog, SpeedRequestDialog, WhenCanWeDialog, TelexDialog, WeatherDialog, WeatherSubscriptionsDialog): monkeypatch.setattr(cls, "ShowModal", counted_show_modal)`, importing them from `src.gui.dialogs`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_update_checker.py tests/test_main_window.py`
Expected: FAIL with `ImportError: cannot import name 'UpdateOutcome'`, `AttributeError: 'MainWindow' object has no attribute '_flush_deferred'`, and the counter test failing on `len(depths) == 11` (depths are all 0 because nothing counts yet).

- [ ] **Step 3: Rewrite the update checker**

Replace `src/utils/update_checker.py` in full with:

```python
"""Update checker for the Sim-CPDLC application.

The lookup runs on the network worker and reports an outcome; the window owns
every prompt, so an "update available" message waits for any open dialog and
never closes the application from under one (audit M-5).
"""

import functools
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from packaging import version

from src.config import APP_VERSION, GITHUB_URL
from src.model.network_worker import PRIORITY_INFO


@dataclass
class UpdateOutcome:
    """What a check found.

    Attributes:
        latest: The latest released version, or None when it could not be read
        url: The release page, or None
        newer: True when latest is newer than the running version
        error: The failure text when the lookup failed, else None
    """

    latest: Optional[str] = None
    url: Optional[str] = None
    newer: bool = False
    error: Optional[str] = None


class UpdateChecker:
    """Looks up the latest release on GitHub, off the GUI thread."""

    def __init__(self, logger=None, worker=None):
        """Initialize the update checker.

        Args:
            logger: Optional logger instance
            worker: The NetworkWorker that runs the lookup
        """
        self.logger = logger or logging.getLogger("Sim-CPDLC")
        self.worker = worker
        self.current_version = APP_VERSION

    def check(self, on_done):
        """Fetch the latest release and report it.

        Args:
            on_done: Callable(UpdateOutcome), run on the GUI thread
        """
        self.worker.submit(
            "update", self._get_latest_version, functools.partial(self._report, on_done), PRIORITY_INFO
        )

    def _report(self, on_done, result):
        """Turn the worker's result into an outcome. Runs on the GUI thread."""
        if not result.ok:
            self.logger.error(f"Error checking for updates: {result.error}")
            on_done(UpdateOutcome(error=result.error))
            return

        latest, url = result.value
        on_done(UpdateOutcome(latest=latest, url=url, newer=self._is_newer_version(latest)))

    def _get_latest_version(self):
        """Read the latest release tag from GitHub. Runs on the worker.

        Returns:
            tuple: (version_string, release_url)

        Raises:
            Whatever requests raises; the worker turns it into a failed result.
        """
        # GITHUB_URL is https://github.com/<user>/<repo>
        parts = GITHUB_URL.strip("/").split("/")
        api_url = f"https://api.github.com/repos/{parts[-2]}/{parts[-1]}/releases/latest"
        self.logger.debug(f"Checking for updates at: {api_url}")

        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v"), data.get("html_url", "")

    def _is_newer_version(self, latest_version):
        """Check if latest_version is newer than the running version."""
        if not latest_version:
            return False
        try:
            return version.parse(latest_version) > version.parse(self.current_version)
        except Exception as exc:
            self.logger.error(f"Error comparing versions: {exc}")
            return False
```

- [ ] **Step 4: Count the dialogs and own the prompt**

In `src/gui/main_window.py`:

Imports: add `import webbrowser` after `import sys`, `from contextlib import contextmanager` after the standard imports, and `APP_VERSION,` to the `src.config` import list.

`__init__`: right after `self.logger.debug("Initializing MainWindow")`, add:

```python
        # How many modal dialogs are open. A prompt that arrives from the
        # background (the update check) waits until this is zero, so it can
        # never pop over, or close the app from under, a dialog in use.
        self._modal_depth = 0
        self.pending_update = None
```

Move the `self.worker = NetworkWorker(logger)` block (Task 2) to just after `self.simconnect_manager = SimConnectManager()`. Delete the `self._check_first_launch()` call and its comment from their current place. Replace the update-checker block (from `# Initialize update checker` through the `else:` branch's debug line) with:

```python
        # Initialize update checker
        self.update_checker = UpdateChecker(logger, self.worker)

        # Check for updates if enabled in settings. A run from source is a
        # developer's checkout, not an installation to be told about releases.
        config = load_config()
        if not config.get("auto_check_updates", True):
            self.logger.debug("Auto-update check disabled")
        elif not getattr(sys, "frozen", False):
            self.logger.debug("Running from source; skipping the automatic update check")
        else:
            self.logger.debug("Auto-update check enabled, checking for updates")
            self.update_checker.check(self._on_auto_update_check)
```

Replace the sound-file `wx.MessageBox(error_msg, "Missing Sound File", wx.OK | wx.ICON_WARNING)` with `self._message_box(error_msg, "Missing Sound File", wx.OK | wx.ICON_WARNING)`. Just before `self.Show(True)`, add:

```python
        # The welcome prompt runs once the window is complete: its handlers
        # are bound and the controllers exist (audit L-15).
        self._check_first_launch()
```

Replace `on_check_updates` with:

```python
    def on_check_updates(self, _):
        """Manually check for updates."""
        self.logger.debug("Manually checking for updates")
        self.SetStatusText("Checking for updates...")
        self.update_checker.check(self._on_manual_update_check)
```

Add after `_require_connection`:

```python
    @contextmanager
    def _show_dialog(self, dlg):
        """Show a dialog modally, count it as open, and destroy it afterwards.

        Args:
            dlg: The dialog to show

        Yields:
            The ShowModal() return code
        """
        self._modal_depth += 1
        try:
            yield dlg.ShowModal()
        finally:
            self._modal_depth -= 1
            dlg.Destroy()
            self._flush_deferred()

    def _message_box(self, message, caption, style=wx.OK):
        """wx.MessageBox parented to this window and counted as an open dialog."""
        self._modal_depth += 1
        try:
            return wx.MessageBox(message, caption, style, parent=self)
        finally:
            self._modal_depth -= 1
            self._flush_deferred()

    def _flush_deferred(self):
        """Show what waited for the dialogs to close: the update prompt, if any."""
        if self._modal_depth or self.pending_update is None:
            return

        outcome, self.pending_update = self.pending_update, None
        answer = self._message_box(
            "A new version of Sim-CPDLC is available!\n\n"
            f"Current version: {APP_VERSION}\n"
            f"Latest version: {outcome.latest}\n\n"
            "Open the release page in your browser?",
            "Update Available",
            wx.YES_NO | wx.ICON_INFORMATION,
        )
        if answer == wx.YES:
            self._open_release_page(outcome.url)

    def _open_release_page(self, url):
        """Open the release page in the browser; the app stays open either way."""
        self.logger.info(f"Opening the release page: {url}")
        try:
            webbrowser.open(url)
        except Exception as exc:
            self.logger.error(f"Error opening browser: {exc}")
            self._message_box(
                f"Error opening browser: {exc}\n\n"
                f"Please visit {url} manually to download the update.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _on_auto_update_check(self, outcome):
        """Queue the prompt for a newer release; say nothing otherwise."""
        if outcome.newer:
            self.pending_update = outcome
            self._flush_deferred()

    def _on_manual_update_check(self, outcome):
        """Report the outcome of a check the pilot asked for."""
        if outcome.newer:
            self.pending_update = outcome
            self._flush_deferred()
        elif outcome.latest:
            self._message_box(
                f"You are running the latest version ({APP_VERSION}).",
                "No Updates Available",
                wx.OK | wx.ICON_INFORMATION,
            )
        else:
            self._message_box(
                "Could not retrieve version information from GitHub.",
                "Update Check Failed",
                wx.OK | wx.ICON_ERROR,
            )
```

Convert every dialog handler to the context manager. The shape, shown for `on_logon`:

```python
        dlg = LogonDialog(self)
        with self._show_dialog(dlg) as answer:
            if answer != wx.ID_OK:
                return
            station = dlg.get_logon_details()
            ... (the body as it is, without the trailing dlg.Destroy() calls)
```

Apply it to `on_settings` (`SettingsDialog`), `on_connect` (`ConnectDialog`), `on_logon` (delete the inner `dlg.Destroy(); return` pair in favour of a bare `return`), `on_altitude_change`, `on_direct_request`, `on_speed_request`, `on_when_can_we_expect`, `on_telex`, `on_weather_request`, `on_weather_subscriptions` (`with self._show_dialog(WeatherSubscriptionsDialog(self, self.weather_monitor)): pass`), `on_pdc_request`, and `_check_first_launch` (`dlg = wx.MessageDialog(...)`, `with self._show_dialog(dlg) as result:`). Every `dlg.Destroy()` in those handlers goes; the context manager destroys the dialog.

Replace every remaining `wx.MessageBox(` in `src/gui/main_window.py` with `self._message_box(` (the `_on_fatal_link_error` deferral becomes `self._defer(self._message_box, ...)`). Afterwards `grep -n "wx.MessageBox" src/gui/main_window.py` must print only the line inside `_message_box`.

- [ ] **Step 5: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, twelve more than after Task 6. `tests/test_harness.py::test_a_first_launch_asks_through_the_recorder_not_a_real_dialog` still passes (the prompt runs synchronously at the end of `__init__`).

- [ ] **Step 6: Commit**

```bash
git add src/utils/update_checker.py src/gui/main_window.py tests/support.py tests/test_main_window.py tests/test_update_checker.py
git commit -m "Count open dialogs, and let the update prompt wait for them instead of closing the app"
```

---

### Task 8: SimConnect connects once, off the GUI thread, and the tune is checked

**Files:**
- Modify: `src/utils/simconnect_manager.py:74-111` (`set_com1_standby_mhz` never connects and checks `send_event`; new `is_connected`)
- Modify: `src/gui/main_window.py` (`__init__` caches `auto_tune_com1`; `on_settings` refreshes it; `_on_connect_result` connects the simulator; `_auto_tune` split with `_retry_auto_tune`; new `_connect_simconnect`)
- Modify: `tests/support.py` (`FakeSimConnectManager` gains `tune_results`, `connects`, `disconnects`; `make_main_window` sets `_auto_tune_com1`)
- Modify: `tests/test_uplink_handling.py` (the failed-tune test; two new tests), `tests/test_session_lifecycle.py` (connect starts the simulator connection), `tests/test_main_window.py` (settings refresh the cache)
- Create: `tests/test_simconnect_manager.py`

**Interfaces:**
- Consumes: `NetworkWorker.run_detached` (Task 1); `_on_connect_result` (Task 5).
- Produces:
  - `SimConnectManager.is_connected() -> bool`; `set_com1_standby_mhz(freq) -> bool` returns False when not connected or when `send_event` returns False or raises (dropping the connection with `exit()` in the latter two cases); `connect()` unchanged.
  - `MainWindow._auto_tune_com1` (cached from config, refreshed when Settings are saved); `_connect_simconnect(on_done=None)` runs `simconnect_manager.connect` through `worker.run_detached`; `_auto_tune(text)` tries the standby once and, on failure, disconnects, reconnects off the GUI thread and re-sends once through `_retry_auto_tune(freq, result)`, which sets `"Auto-tune failed — set <freq> manually"` when that also fails.
  - `FakeSimConnectManager(result=True, tune_results=None)`: `tune_results` is a list consumed one per `set_com1_standby_mhz` call, falling back to `result`; counters `connects`, `disconnects`; `is_connected()`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, replace `FakeSimConnectManager` with:

```python
class FakeSimConnectManager:
    """Records the frequencies the window tries to tune, never touching a simulator.

    Args:
        result: What connect() and set_com1_standby_mhz() report back
        tune_results: Answers for successive set_com1_standby_mhz() calls,
            consumed in order; `result` once they run out
    """

    def __init__(self, result=True, tune_results=None):
        self.result = result
        self.tune_results = list(tune_results or [])
        self.tuned = []
        self.connects = 0
        self.disconnects = 0

    def connect(self):
        self.connects += 1
        return self.result

    def is_connected(self):
        return self.connects > self.disconnects

    def disconnect(self):
        self.disconnects += 1

    def set_com1_standby_mhz(self, frequency_mhz):
        self.tuned.append(frequency_mhz)
        if self.tune_results:
            return self.tune_results.pop(0)
        return self.result
```

In `make_main_window`, after `window.pending_update = None`, add:

```python
    window._auto_tune_com1 = load_config().get("auto_tune_com1", True)
```

and extend the `src.config` import to `from src.config import DEFAULT_CONFIG, load_config, save_config`.

Create `tests/test_simconnect_manager.py`:

```python
"""The SimConnect manager's tune path: it never connects on its own, and it
believes the simulator's answer (audit M-9)."""

from src.utils.simconnect_manager import SimConnectManager


class FakeSim:
    """Stands in for the upstream SimConnect object."""

    def __init__(self, accept=True, raise_with=None):
        self.accept = accept
        self.raise_with = raise_with
        self.events = []
        self.exited = False

    def send_event(self, event_id, value):
        if self.raise_with is not None:
            raise self.raise_with
        self.events.append((event_id, value))
        return self.accept

    def exit(self):
        self.exited = True


def connected(sim):
    manager = SimConnectManager()
    manager._sm = sim
    manager._event_id = 7
    return manager


def test_tuning_without_a_connection_fails_without_connecting():
    manager = SimConnectManager()

    assert manager.set_com1_standby_mhz(133.325) is False
    assert manager.is_connected() is False


def test_an_accepted_event_tunes_the_standby():
    sim = FakeSim()
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is True
    assert sim.events == [(7, 133325000)]


def test_a_refused_event_is_a_failure_and_drops_the_connection():
    """Upstream returns False instead of raising when the simulator is gone;
    the old code reported success and never retuned anything."""
    sim = FakeSim(accept=False)
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is False
    assert sim.exited is True
    assert manager.is_connected() is False


def test_an_event_that_raises_drops_the_connection():
    sim = FakeSim(raise_with=OSError("pipe closed"))
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is False
    assert sim.exited is True
    assert manager.is_connected() is False
```

In `tests/test_uplink_handling.py`, replace `test_a_failed_auto_tune_tells_the_pilot_the_frequency` with:

```python
def test_a_failed_auto_tune_tells_the_pilot_the_frequency(logger):
    """One reconnect off the GUI thread, one more try; then the pilot is told."""
    window, _, _, simconnect = build(logger, simconnect=FakeSimConnectManager(result=False))

    window._on_message_received(uplink(CURRENT, 7, CONTACT))
    window.worker.run_pending()

    assert simconnect.tuned == [133.325]
    assert simconnect.connects == 1
    assert window.status_texts == ["Auto-tune failed — set 133.325 manually"]


def test_a_lost_simulator_is_reconnected_once_and_the_frequency_resent(logger):
    """MSFS closed and reopened: the first send is refused, the reconnect
    succeeds, the second send lands, and the pilot hears nothing."""
    simconnect = FakeSimConnectManager(tune_results=[False, True])
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.tuned == [133.325]
    assert simconnect.disconnects == 1

    window.worker.run_pending()

    assert simconnect.tuned == [133.325, 133.325]
    assert simconnect.connects == 1
    assert window.status_texts == []


def test_the_reconnect_does_not_run_on_the_gui_thread(logger):
    simconnect = FakeSimConnectManager(tune_results=[False, True])
    window, _, _, _ = build(logger, simconnect=simconnect)

    window._on_message_received(uplink(CURRENT, 7, CONTACT))

    assert simconnect.connects == 0
    assert window.worker.pending() == 1
```

In `test_a_failed_auto_tune_tells_the_pilot_the_frequency` the first attempt fails (`result=False`), the reconnect returns False, so no second tune is attempted: `tuned == [133.325]`.

In `tests/test_session_lifecycle.py::test_connecting_hands_the_identity_to_the_session`, after `window.worker.run_pending()` assert additionally `assert window.simconnect_manager.connects == 1` — the connect queues the simulator connection, which the same `run_pending()` also runs (the fake connect is queued behind the network connect job; call `window.worker.run_pending()` a second time before the assertion if the first run left it queued).

In `tests/test_main_window.py`, append:

```python
class FakeSettingsDialog:
    """Stands in for SettingsDialog: answers OK with auto-tune switched off."""

    def __init__(self, *args, **kwargs):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def get_settings(self):
        return ("", "", "", False, False, 5)

    def Destroy(self):
        pass


def test_saving_settings_refreshes_the_auto_tune_cache(window, monkeypatch):
    """The CONTACT path reads the cached flag rather than the config file on
    every uplink, so Settings has to refresh it."""
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)
    assert window._auto_tune_com1 is True

    window.on_settings(None)

    assert window._auto_tune_com1 is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_simconnect_manager.py tests/test_uplink_handling.py tests/test_main_window.py tests/test_session_lifecycle.py`
Expected: FAIL with `AttributeError: 'SimConnectManager' object has no attribute 'is_connected'`, the refused-event test reporting True, and the window tests failing on `connects`/`tuned` counts and on `_auto_tune_com1`.

- [ ] **Step 3: Make the manager honest and connect off the GUI thread**

In `src/utils/simconnect_manager.py`, add after `connect()`:

```python
    def is_connected(self) -> bool:
        """Whether a SimConnect session is open."""
        return self._sm is not None
```

and replace `set_com1_standby_mhz` with:

```python
    def set_com1_standby_mhz(self, frequency_mhz: float) -> bool:
        """Set COM1 standby over the existing connection.

        Never connects: connect() is slow and can block, so the window runs
        it off the GUI thread and retries the tune once afterwards.

        Args:
            frequency_mhz: Frequency in MHz (e.g. 134.750).

        Returns:
            True if the simulator took the frequency. False when not connected,
            or when the event was refused (upstream send_event returns False
            rather than raising when the simulator has gone); the connection
            is dropped then, so the next attempt reconnects.
        """
        if self._sm is None or self._event_id is None:
            return False

        freq_hz = int(round(frequency_mhz * 1_000_000))
        try:
            accepted = self._sm.send_event(self._event_id, freq_hz)
        except Exception as e:
            logger.warning(f"Failed to send COM1 standby event: {e}")
            self.disconnect()
            return False

        if accepted is False:
            logger.warning("SimConnect refused the COM1 standby event; dropping the connection")
            self.disconnect()
            return False

        logger.info(f"COM1 standby set to {frequency_mhz:.3f} MHz ({freq_hz} Hz)")
        return True
```

In `src/gui/main_window.py`:

- In `__init__`, right after the `config = load_config()` of the update-check block, add:

```python
        # Read once and refreshed by Settings, rather than from disk on every
        # uplink.
        self._auto_tune_com1 = config.get("auto_tune_com1", True)
```

- In `on_settings`, inside the `if save_config(config):` branch before the log line, add `self._auto_tune_com1 = new_auto_tune_com1`.
- In `_on_connect_result`, after `self._add_custom_message(f"Connected as {callsign}", "SYSTEM")`, add:

```python
        # Reach the simulator now, off the GUI thread, so the first CONTACT
        # does not pay for the connection.
        self._connect_simconnect()
```

- Add after `_fetch_simbrief`:

```python
    def _connect_simconnect(self, on_done=None):
        """Connect to the simulator on a thread of its own.

        SimConnect's connect can block without a timeout when the simulator is
        slow to answer, so it must not sit in the network queue.

        Args:
            on_done: Callable(JobResult) run on the GUI thread; the result's
                value is connect()'s answer
        """
        self.worker.run_detached("simconnect", self.simconnect_manager.connect, on_done)
```

- Replace `_auto_tune` with:

```python
    def _auto_tune(self, text):
        """Put a CONTACT/MONITOR frequency into the COM1 standby, if enabled.

        Args:
            text: The uplink's element text as returned by _protocol_text
        """
        if not self._auto_tune_com1:
            return

        freq = extract_contact_frequency(text)
        if freq is None:
            return

        self.logger.info(f"CONTACT/MONITOR frequency detected: {freq:.3f} MHz")
        if self.simconnect_manager.set_com1_standby_mhz(freq):
            self.logger.info(f"COM1 standby set to {freq:.3f} MHz")
            return

        # Not connected, or the simulator has gone away since: reconnect once,
        # off the GUI thread, and send the frequency again.
        self.simconnect_manager.disconnect()
        self._connect_simconnect(functools.partial(self._retry_auto_tune, freq))

    def _retry_auto_tune(self, freq, result):
        """Second and last attempt at a tune, after reconnecting. Runs on the GUI thread.

        Args:
            freq: The frequency in MHz
            result: The reconnect's JobResult
        """
        if result.ok and result.value and self.simconnect_manager.set_com1_standby_mhz(freq):
            self.logger.info(f"COM1 standby set to {freq:.3f} MHz after reconnecting")
            return

        self.logger.warning("Could not set COM1 standby (SimConnect unavailable)")
        self.SetStatusText(f"Auto-tune failed — set {freq:.3f} manually")
```

- [ ] **Step 4: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, seven more than after Task 7.

- [ ] **Step 5: Commit**

```bash
git add src/utils/simconnect_manager.py src/gui/main_window.py tests/support.py tests/test_simconnect_manager.py tests/test_uplink_handling.py tests/test_session_lifecycle.py tests/test_main_window.py
git commit -m "Connect to the simulator off the GUI thread and believe its answer to a tune"
```

---

### Task 9: Exit drains the worker, a forced close is not questioned, and `app.py` is plain

**Files:**
- Modify: `src/gui/main_window.py` (`on_close`)
- Modify: `app.py`
- Modify: `tests/support.py` (`FakeCloseEvent.CanVeto`)
- Modify: `tests/test_session_lifecycle.py` (exit tests)
- Modify: `tests/README.md`

**Interfaces:**
- Consumes: `NetworkWorker.shutdown` (Task 1); `_end_dialogue` (Task 4).
- Produces: `on_close` asks only when `event.CanVeto()`, queues the LOGOFF through `_end_dialogue`, stops polling, calls `self.worker.shutdown(timeout=5)` (which drains the queue, so the LOGOFF goes out) before the weather monitor and SimConnect are shut down. `FakeCloseEvent(can_veto=True)` with `CanVeto()`. `app.py` runs a plain `wx.App(False)`.

- [ ] **Step 1: Write the failing tests**

In `tests/support.py`, give `FakeCloseEvent.__init__` a `can_veto=True` parameter stored as `self.can_veto`, and add:

```python
    def CanVeto(self):
        return self.can_veto
```

In `tests/test_session_lifecycle.py`, replace `test_exit_logs_off_and_forgets_the_dialogue` with:

```python
def test_exit_logs_off_and_forgets_the_dialogue(logger):
    """on_close drains the worker before the window goes, so the LOGOFF it
    queued goes out without the test running the worker itself."""
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent()

    window.on_close(event)

    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert dialogue(session) == ("", None, "", 1)
    assert window.polling_controller.stopped is True
    assert window.weather_monitor.shut_down is True
    assert event.skipped is True


def test_a_forced_close_is_not_questioned_but_still_logs_off(logger, message_boxes):
    """Windows ending the session cannot be vetoed; asking would only trip a
    wx assertion and skip the cleanup (audit L-15)."""
    message_boxes.answer = wx.NO
    window, session, connection, _ = build(logger)
    event = FakeCloseEvent(can_veto=False)

    window.on_close(event)

    assert message_boxes.calls == []
    assert connection.sent == [(STATION, 1, RR.NOT_REQUIRED.value, "LOGOFF", None)]
    assert (event.vetoed, event.skipped) == (False, True)


def test_nothing_reaches_the_window_after_it_has_closed(logger):
    window, _, _, manager = build(logger)
    window.on_close(FakeCloseEvent())
    before = len(manager.message_log)

    window.cpdlc_session.request_weather("metar", "EGLL", lambda ok, text: manager.add_custom_message("late", "SYSTEM"))
    window.worker.run_pending()

    assert len(manager.message_log) == before
```

In the exit tests of Task 4 that call `window.worker.run_pending()` after `on_close(...)`, the call may stay; it is a no-op once `shutdown()` has drained the queue.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_session_lifecycle.py`
Expected: FAIL: the LOGOFF has not gone out when `on_close` returns (`connection.sent == []`), the forced close shows the confirmation, and the late callback still adds a row.

- [ ] **Step 3: Drain on exit and simplify the entry point**

In `src/gui/main_window.py`, replace `on_close` with:

```python
    def on_close(self, event):
        """Handle application close event and perform cleanup."""
        self.logger.info("Application close event triggered")

        if self.connection_manager.is_connected():
            # A forced close (Windows ending the session) cannot be vetoed, so
            # there is nothing to ask.
            if event.CanVeto() and not self._confirm_exit(event):
                return

            self.logger.info("Exit confirmed, performing clean disconnect")
            self._end_dialogue()
            self.polling_controller.stop()

        # Let the LOGOFF just queued go out, then stop delivering results to a
        # window that is about to be gone. A job stuck in a network call is
        # abandoned after the timeout.
        self.worker.shutdown(timeout=5)
        self.weather_monitor.shutdown()
        self.simconnect_manager.disconnect()
        self.logger.info("Application shutting down")
        event.Skip()  # Allow the window to close
```

Replace `app.py` in full with:

```python
#!/usr/bin/env python3
"""
Sim-CPDLC - A simple CPDLC client for SayIntentions.ai and Hoppie's ACARS

This is the main entry point for the application.
"""

import wx

from src.logging_setup import setup_logging
from src.gui import MainWindow
from src.config import get_user_data_dir
from src.error_reporting import ExceptionReporter
from src.model.connection_manager import install_request_timeout


def main():
    """Main entry point for the application."""
    # Set up logging
    logger = setup_logging()
    logger.info("Application starting")

    # Log user data directory location
    user_data_dir = get_user_data_dir()
    logger.info(f"Using user data directory: {user_data_dir}")

    # Exceptions escaping a wx handler already reach sys.excepthook; the
    # reporter logs them and shows one dialog at a time.
    ExceptionReporter(logger).install()

    # hoppie_connector passes no timeout to requests, so a server that accepts
    # the connection and then goes silent would otherwise block the worker
    # thread forever. This gives those calls a default timeout.
    install_request_timeout()

    # Create and start the application
    app = wx.App(False)
    MainWindow(None, "Sim-CPDLC", logger)

    try:
        logger.debug("Entering main application loop")
        app.MainLoop()
    finally:
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
```

(`OnExceptionInMainLoop` only ran for C++ exceptions, where `sys.exc_info()` is empty and the override raised `TypeError`; `wx.App` resets SIGINT, so the `KeyboardInterrupt` branch never ran. Audit L-14.)

- [ ] **Step 4: Update the test README**

In `tests/README.md`:

- In the paragraph on shared doubles, extend the list to `` (`uplink`, `FakeConnectionManager`, `FakeSimConnectManager`, `make_main_window`, `FakeClock`, `answerable`, `inline_worker`, ...) `` and add the sentence: `Network work runs on a worker thread in the application; tests use `inline_worker()`, which has no thread, and call `run_pending()` to run what a handler queued.`
- Add rows, keeping the table alphabetical: `| \`test_network_worker.py\` | The network worker: ordering, generations, pacing, failure capture, shutdown |`, `| \`test_simconnect_manager.py\` | The SimConnect tune path: no connecting on its own, the simulator's answer believed |`, `| \`test_update_checker.py\` | The update check off the GUI thread, and the prompt that waits for open dialogs |`, `| \`test_weather_requests.py\` | The manual weather request through the window; the report or the error arrives from the worker |`.
- Reword: `test_acknowledge_path.py` → `Responding to an uplink, end to end from the window, queued on the worker, down to the frame`; `test_dialogs.py` → `The weather request dialog's validation; the Connect and PDC dialogs filling in from SimBrief`; `test_downlink_requests.py` → `The exact text of every downlink the client can send, and every send failure, through the worker`; `test_polling_controller.py` → `Poll intervals, polls on the worker, the back-off ladder while the link is lost, batch delivery, the tick callback`; `test_session_lifecycle.py` → `Connect, disconnect and exit through the worker; a rejected logon code; a lost link is not a disconnect`; `test_weather_monitor.py` → `Weather change detection, the update cycle on the worker, the timer lifecycle`.

- [ ] **Step 5: Run the full suite**

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all green, two more than after Task 8. Also run `$PY -c "import app"` from the worktree root to be sure the entry point still imports (it must not start the app).

- [ ] **Step 6: Commit**

```bash
git add src/gui/main_window.py app.py tests/support.py tests/test_session_lifecycle.py tests/README.md
git commit -m "Drain the worker on exit, skip the question on a forced close, and simplify the entry point"
```

---

## Self-review

- **Spec coverage.** `NetworkWorker` with `Job`/`JobResult`, priorities, generations, pacing, exception capture, alive-guarded dispatch (T1); `PollingController` submitting a poll per tick and skipping while one is out (T2); `WeatherMonitor` without a thread, cycle ids, and the manual request through the same path with the dialog closing at once (T3); every `CpdlcSession` send returning `bool`, building the frame and spending the MIN synchronously, reporting through `on_done`, the acknowledgement retry removed (T4); `on_connect` submitting a connect job with the menu item disabled and the two-phase disconnect (T5, deviation 2); `ConnectDialog`/`PDCDialog` taking `fetch_simbrief` and filling in if alive (T6); `UpdateChecker` as a job, `pending_update` shown only when no dialog is open, the prompt parented and never closing the app, from-source runs skipping the check, `_show_dialog`/`_message_box` counting, the ShowModal assertion test (T7); SimConnect connected once per network connect off the GUI thread, `send_event` checked, reconnect-and-resend once, `auto_tune_com1` cached (T8, deviation 1); `install_request_timeout` with `(10, 15)` (T1), `on_close` with `CanVeto`, the LOGOFF at priority 0 and `shutdown(timeout=5)`, `app.py` without `OnExceptionInMainLoop` and the `KeyboardInterrupt` branch (T9). Landing order: T1–T3 are step one, T4–T5 step two, T6–T9 step three, each leaving the suite green.
- **Placeholders.** None; every step carries its code.
- **Type consistency.** `on_done(success, text_or_error)` is the contract everywhere a session send is called (T3 weather, T4 sends, T5 through `_end_dialogue`, T9 through `on_close`); `JobResult` callbacks take one argument and are built with `functools.partial` where extra context is needed; `FakeSimConnectManager.connects`/`disconnects` (T8) match what `_connect_simconnect` and `_auto_tune` call; `make_main_window` gains `worker` (T3), loses the retry shim (T4), gains `_modal_depth`/`pending_update` (T7) and `_auto_tune_com1` (T8) in that order, so each task's tests see the attributes they need.
