"""Tests for the network worker: ordering, generations, pacing, failure capture.

Everything the app does on the network goes through this one queue, so its
ordering and its failure handling are what make the GUI thread safe to keep
using while a request is out.
"""

import logging
import threading
import time

import pytest

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


def test_the_inline_worker_re_raises_a_callback_error_after_draining(logger):
    """What the event loop would do with a callback that raises after
    wx.CallAfter: the rest of the queue still runs, then the error surfaces."""
    worker = inline_worker(logger)
    ran = []

    def explode(result):
        raise RuntimeError("list control gone")

    worker.submit("poll", lambda: 1, explode)
    worker.submit("poll", lambda: 2, lambda result: ran.append(result.value))

    with pytest.raises(RuntimeError, match="list control gone"):
        worker.run_pending()

    assert ran == [2]
    assert worker.errors == []


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


def test_shutdown_runs_queued_jobs_but_delivers_nothing(logger):
    """The LOGOFF queued by on_close goes out; its echo has nowhere to go."""
    worker = inline_worker(logger)
    ran, reported = [], []
    worker.submit("send", lambda: ran.append("LOGOFF"), lambda result: reported.append(result))

    worker.shutdown()

    assert ran == ["LOGOFF"]
    assert reported == []


def test_shutdown_drains_without_pacing(logger):
    """The exit LOGOFF must not wait out the send gap: the join budget is for
    the request itself."""
    clock = FakeClock()
    slept = []
    worker = NetworkWorker(
        logger, dispatch=inline, start_thread=False, spacing={"send": 5}, clock=clock, sleep=slept.append
    )
    worker.submit("send", lambda: None, priority=PRIORITY_SEND)
    worker.run_pending()
    ran = []
    worker.submit("send", lambda: ran.append("LOGOFF"), priority=PRIORITY_SEND)

    worker.shutdown()

    assert ran == ["LOGOFF"]
    assert slept == []


def test_the_real_thread_runs_jobs_and_stops_on_shutdown(logger):
    done = threading.Event()
    worker = NetworkWorker(logger, dispatch=inline)
    worker.submit("poll", lambda: 7, lambda result: done.set())

    assert done.wait(5) is True

    worker.shutdown(timeout=5)

    assert worker._thread.is_alive() is False


def test_shutdown_wakes_a_pacer_that_is_already_asleep(logger):
    """A send that entered its 5 s gap just before shutdown must go out now,
    not when the gap ends."""
    first_done = threading.Event()
    second_ran = threading.Event()
    worker = NetworkWorker(logger, dispatch=inline, spacing={"send": 5})
    worker.submit("send", lambda: first_done.set(), priority=PRIORITY_SEND)
    assert first_done.wait(5) is True
    worker.submit("send", lambda: second_ran.set(), priority=PRIORITY_SEND)
    time.sleep(0.2)  # let the worker reach _pace and start its wait

    started = time.monotonic()
    worker.shutdown(timeout=5)

    assert second_ran.is_set() is True
    assert time.monotonic() - started < 2
    assert worker._thread.is_alive() is False
