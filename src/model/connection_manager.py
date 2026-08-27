"""Connection management for the CPDLC client."""

import logging
import re
import wx
import requests

from hoppie_connector import HoppieConnector, HoppieError

from src.config import SAYINTENTIONS_API_URL, HOPPIE_API_URL
from src.utils.weather_parsing import report_type_label, report_type_packet

# Hoppie wraps information responses as: {server info {actual text}}
_SERVER_INFO_PATTERN = re.compile(r"^\{server info \{(.+)\}\}$", re.DOTALL)


class ConnectionManager:
    """Manages network connections to the CPDLC service."""

    def __init__(self, logger, message_callback=None):
        """Initialize the connection manager.

        Args:
            logger: Application logger
            message_callback: Callback function for received messages
        """
        self.logger = logger
        self.cnx = None
        self.callsign = ""
        self.logon_code = ""
        self.network_type = None
        self.connection_failures = 0
        self.max_connection_failures = 3
        self.message_callback = message_callback

    def is_connected(self):
        """Check if currently connected to the network."""
        return self.cnx is not None

    def connect(self, callsign, logon_code, network_type="sayintentions"):
        """Connect to the CPDLC network.

        Args:
            callsign: Aircraft callsign
            logon_code: CPDLC logon code
            network_type: Network type ("sayintentions" or "hoppie")

        Raises:
            HoppieError: If connection fails
        """
        self.logger.info(
            f"Attempting to connect as {callsign} to {network_type} network"
        )

        # Select the appropriate API URL based on network type
        if network_type == "hoppie":
            api_url = HOPPIE_API_URL
        else:  # Default to SayIntentions
            api_url = SAYINTENTIONS_API_URL

        try:
            self.cnx = HoppieConnector(
                callsign,
                logon_code,
                url=api_url,
            )
        except HoppieError:
            self.cnx = None
            raise

        self.callsign = callsign
        self.logon_code = logon_code
        self.network_type = network_type
        self.connection_failures = 0
        self.logger.info(
            f"Successfully connected as {callsign} to {network_type} network"
        )

    def disconnect(self):
        """Disconnect from the CPDLC network."""
        if not self.cnx:
            return

        self.logger.info("Disconnecting from CPDLC network")
        self.cnx = None
        self.logger.info("Successfully disconnected")

    def poll(self):
        """Poll for new messages from the network.

        Returns:
            tuple: (messages, poll_status) or (None, None) if not connected
        """
        if not self.cnx:
            return None, None

        try:
            self.logger.debug("Polling for new messages")
            messages, poll_status = self.cnx.poll()

            # Reset connection failures counter on successful poll
            if self.connection_failures > 0:
                self.logger.debug(
                    f"Resetting connection failures from {self.connection_failures} to 0"
                )
            self.connection_failures = 0

            return messages, poll_status
        except HoppieError as exc:
            self.logger.error(f"Poll error: {exc}")

            # Increment connection failures counter
            self.connection_failures += 1
            self.logger.warning(
                f"Connection failure count: {self.connection_failures}/{self.max_connection_failures}"
            )

            return None, None

    def should_attempt_reconnection(self):
        """Check if reconnection should be attempted based on failure count."""
        return (
            self.connection_failures >= self.max_connection_failures
            and self.callsign
            and self.logon_code
        )

    def attempt_reconnection(self):
        """Attempt to reconnect to the CPDLC network.

        Returns:
            bool: True if reconnection successful, False otherwise
        """
        if not self.callsign or not self.logon_code:
            self.logger.error("Cannot reconnect: missing callsign or logon code")
            return False

        try:
            self.logger.info(f"Attempting to reconnect as {self.callsign}...")

            # Select the appropriate API URL based on stored network type
            if self.network_type == "hoppie":
                api_url = HOPPIE_API_URL
            else:
                api_url = SAYINTENTIONS_API_URL

            self.cnx = HoppieConnector(
                self.callsign,
                self.logon_code,
                url=api_url,
            )

            # Reset connection failures counter
            self.connection_failures = 0
            self.logger.info(f"Reconnection successful for {self.callsign}")
            return True
        except HoppieError as exc:
            self.logger.error(f"Reconnection failed: {exc}")
            self.cnx = None
            return False

    def send_cpdlc(self, recipient, min_value, response_type, message, mrn=None):
        """Send a CPDLC message.

        Args:
            recipient: Message recipient
            min_value: Message identification number
            response_type: Required response type
            message: Message content
            mrn: Message reference number (for responses)

        Raises:
            HoppieError: If message sending fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        self.cnx.send_cpdlc(recipient, min_value, response_type, message, mrn=mrn)

    def send_telex(self, recipient, message):
        """Send a TELEX message.

        Args:
            recipient: Message recipient
            message: Message content

        Raises:
            HoppieError: If message sending fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        self.cnx.send_telex(recipient, message)

    def _resolve_api_url(self):
        """Return the API URL matching the currently connected network."""
        if self.network_type == "hoppie":
            return HOPPIE_API_URL
        return SAYINTENTIONS_API_URL

    def send_info_request(self, info_type, icao):
        """Fetch a weather/information report via the Hoppie "inforeq" interface.

        Made as a direct HTTP GET because hoppie_connector does not model the
        inforeq message type. Blocking — callers that run on a timer should
        invoke this from a worker thread.

        Args:
            info_type: Report type key (e.g. "metar", "taf", "vatatis")
            icao: Airport ICAO code

        Returns:
            str: The report text

        Raises:
            HoppieError: If not connected or the request fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        packet_type = report_type_packet(info_type)
        label = report_type_label(info_type)

        params = {
            "logon": self.logon_code,
            "from": self.callsign,
            "to": "SERVER",
            "type": "inforeq",
            "packet": f"{packet_type} {icao}",
        }

        self.logger.info(f"Requesting {label} for {icao}")

        try:
            response = requests.get(self._resolve_api_url(), params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error(f"{label} request failed: {exc}")
            raise HoppieError(f"{label} request failed: {exc}")

        body = response.text.strip()

        if body.startswith("ok "):
            report_text = body[3:].strip()
            # Response is wrapped as {server info {actual text}} — extract inner content
            match = _SERVER_INFO_PATTERN.match(report_text)
            if match:
                report_text = match.group(1).strip()

            if not report_text:
                self.logger.warning(f"Empty {label} response for {icao}")
                raise HoppieError(f"No {label} available for {icao}")

            self.logger.info(f"Received {label} for {icao}")
            return report_text
        elif body.startswith("error "):
            error_reason = body[6:].strip()
            self.logger.error(f"{label} request error: {error_reason}")
            raise HoppieError(f"{label} request error: {error_reason}")
        else:
            self.logger.error(f"Unexpected {label} response: {body}")
            raise HoppieError(f"Unexpected response: {body}")

    def send_metar_request(self, icao):
        """Send a METAR information request.

        Args:
            icao: Airport ICAO code

        Returns:
            str: The METAR text

        Raises:
            HoppieError: If not connected or request fails
        """
        return self.send_info_request("metar", icao)

    def send_atis_request(self, icao, source="vatatis"):
        """Send an ATIS information request.

        Args:
            icao: Airport ICAO code
            source: ATIS source key ("vatatis", "ivaoatis" or "peatis")

        Returns:
            str: The ATIS text

        Raises:
            HoppieError: If not connected or request fails
        """
        return self.send_info_request(source, icao)
