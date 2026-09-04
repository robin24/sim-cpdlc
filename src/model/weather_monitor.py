"""Automatic weather updates for subscribed airports.

Neither Hoppie nor SayIntentions push weather to the aircraft, so an automatic
update is really a polite re-request on a timer. This module keeps the list of
subscribed airports, re-fetches each report through the network worker so the
GUI never blocks on network I/O, and only announces a report when it has
actually changed (a new ATIS letter, or amended METAR/TAF text).
"""

import functools
import time

import wx

from src.model.network_worker import PRIORITY_INFO
from src.utils.weather_parsing import (
    describe_report,
    report_signature,
    report_type_label,
)

# Consecutive failures tolerated before a subscription is dropped, so a
# mistyped ICAO or an airport with no ATIS doesn't retry forever.
MAX_CONSECUTIVE_ERRORS = 5


class WeatherSubscription:
    """One airport/report-type pair being kept up to date."""

    def __init__(self, icao, info_type):
        """Initialize the subscription.

        Args:
            icao: Airport ICAO code
            info_type: Report type key (e.g. "metar", "vatatis")
        """
        self.icao = icao.upper()
        self.info_type = info_type
        self.signature = None
        self.text = ""
        self.last_update = None
        self.error_count = 0

    @property
    def key(self):
        """Return the tuple that uniquely identifies this subscription."""
        return (self.icao, self.info_type)

    def describe(self):
        """Return a human-readable description of what is being watched."""
        return f"{report_type_label(self.info_type)} for {self.icao}"


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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, parent_window):
        """Start the update timer, or restart it after a disconnect.

        Args:
            parent_window: The window that owns the timer
        """
        self._shutting_down = False

        if self._timer is None:
            self._parent = parent_window
            self._timer = wx.Timer(parent_window)
            parent_window.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

        if not self._timer.IsRunning():
            self._timer.Start(self.interval_ms)
            self.logger.info(
                f"Started weather monitor with interval {self.interval_ms}ms"
            )

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

    def shutdown(self):
        """Stop the timer and drop every subscription."""
        self.stop()
        self._subscriptions.clear()
        if self._timer is not None:
            self._timer.Destroy()
            self._timer = None

    def set_interval(self, interval_ms):
        """Change how often subscriptions are re-checked.

        Args:
            interval_ms: New interval in milliseconds
        """
        self.interval_ms = interval_ms
        if self._timer and self._timer.IsRunning():
            self._timer.Stop()
            self._timer.Start(interval_ms)
            self.logger.info(f"Weather monitor interval set to {interval_ms}ms")

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, icao, info_type, initial_text=None):
        """Start keeping a report up to date.

        Args:
            icao: Airport ICAO code
            info_type: Report type key
            initial_text: Report text already shown to the user, if any. Passing
                it prevents the first automatic check from re-announcing a
                report the user just requested by hand.

        Returns:
            bool: True if a new subscription was created, False if it existed
        """
        subscription = WeatherSubscription(icao, info_type)

        if subscription.key in self._subscriptions:
            existing = self._subscriptions[subscription.key]
            if initial_text:
                existing.text = initial_text
                existing.signature = report_signature(
                    initial_text, info_type, existing.icao
                )
            return False

        if initial_text:
            subscription.text = initial_text
            subscription.signature = report_signature(
                initial_text, info_type, subscription.icao
            )

        self._subscriptions[subscription.key] = subscription
        self.logger.info(f"Subscribed to automatic updates: {subscription.describe()}")
        return True

    def unsubscribe(self, icao, info_type):
        """Stop keeping a report up to date.

        Args:
            icao: Airport ICAO code
            info_type: Report type key

        Returns:
            bool: True if a subscription was removed
        """
        key = (icao.upper(), info_type)
        subscription = self._subscriptions.pop(key, None)
        if subscription:
            self.logger.info(
                f"Unsubscribed from automatic updates: {subscription.describe()}"
            )
            return True
        return False

    def is_subscribed(self, icao, info_type):
        """Check whether a report is being kept up to date."""
        return (icao.upper(), info_type) in self._subscriptions

    def get_subscriptions(self):
        """Return the current subscriptions, sorted for stable display."""
        return sorted(
            self._subscriptions.values(), key=lambda s: (s.icao, s.info_type)
        )

    def count(self):
        """Return the number of active subscriptions."""
        return len(self._subscriptions)

    def clear(self):
        """Drop every subscription."""
        if self._subscriptions:
            self.logger.info(
                f"Cleared {len(self._subscriptions)} weather subscription(s)"
            )
        self._subscriptions.clear()

    # ------------------------------------------------------------------
    # Update cycle
    # ------------------------------------------------------------------

    def check_now(self):
        """Run an update cycle immediately, outside the normal timer tick.

        Returns:
            bool: True if a cycle started. False when there is nothing to
                check, a cycle is already running, or the monitor is stopped
                or disconnected -- the caller should not claim otherwise.
        """
        return self._run_cycle()

    def _on_timer(self, _):
        """Handle the periodic update timer."""
        self._run_cycle()

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

    def _on_result(self, icao, info_type, text, error):
        """Apply one fetch result. Runs on the GUI thread.

        Args:
            icao: Airport ICAO code
            info_type: Report type key
            text: The fetched report, or None if the fetch failed
            error: Error description, or None on success
        """
        subscription = self._subscriptions.get((icao, info_type))
        if subscription is None:
            # Unsubscribed while the request was in flight.
            return

        if error is not None:
            subscription.error_count += 1
            self.logger.warning(
                f"Automatic update failed for {subscription.describe()} "
                f"({subscription.error_count}/{MAX_CONSECUTIVE_ERRORS}): {error}"
            )
            if subscription.error_count >= MAX_CONSECUTIVE_ERRORS:
                self._subscriptions.pop(subscription.key, None)
                self.logger.error(
                    f"Giving up on automatic updates for {subscription.describe()}"
                )
                if self.on_error:
                    self.on_error(subscription, error)
            return

        subscription.error_count = 0
        subscription.last_update = time.time()

        signature = report_signature(text, info_type, icao)
        if signature == subscription.signature:
            self.logger.debug(f"No change in {subscription.describe()}")
            return

        is_first = subscription.signature is None
        subscription.signature = signature
        subscription.text = text

        self.logger.info(
            f"{'Initial' if is_first else 'Updated'} report for "
            f"{subscription.describe()}"
        )

        if self.on_update:
            self.on_update(
                subscription, text, describe_report(text, info_type, icao)
            )
