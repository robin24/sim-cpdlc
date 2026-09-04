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
        sleep: Sleep function; the worker's own wake-able wait when None,
            injectable for the spacing tests
    """

    def __init__(
        self,
        logger,
        dispatch=wx.CallAfter,
        start_thread=True,
        spacing=None,
        clock=time.monotonic,
        sleep=None,
    ):
        self.logger = logger
        self._dispatch = dispatch
        self._spacing = dict(DEFAULT_SPACING if spacing is None else spacing)
        self._clock = clock
        # Event.wait(timeout) returns early once the event is set, so shutdown
        # can cut a pacing wait short instead of waiting the gap out.
        self._wake = threading.Event()
        self._sleep = sleep if sleep is not None else self._wake.wait
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

        Raises:
            ValueError: For a kind that is paced (send, inforeq); pacing
                only works inside the queue.
        """
        if kind in self._spacing:
            raise ValueError(f"{kind} jobs are paced; queue them with submit()")

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
        """Stop delivering results, then let queued work drain.

        Jobs still queued run to completion, but nothing is delivered from
        this point on: a result produced while draining must not reach a
        window that is going away. Pacing stops too, so the whole `timeout`
        is left for the requests themselves. With a thread, a stop marker is
        queued behind everything pending and the thread is given `timeout`
        seconds to reach it; a job stuck in a network call is abandoned (the
        thread is a daemon). Without a thread the queue is run inline.

        Args:
            timeout: Seconds to wait for the queue to drain
        """
        self._alive = False
        # Wake a pacer mid-sleep; the queue drains without further spacing.
        self._wake.set()
        if self._thread is None:
            self.run_pending()
        else:
            self._queue.put(
                Job(_STOP_PRIORITY, next(self._sequence), _STOP, None, None, self._generation)
            )
            self._thread.join(timeout)

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
        if not self._alive:
            # Shutdown has begun: the last frames go out at once rather than
            # waiting for a gap nobody will see.
            return

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
        if job.on_done is None:
            return

        if not self._alive:
            self.logger.info(
                f"Dropped the result of a {job.kind} job after shutdown (ok={result.ok}, error={result.error})"
            )
            return

        try:
            self._dispatch(job.on_done, result)
        except Exception as exc:
            # wx.CallAfter raises once the wx.App is gone (AssertionError) and
            # a dead window proxy raises RuntimeError. At shutdown neither
            # matters, and the worker must never take the process down.
            self.logger.warning(f"Dropped the result of a {job.kind} job: {exc}")
