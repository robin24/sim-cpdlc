"""Controller for managing CPDLC polling behavior."""

import time
import logging
import wx

from hoppie_connector import HoppieMessage, CpdlcMessage
from src.model.connection_manager import ConnectionManager
from src.utils.message_formatting import extract_message_content


class PollingController:
    """Controls polling behavior for CPDLC communications."""

    def __init__(
        self,
        logger,
        connection_manager: ConnectionManager,
        message_callback=None,
        default_poll_interval=60000,  # 60 seconds
        active_poll_interval=20000,  # 20 seconds
        inactivity_timeout=300000,  # 5 minutes
    ):
        """Initialize the polling controller.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            message_callback: Callback for received messages
            default_poll_interval: Default polling interval in milliseconds
            active_poll_interval: Active polling interval in milliseconds
            inactivity_timeout: Inactivity timeout in milliseconds
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.message_callback = message_callback
        self.default_poll_interval = default_poll_interval
        self.active_poll_interval = active_poll_interval
        self.inactivity_timeout = inactivity_timeout
        self.last_activity_time = 0
        self.poll_timer = None

    def start(self, parent_window):
        """Start the polling timer.

        Args:
            parent_window: The parent window for the timer
        """
        self.poll_timer = wx.Timer(parent_window)
        parent_window.Bind(wx.EVT_TIMER, self.on_poll_timer, self.poll_timer)
        self.poll_timer.Start(self.default_poll_interval)
        self.logger.info(
            f"Started polling timer with interval {self.default_poll_interval}ms"
        )

    def stop(self):
        """Stop the polling timer."""
        if self.poll_timer and self.poll_timer.IsRunning():
            self.poll_timer.Stop()
            self.logger.info("Stopped polling timer")

    def is_running(self):
        """Check if the polling timer is running.

        Returns:
            bool: True if running, False otherwise
        """
        return self.poll_timer and self.poll_timer.IsRunning()

    def on_poll_timer(self, event):
        """Handle poll timer event."""
        if not self.connection_manager.is_connected():
            self.logger.warning("Connection lost, stopping poll timer")
            self.stop()
            return

        messages, poll_status = self.connection_manager.poll()

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
                # Restart the poll timer if it's not running
                if not self.is_running():
                    self.poll_timer.Start(self.default_poll_interval)
            else:
                self.logger.error("Reconnection failed")

    def set_active_polling(self):
        """Switch to more frequent polling during active communication."""
        if not self.poll_timer:
            return

        current_interval = self.poll_timer.GetInterval()
        if current_interval != self.active_poll_interval:
            self.logger.debug(
                f"Switching to active polling interval: {self.active_poll_interval}ms"
            )
            self.poll_timer.Stop()
            self.poll_timer.Start(self.active_poll_interval)

        # Update the last activity timestamp
        self.last_activity_time = time.time()
        self.logger.debug(f"Updated last activity time: {self.last_activity_time}")

    def check_polling_timeout(self):
        """Check if we should return to default polling after period of inactivity."""
        if not self.poll_timer:
            return

        # Skip if we're already at the default interval
        current_interval = self.poll_timer.GetInterval()
        if current_interval == self.default_poll_interval:
            return

        current_time = time.time()
        elapsed = current_time - self.last_activity_time
        elapsed_ms = elapsed * 1000  # Convert seconds to milliseconds

        # If more than inactivity_timeout has passed, return to default polling
        if elapsed_ms > self.inactivity_timeout:
            self.logger.info(
                f"Inactivity timeout reached ({elapsed:.1f}s). Returning to default polling interval of {self.default_poll_interval}ms"
            )
            self.poll_timer.Stop()
            self.poll_timer.Start(self.default_poll_interval)

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
        if message.__class__.__name__ == "TelexMessage":
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
