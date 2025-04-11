"""CPDLC session management for the client."""

import logging
from typing import Optional, Callable

from hoppie_connector import CpdlcResponseRequirement as RR

from src.model.connection_manager import ConnectionManager


class CpdlcSession:
    """Manages CPDLC session state and operations."""

    def __init__(self, logger, connection_manager: ConnectionManager):
        """Initialize the CPDLC session.

        Args:
            logger: Application logger
            connection_manager: Connection manager instance
        """
        self.logger = logger
        self.connection_manager = connection_manager
        self.current_station = ""
        self.cpdlc_min_counter = 1
        self.callsign = ""

    def set_callsign(self, callsign: str):
        """Set the aircraft callsign.

        Args:
            callsign: The aircraft callsign
        """
        self.callsign = callsign

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

    def logon(self, station: str) -> bool:
        """Logon to a CPDLC station.

        Args:
            station: The station to logon to

        Returns:
            bool: True if logon request sent, False otherwise
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

        self.logger.info(f"Attempting to logon to station: {station}")
        self.cpdlc_min_counter = 1
        message = "REQUEST LOGON"

        success = self.connection_manager.send_cpdlc(
            station,
            self.cpdlc_min_counter,
            RR.YES.value,
            message,
        )

        if success:
            # Don't set current_station yet, just increment the counter
            self.cpdlc_min_counter += 1
            self.logger.info(f"Logon request sent to {station}")
            return True
        else:
            self.logger.error(f"Failed to send logon request to {station}")
            return False

    def logoff(self) -> bool:
        """Logoff from the current station.

        Returns:
            bool: True if logoff request sent, False otherwise
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.debug("Logoff attempted without active station or connection")
            return False

        self.logger.info(f"Logging off from station: {self.current_station}")
        message = "LOGOFF"

        success = self.connection_manager.send_cpdlc(
            self.current_station,
            self.cpdlc_min_counter,
            RR.NOT_REQUIRED.value,
            message,
        )

        if success:
            # Update session state
            previous_station = self.current_station
            self.cpdlc_min_counter += 1
            self.current_station = ""
            self.logger.info(f"Successfully logged off from {previous_station}")
            return True
        else:
            self.logger.error(
                f"Failed to send logoff message to {self.current_station}"
            )
            return False

    def send_logoff_message(self) -> bool:
        """Send a logoff message to the current station.

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self.current_station or not self.connection_manager.is_connected():
            return False

        self.logger.info(f"Sending logoff message to {self.current_station}")
        message = "LOGOFF"

        success = self.connection_manager.send_cpdlc(
            self.current_station,
            self.cpdlc_min_counter,
            RR.NOT_REQUIRED.value,
            message,
        )

        if success:
            self.cpdlc_min_counter += 1
            previous_station = self.current_station
            self.current_station = ""
            self.logger.info(f"Successfully logged off from {previous_station}")
            return True
        else:
            self.logger.error(f"Error sending logoff message to {self.current_station}")
            return False

    def send_altitude_change_request(
        self, altitude: str, is_climb: bool, reason: Optional[str] = None
    ) -> bool:
        """Send an altitude change request.

        Args:
            altitude: The requested altitude
            is_climb: True for climb, False for descent
            reason: Optional reason for the request

        Returns:
            bool: True if request sent successfully, False otherwise
        """
        if not self.current_station or not self.connection_manager.is_connected():
            self.logger.warning(
                "Altitude change attempted without active station or connection"
            )
            return False

        direction = "climb" if is_climb else "descent"
        self.logger.info(
            f"Requesting {direction} to {altitude}"
            + (f" due to {reason}" if reason else "")
        )

        message = f"REQUEST {direction.upper()} TO {altitude}"
        if reason:
            message += f" DUE TO {reason.upper()}"

        success = self.connection_manager.send_cpdlc(
            self.current_station,
            self.cpdlc_min_counter,
            RR.W_U.value,  # Requires WILCO/UNABLE response
            message,
        )

        if success:
            self.cpdlc_min_counter += 1
            self.logger.debug(
                f"Altitude change request sent, new MIN counter: {self.cpdlc_min_counter}"
            )
            return True
        else:
            self.logger.error("Failed to send altitude change request")
            return False

    def send_acknowledgement(self, sender: str, min_value: int, response: str) -> bool:
        """Send an acknowledgement response to a CPDLC message.

        Args:
            sender: The message sender
            min_value: The message identification number
            response: The response text (WILCO, UNABLE, etc.)

        Returns:
            bool: True if acknowledgement sent successfully, False otherwise
        """
        if not self.connection_manager.is_connected():
            self.logger.error("Cannot send acknowledgement: not connected")
            return False

        self.logger.info(
            f"Acknowledging message from {sender} (MIN: {min_value}) with response: {response}"
        )

        success = self.connection_manager.send_cpdlc(
            sender,
            self.cpdlc_min_counter,
            RR.NOT_REQUIRED.value,
            response,
            mrn=min_value,
        )

        if success:
            self.cpdlc_min_counter += 1
            return True
        else:
            self.logger.error(f"Failed to send acknowledgement to {sender}")
            return False

    def send_telex(self, recipient: str, message: str) -> bool:
        """Send a TELEX message.

        Args:
            recipient: The message recipient
            message: The message text

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self.connection_manager.is_connected():
            self.logger.warning("Telex attempted without active connection")
            return False

        self.logger.info(f"Sending telex to {recipient}")
        self.logger.debug(f"Telex content: {message}")

        return self.connection_manager.send_telex(recipient, message)

    def handle_logon_accepted(self, station: str) -> None:
        """Handle a LOGON ACCEPTED message from a station.

        Args:
            station: The station that accepted the logon
        """
        # Validate station name is exactly 4 characters
        if len(station) != 4:
            self.logger.warning(
                f"Invalid station name in LOGON ACCEPTED: {station} (must be 4 characters)"
            )
            return

        # Handle both explicit logon acceptance and automatic handovers
        self.logger.info(f"Logon accepted by station: {station}")
        self.current_station = station

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
    ) -> bool:
        """Send a PDC (Pre-Departure Clearance) request.

        Args:
            origin_icao: Origin airport ICAO code
            destination_icao: Destination airport ICAO code
            aircraft_code: Aircraft type code
            stand_designator: Stand number/designator
            atis_code: ATIS information letter

        Returns:
            bool: True if request sent successfully, False otherwise
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

        return self.connection_manager.send_telex(origin_icao, message)
