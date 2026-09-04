"""SimConnect connection manager for setting COM1 standby frequency in MSFS."""

import logging
from typing import Optional

logger = logging.getLogger("Sim-CPDLC")

# Cache the import availability check
_simconnect_available: Optional[bool] = None


class SimConnectManager:
    """Manages SimConnect connection lifecycle and COM1 standby tuning."""

    def __init__(self):
        self._sm = None
        self._event_id = None
        self._warned_unavailable = False

    def is_available(self) -> bool:
        """Check if the SimConnect package is importable."""
        global _simconnect_available
        if _simconnect_available is None:
            try:
                import SimConnect  # noqa: F401

                _simconnect_available = True
            except ImportError:
                _simconnect_available = False
                if not self._warned_unavailable:
                    logger.warning(
                        "SimConnect package not installed — auto-tune COM1 disabled"
                    )
                    self._warned_unavailable = True
        return _simconnect_available

    def connect(self) -> bool:
        """Establish a SimConnect connection and map the COM_STBY_RADIO_SET_HZ event.

        Returns:
            True if connected successfully, False otherwise.
        """
        if self._sm is not None:
            return True

        if not self.is_available():
            return False

        try:
            from SimConnect import SimConnect

            self._sm = SimConnect()
            self._event_id = self._sm.map_to_sim_event(b"COM_STBY_RADIO_SET_HZ")
            logger.info("SimConnect connected and COM_STBY_RADIO_SET_HZ mapped")
            return True
        except Exception as e:
            logger.warning(f"SimConnect connection failed: {e}")
            self._sm = None
            self._event_id = None
            return False

    def disconnect(self):
        """Clean up the SimConnect connection."""
        if self._sm is not None:
            try:
                self._sm.exit()
            except Exception as e:
                logger.debug(f"SimConnect disconnect error: {e}")
            finally:
                self._sm = None
                self._event_id = None
                logger.info("SimConnect disconnected")

    def is_connected(self) -> bool:
        """Whether a SimConnect session is open."""
        return self._sm is not None

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
