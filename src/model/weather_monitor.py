"""Automatic weather updates for subscribed airports.

Neither Hoppie nor SayIntentions push weather to the aircraft, so an automatic
update is really a polite re-request on a timer. This module keeps the list of
subscribed airports, re-fetches each report in a worker thread so the GUI never
blocks on network I/O, and only announces a report when it has actually changed
(a new ATIS letter, or amended METAR/TAF text).
"""

import threading
import time

import wx

from hoppie_connector import HoppieError

from src.utils.weather_parsing import (
    describe_report,
    report_signature,
    report_type_label,
)

# Pause between consecutive fetches in one cycle, so a handful of
# subscriptions doesn't arrive at the server as a burst.
_REQUEST_SPACING_SECONDS = 1.0

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
    snapshot, hands it to a short-lived worker thread that performs the
    blocking HTTP requests, and results come back via wx.CallAfter — so
    nothing here mutates shared state from two threads at once.
    """

    def __init__(
        self,
        logger,
        connection_manager,
        on_update=None,
        on_error=None,
        interval_ms=300000,
    ):
        """Initialize the weather monitor.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            on_update: Callback(subscription, text, description) for new reports
            on_error: Callback(subscription, error_text) for repeated failures
            interval_ms: How often to re-check each subscription
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.on_update = on_update
        self.on_error = on_error
        self.interval_ms = interval_ms

        self._subscriptions = {}
        self._timer = None
        self._parent = None
        self._cycle_running = False
        self._shutting_down = False

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
        """Stop the update timer, leaving subscriptions in place."""
        self._shutting_down = True
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
        """Kick off a fetch for every subscription, on a worker thread.

        Returns:
            bool: True if a cycle started, False if it was skipped.
        """
        if self._shutting_down or not self._subscriptions or self._parent is None:
            return False

        if self._cycle_running:
            self.logger.debug("Weather update cycle still running, skipping this tick")
            return False

        if not self.connection_manager.is_connected():
            self.logger.debug("Not connected, skipping weather update cycle")
            return False

        # Snapshot on the GUI thread so the worker never touches the live dict.
        pending = [(s.icao, s.info_type) for s in self._subscriptions.values()]

        self._cycle_running = True
        thread = threading.Thread(
            target=self._fetch_worker, args=(pending,), daemon=True
        )
        thread.start()
        return True

    def _fetch_worker(self, pending):
        """Fetch each subscribed report. Runs on a worker thread.

        Args:
            pending: List of (icao, info_type) tuples to fetch
        """
        try:
            for index, (icao, info_type) in enumerate(pending):
                if self._shutting_down:
                    break

                if index:
                    time.sleep(_REQUEST_SPACING_SECONDS)

                try:
                    text = self.connection_manager.send_info_request(info_type, icao)
                    error = None
                except HoppieError as exc:
                    text = None
                    error = str(exc)
                except Exception as exc:  # pragma: no cover - defensive
                    text = None
                    error = str(exc)
                    self.logger.error(
                        f"Unexpected error fetching {info_type} for {icao}: {exc}"
                    )

                self._post_result(icao, info_type, text, error)
        finally:
            self._post_cycle_finished()

    def _post_result(self, icao, info_type, text, error):
        """Hand one fetch result back to the GUI thread."""
        if self._shutting_down or not self._parent or self._parent.IsBeingDeleted():
            return
        wx.CallAfter(self._on_result, icao, info_type, text, error)

    def _post_cycle_finished(self):
        """Clear the in-progress flag on the GUI thread."""
        if not self._parent or self._parent.IsBeingDeleted():
            self._cycle_running = False
            return
        wx.CallAfter(self._on_cycle_finished)

    def _on_cycle_finished(self):
        """Mark the update cycle as complete. Runs on the GUI thread."""
        self._cycle_running = False

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
