"""CPDLC session management for the client."""

import time
from typing import Optional, Callable

from hoppie_connector import CpdlcResponseRequirement as RR

from src.config import PENDING_LOGON_TIMEOUT_SECONDS, PREVIOUS_STATION_WINDOW_SECONDS
from src.model.connection_manager import ConnectionManager
from src.model.network_worker import PRIORITY_INFO, PRIORITY_SEND
from src.utils.weather_parsing import report_type_label


class CpdlcSession:
    """Manages CPDLC session state and operations.

    The session knows who the aircraft is talking to: the station logged on,
    a REQUEST LOGON still waiting for its answer, and for a while after a
    handover the station that handed the aircraft over, whose late uplinks
    (typically the CONTACT instruction) are still answerable. reset() forgets
    all of it; the callsign and network survive, because they identify the
    aircraft rather than the dialogue.
    """

    def __init__(
        self,
        logger,
        connection_manager: ConnectionManager,
        clock: Callable[[], float] = time.monotonic,
        worker=None,
    ):
        """Initialize the CPDLC session.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            clock: Returns the current time in seconds. Monotonic, so the
                session's time windows are not upset by a clock change; tests
                pass a hand-driven clock.
            worker: The NetworkWorker that performs the requests and sends
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.clock = clock
        self.worker = worker
        self.callsign = ""
        self.network = None
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self.pending_logon_min = None
        self.pending_logon_station = None
        self.pending_logon_at = None
        self.previous_station = ""
        self.previous_station_until = None

    def reset(self) -> None:
        """Forget the ATC dialogue: station, pending logon, handover window, MIN.

        The window calls this on File > Disconnect whether or not the LOGOFF
        could be sent, on a fatal link error, and (through begin_session) when
        the aircraft's identity changes. Audit M-1: without it a disconnect
        left the app believing it was still logged on.
        """
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self._clear_pending()
        self.previous_station = ""
        self.previous_station_until = None
        self.logger.debug("CPDLC session state reset")

    def begin_session(self, callsign: str, network: Optional[str]) -> None:
        """Record the identity of a new network connection.

        The network holds the ATC logon by callsign, so reconnecting as the
        same aircraft on the same network keeps the dialogue; any change of
        identity starts from a clean one.

        Args:
            callsign: The aircraft callsign
            network: The network type, "hoppie" or "sayintentions"
        """
        if (callsign, network) != (self.callsign, self.network):
            self.reset()
        self.callsign = callsign
        self.network = network

    def _clear_pending(self) -> None:
        """Forget a REQUEST LOGON that is waiting for its answer."""
        self.pending_logon_min = None
        self.pending_logon_station = None
        self.pending_logon_at = None

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

    def get_callsign(self) -> str:
        """Get the current aircraft callsign.

        Returns:
            str: The current callsign
        """
        return self.callsign

    def is_logged_on(self) -> bool:
        """Check if logged on to a station.

        Returns:
            bool: True if logged on, False otherwise
        """
        return bool(self.current_station)

    def get_current_station(self) -> str:
        """Get the current station.

        Returns:
            str: The current station or empty string if not logged on
        """
        return self.current_station

    def logon(self, station: str, on_done=None, on_logoff_done=None) -> bool:
        """Log on to a CPDLC station.

        A station still logged on is sent LOGOFF first, so it learns the
        dialogue has ended before the next one starts (audit M-7); the worker
        spaces the two frames out. The REQUEST LOGON reports through on_done,
        the LOGOFF through on_logoff_done, so each can be named for itself.

        Args:
            station: The station to log on to
            on_done: Callable(success, text_or_error) for the REQUEST LOGON,
                run on the GUI thread
            on_logoff_done: Callable(success, text_or_error) for the LOGOFF
                that precedes the request when a station is logged on; on_done
                is used when None

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
            self.logoff(on_done if on_logoff_done is None else on_logoff_done)

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

    def handle_logon_accepted(self, station: str, mrn: Optional[int] = None) -> bool:
        """Handle a LOGON ACCEPTED message from a station.

        Args:
            station: The station that accepted the logon
            mrn: The message reference number from the LOGON ACCEPTED message

        Returns:
            bool: True if the logon was accepted, False if it was ignored
        """
        # Validate station name is exactly 4 characters
        if len(station) != 4:
            self.logger.warning(
                f"Invalid station name in LOGON ACCEPTED: {station} (must be 4 characters)"
            )
            return False

        # Validate the sender against our pending logon request. The MRN
        # alone cannot do this: logon() restarts cpdlc_min_counter at 1, so
        # every pending logon carries MIN 1 and a stale acceptance from a
        # previously contacted station would match. With nothing pending —
        # before any logon, or after a rejection or an expiry — an
        # acceptance is honoured as it stands: a station may log an aircraft
        # on without a request, and there is nothing to check it against.
        if self.pending_logon_station and station != self.pending_logon_station:
            self.logger.warning(
                f"LOGON ACCEPTED from {station} does not match pending logon station "
                f"{self.pending_logon_station}, ignoring"
            )
            return False

        # Validate MRN matches our pending logon request
        if self.pending_logon_min is not None and mrn is not None:
            if mrn != self.pending_logon_min:
                self.logger.warning(
                    f"LOGON ACCEPTED MRN {mrn} does not match pending logon MIN {self.pending_logon_min}, ignoring"
                )
                return False

        self.logger.info(f"Logon accepted by station: {station}")
        self.current_station = station
        self._clear_pending()
        return True

    def handle_station_logoff(self, station: str) -> None:
        """Handle a LOGOFF message from a station.

        Args:
            station: The station that sent the logoff
        """
        if self.current_station == station:
            self.logger.info(f"Received LOGOFF from station: {station}")
            self.current_station = ""
        else:
            self.logger.warning(
                f"Received LOGOFF from {station} but current station is {self.current_station}"
            )

    def handle_handover(self, old: str, new: str, on_done=None) -> bool:
        """Follow a HANDOVER from the current station to the next one.

        The old station keeps answering for a while: in 22 of 163 logged
        handovers its CONTACT instruction arrived after the handover, in the
        same poll as the new station's LOGON ACCEPTED. Its uplinks therefore
        stay answerable for PREVIOUS_STATION_WINDOW_SECONDS. No LOGOFF is
        sent; the station handing over has ended the dialogue itself.

        Args:
            old: The station handing over; must be the current station
            new: The station to log on to
            on_done: Callable(success, text_or_error) for the REQUEST LOGON,
                run on the GUI thread

        Returns:
            bool: logon()'s answer, or False when old is not the current station
        """
        if not old or old != self.current_station:
            self.logger.warning(
                f"Ignoring handover from {old}: current station is "
                f"{self.current_station or '(none)'}"
            )
            return False

        self.logger.info(f"Handover from {old} to {new}")
        self.previous_station = old
        self.previous_station_until = self.clock() + PREVIOUS_STATION_WINDOW_SECONDS
        self.current_station = ""
        self._clear_pending()
        return self.logon(new, on_done)

    def is_answerable_sender(self, sender: str) -> bool:
        """Whether an uplink from this station can still be answered.

        True for the current station, and for the station that handed the
        aircraft over until its window closes. The message list uses this to
        decide whether to offer responses.

        Args:
            sender: The station the uplink came from
        """
        if not sender:
            return False
        if sender == self.current_station:
            return True
        return (
            sender == self.previous_station
            and self.previous_station_until is not None
            and self.clock() < self.previous_station_until
        )

    def handle_logon_rejected(self, station: str, mrn: Optional[int] = None) -> bool:
        """Handle a station refusing our REQUEST LOGON.

        Covers an explicit LOGON REJECTED and an UNABLE answering the request.
        Either must come from the station the logon is pending with, and an
        MRN, when given, must reference the pending request.

        Args:
            station: The station that answered
            mrn: The message reference number of the answer, if any

        Returns:
            bool: True if a pending logon was cancelled, False if the message
                did not concern one
        """
        if not self.pending_logon_station or station != self.pending_logon_station:
            return False
        if mrn is not None and mrn != self.pending_logon_min:
            return False

        self.logger.info(f"Logon to {station} rejected")
        self._clear_pending()
        return True

    def expire_pending(self, now: Optional[float] = None) -> Optional[str]:
        """Give up on a REQUEST LOGON nobody answered.

        Args:
            now: The current clock reading; taken from the clock when None

        Returns:
            The station whose pending logon just expired, else None
        """
        if self.pending_logon_at is None:
            return None
        now = self.clock() if now is None else now
        if now - self.pending_logon_at < PENDING_LOGON_TIMEOUT_SECONDS:
            return None

        station = self.pending_logon_station
        self.logger.warning(
            f"Logon to {station} not answered within {PENDING_LOGON_TIMEOUT_SECONDS} s"
        )
        self._clear_pending()
        return station

    def send_pdc_request(
        self,
        origin_icao: str,
        destination_icao: str,
        aircraft_code: str,
        stand_designator: str,
        atis_code: str,
        on_done=None,
    ) -> bool:
        """Send a PDC (Pre-Departure Clearance) request.

        Args:
            origin_icao: Origin airport ICAO code
            destination_icao: Destination airport ICAO code
            aircraft_code: Aircraft type code
            stand_designator: Stand number/designator
            atis_code: ATIS information letter
            on_done: Callable(success, text_or_error), run on the GUI thread

        Returns:
            bool: True if the request was queued
        """
        if not self.connection_manager.is_connected() or not self.callsign:
            self.logger.warning(
                "PDC request attempted without active connection or callsign"
            )
            return False

        self.logger.info(
            f"Requesting PDC from {origin_icao} to {destination_icao} with aircraft {aircraft_code}"
        )

        message = f"Request predep clearance {self.callsign} {aircraft_code} to {destination_icao} at {origin_icao} stand {stand_designator} atis {atis_code}".upper()

        self._submit_send(
            message, lambda: self.connection_manager.send_telex(origin_icao, message), on_done
        )
        return True

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
