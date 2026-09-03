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
        tick_callback=None,
    ):
        """Initialize the polling controller.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            message_callback: Callback for received messages
            default_poll_interval: Accepted for call-site compatibility; the
                idle interval always comes from poll_interval_range
            active_poll_interval: Interval used while a reply is expected
            inactivity_timeout: How long to stay in the faster mode after the
                last activity, in milliseconds
            poll_interval_range: (minimum, maximum) idle interval in
                milliseconds that each idle poll is randomised within
            link_callback: Callback(old_state, new_state, reason) for every
                link transition, after the status bar has been updated
            unreadable_callback: Callback(list of UnreadableMessage) for
                uplinks the library could not decode
            tick_callback: Callback() run at the end of every tick, whatever
                the poll returned, for housekeeping that keeps the poll's
                rhythm, such as giving up on an unanswered logon
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.message_callback = message_callback
        self.link_callback = link_callback
        self.unreadable_callback = unreadable_callback
        self.tick_callback = tick_callback
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
            self.logger.warning("Not connected; stopping poll timer")
            self.stop()
            return

        # The timer is one-shot, so the next tick only happens if this handler
        # arranges it. Message handling reaches into the GUI, SimConnect and a
        # nested logon, so anything raising there would otherwise end polling
        # for the rest of the session. stop() sets _stopped, so the fatal
        # branch below still ends polling deliberately.
        try:
            result = self.connection_manager.poll()
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
                self.tick_callback()
            if link_error is not None:
                raise link_error
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
        """React to a link transition: the restore text, then the window.

        The degraded and lost texts are refreshed by _show_link_status after
        every poll.
        """
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
