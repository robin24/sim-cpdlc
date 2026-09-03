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
