"""CPDLC session management for the client."""

import logging
import time
from typing import Optional, Callable, Tuple

from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

from src.model.connection_manager import ConnectionManager
from src.utils.weather_parsing import report_type_label


class CpdlcSession:
    """Manages CPDLC session state and operations.

    The session knows who the aircraft is talking to: the station logged on
    and a REQUEST LOGON still waiting for its answer. reset() forgets all of
    it; the callsign and network survive, because they identify the aircraft
    rather than the dialogue.
    """

    def __init__(
        self,
        logger,
        connection_manager: ConnectionManager,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Initialize the CPDLC session.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
            clock: Returns the current time in seconds. Monotonic, so the
                session's time windows are not upset by a clock change; tests
                pass a hand-driven clock.
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.clock = clock
        self.callsign = ""
        self.network = None
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self.pending_logon_min = None
        self.pending_logon_station = None
        self.pending_logon_at = None

    def reset(self) -> None:
        """Forget the ATC dialogue: station, pending logon and MIN counter.

        The window calls this on File > Disconnect whether or not the LOGOFF
        could be sent, on a fatal link error, and (through begin_session) when
        the aircraft's identity changes. Audit M-1: without it a disconnect
        left the app believing it was still logged on.
        """
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self._clear_pending()
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

    def logon(self, station: str) -> Tuple[bool, Optional[str]]:
        """Logon to a CPDLC station.

        A station still logged on is sent LOGOFF first, so it learns the
        dialogue has ended before the next one starts (audit M-7). If that
        LOGOFF cannot be sent nothing else is: the app never has a dialogue
        open with two stations, and the pilot retries once the link is back.

        Args:
            station: The station to logon to

        Returns:
            tuple: (success, message_or_error) where success is True and message_or_error
                  is the sent message text, or success is False and message_or_error is
                  an error description (or None for precondition failures)
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Logon attempted without active connection")
            return False, None

        # Validate station name is exactly 4 characters
        if len(station) != 4:
            self.logger.warning(
                f"Invalid station name: {station} (must be 4 characters)"
            )
            return False, None

        if self.current_station:
            previous = self.current_station
            sent, detail = self.logoff()
            if not sent:
                return False, f"could not send LOGOFF to {previous}: {detail}"

        self.logger.info(f"Attempting to logon to station: {station}")
        self.cpdlc_min_counter = 1
        message = "REQUEST LOGON"

        try:
            self.connection_manager.send_cpdlc(
                station,
                self.cpdlc_min_counter,
                RR.YES.value,
                message,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send logon request to {station}: {exc}")
            return False, str(exc)

        # Track the pending logon for MRN validation on LOGON ACCEPTED, and
        # when it was sent so an unanswered request can be given up on
        self.pending_logon_min = self.cpdlc_min_counter
        self.pending_logon_station = station
        self.pending_logon_at = self.clock()

        # Don't set current_station yet, just increment the counter
        self.cpdlc_min_counter += 1
        self.logger.info(f"Logon request sent to {station}")
        return True, message

    def logoff(self) -> Tuple[bool, Optional[str]]:
        """Logoff from the current station.

        Returns:
            tuple: (success, message_or_error) where success is True and message_or_error
                  is the sent message text, or success is False and message_or_error is
                  an error description (or None for precondition failures)
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.debug("Logoff attempted without active station or connection")
            return False, None

        self.logger.info(f"Logging off from station: {self.current_station}")
        message = "LOGOFF"

        try:
            self.connection_manager.send_cpdlc(
                self.current_station,
                self.cpdlc_min_counter,
                RR.NOT_REQUIRED.value,
                message,
            )
        except HoppieError as exc:
            self.logger.error(
                f"Failed to send logoff message to {self.current_station}: {exc}"
            )
            return False, str(exc)

        # Update session state. A logon that was still pending is abandoned
        # too: the pilot is leaving the dialogue, not waiting on it.
        previous_station = self.current_station
        self.cpdlc_min_counter += 1
        self.current_station = ""
        self._clear_pending()
        self.logger.info(f"Successfully logged off from {previous_station}")
        return True, message

    def send_logoff_message(self) -> Tuple[bool, Optional[str]]:
        """Send a logoff message to the current station.

        Alias for logoff() kept for backward compatibility.

        Returns:
            tuple: (success, message_text) where success is True if message sent successfully,
                  and message_text is the message text that was sent (or None if failed)
        """
        return self.logoff()

    def send_altitude_change_request(
        self, altitude: str, reason: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Send an altitude change request.

        Args:
            altitude: The requested altitude (e.g. "FL350")
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"

        Returns:
            tuple: (success, message_text) where success is True if request sent successfully,
                  and message_text is the message text that was sent (or None if failed)
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(
                "Altitude change attempted without active station or connection"
            )
            return False, None

        self.logger.info(
            f"Requesting {altitude}"
            + (f" due to {reason}" if reason else "")
        )

        message = f"REQUEST {altitude}"
        if reason:
            message += f" DUE TO {reason}"

        try:
            self.connection_manager.send_cpdlc(
                self.current_station,
                self.cpdlc_min_counter,
                RR.YES.value,  # Yes/No response (network approves or denies)
                message,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send altitude change request: {exc}")
            return False, str(exc)

        self.cpdlc_min_counter += 1
        self.logger.debug(
            f"Altitude change request sent, new MIN counter: {self.cpdlc_min_counter}"
        )
        return True, message

    def send_acknowledgement(
        self, sender: str, min_value: int, response: str
    ) -> Tuple[bool, Optional[str]]:
        """Send an acknowledgement response to a CPDLC message.

        Args:
            sender: The message sender
            min_value: The message identification number
            response: The response text (WILCO, UNABLE, etc.)

        Returns:
            tuple: (success, message_text) where success is True if acknowledgement sent successfully,
                  and message_text is the message text that was sent (or None if failed)
        """
        if not self.connection_manager.is_connected():
            self.logger.error("Cannot send acknowledgement: not connected")
            return False, None

        if self.current_station and sender != self.current_station:
            self.logger.warning(
                f"Acknowledgement sender {sender} does not match current station {self.current_station}"
            )

        self.logger.info(
            f"Acknowledging message from {sender} (MIN: {min_value}) with response: {response}"
        )

        try:
            self.connection_manager.send_cpdlc(
                sender,
                self.cpdlc_min_counter,
                RR.NO.value,
                response,
                mrn=min_value,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send acknowledgement to {sender}: {exc}")
            return False, str(exc)

        self.cpdlc_min_counter += 1
        return True, response

    def _request_info(self, icao: str, label: str, send) -> Tuple[bool, Optional[str]]:
        """Run an information request and normalise the result.

        Args:
            icao: Airport ICAO code
            label: Human-readable request name for log messages
            send: Callable taking the ICAO code and returning the response text

        Returns:
            tuple: (success, text_or_error)
        """
        if not self.connection_manager.is_connected():
            self.logger.warning(
                f"{label} request attempted without active connection"
            )
            return False, None

        try:
            return True, send(icao)
        except HoppieError as exc:
            self.logger.error(f"Failed to request {label} for {icao}: {exc}")
            return False, str(exc)

    def send_direct_request(
        self, fix: str, reason: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Send a direct-to waypoint request.

        Args:
            fix: The waypoint/fix name
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"

        Returns:
            tuple: (success, message_text)
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(
                "Direct request attempted without active station or connection"
            )
            return False, None

        message = f"REQUEST DIRECT TO {fix}"
        if reason:
            message += f" DUE TO {reason}"

        try:
            self.connection_manager.send_cpdlc(
                self.current_station,
                self.cpdlc_min_counter,
                RR.YES.value,
                message,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send direct request: {exc}")
            return False, str(exc)

        self.cpdlc_min_counter += 1
        return True, message

    def send_speed_request(
        self, speed: str, is_mach: bool, reason: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Send a speed change request.

        Args:
            speed: The speed value (e.g. "082" for Mach, "300" for knots)
            is_mach: True for Mach, False for knots
            reason: Optional reason — "WEATHER" or "AIRCRAFT PERFORMANCE"

        Returns:
            tuple: (success, message_text)
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(
                "Speed request attempted without active station or connection"
            )
            return False, None

        if is_mach:
            message = f"REQUEST M{speed}"
        else:
            message = f"REQUEST {speed}K"

        if reason:
            message += f" DUE TO {reason}"

        try:
            self.connection_manager.send_cpdlc(
                self.current_station,
                self.cpdlc_min_counter,
                RR.YES.value,
                message,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send speed request: {exc}")
            return False, str(exc)

        self.cpdlc_min_counter += 1
        return True, message

    def send_when_can_we_expect(self, message_text: str) -> Tuple[bool, Optional[str]]:
        """Send a WHEN CAN WE EXPECT inquiry.

        Args:
            message_text: The full message text (e.g. "WHEN CAN WE EXPECT HIGHER LEVEL")

        Returns:
            tuple: (success, message_text)
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(
                "When-can-we-expect request attempted without active station or connection"
            )
            return False, None

        try:
            self.connection_manager.send_cpdlc(
                self.current_station,
                self.cpdlc_min_counter,
                RR.YES.value,
                message_text,
            )
        except HoppieError as exc:
            self.logger.error(f"Failed to send when-can-we-expect request: {exc}")
            return False, str(exc)

        self.cpdlc_min_counter += 1
        return True, message_text

    def send_telex(self, recipient: str, message: str) -> Tuple[bool, Optional[str]]:
        """Send a TELEX message.

        Args:
            recipient: The message recipient
            message: The message text

        Returns:
            tuple: (success, message_text) where success is True if message sent successfully,
                  and message_text is the message text that was sent (or None if failed)
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Telex attempted without active connection")
            return False, None

        self.logger.info(f"Sending telex to {recipient}")
        self.logger.debug(f"Telex content: {message}")

        try:
            self.connection_manager.send_telex(recipient, message)
        except HoppieError as exc:
            self.logger.error(f"Failed to send telex to {recipient}: {exc}")
            return False, str(exc)

        return True, message

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

        # Validate the sender against our pending logon request. The MRN alone
        # cannot do this: logon() restarts cpdlc_min_counter at 1, so every
        # pending logon carries MIN 1 and a stale acceptance from a previously
        # contacted station would match. Only checked when a logon is pending,
        # so unsolicited acceptances during an automatic handover still apply.
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

    def send_pdc_request(
        self,
        origin_icao: str,
        destination_icao: str,
        aircraft_code: str,
        stand_designator: str,
        atis_code: str,
    ) -> Tuple[bool, Optional[str]]:
        """Send a PDC (Pre-Departure Clearance) request.

        Args:
            origin_icao: Origin airport ICAO code
            destination_icao: Destination airport ICAO code
            aircraft_code: Aircraft type code
            stand_designator: Stand number/designator
            atis_code: ATIS information letter

        Returns:
            tuple: (success, message_text) where success is True if request sent successfully,
                  and message_text is the message text that was sent (or None if failed)
        """
        if not self.connection_manager.is_connected() or not self.callsign:
            self.logger.warning(
                "PDC request attempted without active connection or callsign"
            )
            return False, None

        self.logger.info(
            f"Requesting PDC from {origin_icao} to {destination_icao} with aircraft {aircraft_code}"
        )

        message = f"Request predep clearance {self.callsign} {aircraft_code} to {destination_icao} at {origin_icao} stand {stand_designator} atis {atis_code}".upper()

        try:
            self.connection_manager.send_telex(origin_icao, message)
        except HoppieError as exc:
            self.logger.error(f"Failed to send PDC request to {origin_icao}: {exc}")
            return False, str(exc)

        return True, message

    def request_weather(self, info_type: str, icao: str) -> Tuple[bool, Optional[str]]:
        """Request a weather/information report for an airport.

        Args:
            info_type: Report type key ("metar", "taf", "shorttaf", "vatatis")
            icao: Airport ICAO code

        Returns:
            tuple: (success, report_text_or_error)
        """
        return self._request_info(
            icao,
            report_type_label(info_type),
            lambda code: self.connection_manager.send_info_request(info_type, code),
        )
