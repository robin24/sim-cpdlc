"""Controller for managing CPDLC polling behavior."""

import random
import time
import logging
import wx

from hoppie_connector import HoppieMessage, CpdlcMessage, TelexMessage
from src.config import MAX_POLL_INTERVAL, MIN_POLL_INTERVAL
from src.model.connection_manager import ConnectionManager
from src.utils.message_formatting import extract_message_content


class PollingController:
    """Controls polling behavior for CPDLC communications.

    Hoppie asks clients to poll "once between every 45 and 75 seconds, randomly
    timed so that the average server load is stable", and allows a faster
    once-per-20-seconds burst while a reply is expected. Each tick therefore
    schedules the next one itself rather than running on a fixed repeat, so the
    idle interval can be re-randomised every time.
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
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.message_callback = message_callback
        self.default_poll_interval = default_poll_interval
        self.active_poll_interval = active_poll_interval
        self.inactivity_timeout = inactivity_timeout
        self.poll_interval_range = poll_interval_range or (
            MIN_POLL_INTERVAL,
            MAX_POLL_INTERVAL,
        )
        self.last_activity_time = 0
        self.poll_timer = None
        self._active_mode = False
        self._stopped = True

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
        if self.poll_timer is None:
            self.poll_timer = wx.Timer(parent_window)
            parent_window.Bind(wx.EVT_TIMER, self.on_poll_timer, self.poll_timer)

        self._active_mode = False
        self._stopped = False
        self._schedule_next()
        self.logger.info(
            "Started polling timer, idle interval randomised between "
            f"{self.poll_interval_range[0]}ms and {self.poll_interval_range[1]}ms"
        )

    def stop(self):
        """Stop the polling timer."""
        self._stopped = True
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
        """Arrange the next poll, unless polling has been stopped."""
        if self._stopped or self.poll_timer is None:
            return

        interval = self.next_interval()
        self.poll_timer.StartOnce(interval)
        self.logger.debug(f"Next poll in {interval}ms")

    def on_poll_timer(self, event):
        """Handle poll timer event."""
        if not self.connection_manager.is_connected():
            self.logger.warning("Connection lost, stopping poll timer")
            self.stop()
            return

        try:
            messages, poll_status = self.connection_manager.poll()
        except Exception as e:
            self.logger.error(f"Unexpected error during poll: {e}")
            # Keep polling: a single failed attempt should not end the session.
            self._schedule_next()
            return

        # Process received messages
        if messages:
            self.logger.info(f"Received {len(messages)} new message(s)")
            for message in messages:
                self.logger.info(f"Received message: {message}")
                if self.message_callback:
                    self.message_callback(message)

                # Check if this message should trigger faster polling
                if self.should_increase_polling_rate(message):
                    self.set_active_polling()

        # Check if we should return to default polling after inactivity
        self.check_polling_timeout()

        # Check if we need to attempt reconnection
        if self.connection_manager.should_attempt_reconnection():
            self.logger.warning(
                "Maximum connection failures reached, attempting reconnection"
            )
            success = self.connection_manager.attempt_reconnection()
            if success:
                self.logger.info("Reconnection successful")
            else:
                self.logger.error("Reconnection failed")

        self._schedule_next()

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

        # Bring the next poll forward if it is further off than the active rate.
        if self.poll_timer and not self._stopped and self.poll_timer.IsRunning():
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
                # Check for common acknowledgement messages
                ack_responses = [
                    "WILCO",
                    "UNABLE",
                    "ROGER",
                    "AFFIRM",
                    "NEGATIVE",
                    "YES",
                    "NO",
                ]
                clean_content = extract_message_content(content)

                # If the message only contains an acknowledgement, don't increase polling
                if clean_content in ack_responses:
                    return False

        # For all other message types, increase polling rate
        return True
