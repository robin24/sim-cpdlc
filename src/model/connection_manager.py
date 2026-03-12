"""Connection management for the CPDLC client."""

import logging
import wx
import requests

from hoppie_connector import HoppieConnector, HoppieError

from src.config import SAYINTENTIONS_API_URL, HOPPIE_API_URL


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

    def send_metar_request(self, icao):
        """Send a METAR information request via the Hoppie API.

        Args:
            icao: Airport ICAO code

        Returns:
            str: The METAR text

        Raises:
            HoppieError: If not connected or request fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        # Select the appropriate API URL based on stored network type
        if self.network_type == "hoppie":
            api_url = HOPPIE_API_URL
        else:
            api_url = SAYINTENTIONS_API_URL

        params = {
            "logon": self.logon_code,
            "from": self.callsign,
            "to": "SERVER",
            "type": "inforeq",
            "packet": f"metar {icao}",
        }

        self.logger.info(f"Requesting METAR for {icao}")

        try:
            response = requests.get(api_url, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error(f"METAR request failed: {exc}")
            raise HoppieError(f"METAR request failed: {exc}")

        body = response.text.strip()

        if body.startswith("ok "):
            metar_text = body[3:].strip()
            import re
            match = re.match(r"^\{server info \{(.+)\}\}$", metar_text, re.DOTALL)
            if match:
                metar_text = match.group(1).strip()
            self.logger.info(f"Received METAR for {icao}")
            return metar_text
        elif body.startswith("error "):
            error_reason = body[6:].strip()
            self.logger.error(f"METAR request error: {error_reason}")
            raise HoppieError(f"METAR request error: {error_reason}")
        else:
            self.logger.error(f"Unexpected METAR response: {body}")
            raise HoppieError(f"Unexpected response: {body}")

    def send_atis_request(self, icao):
        """Send an ATIS information request via the Hoppie API.

        Makes a direct HTTP GET request since hoppie_connector doesn't
        support the inforeq message type. Always uses Hoppie's API since
        vatatis is a Hoppie-specific feature.

        Args:
            icao: Airport ICAO code

        Returns:
            str: The ATIS text

        Raises:
            HoppieError: If not connected or request fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        # Select the appropriate API URL based on stored network type
        if self.network_type == "hoppie":
            api_url = HOPPIE_API_URL
        else:
            api_url = SAYINTENTIONS_API_URL

        params = {
            "logon": self.logon_code,
            "from": self.callsign,
            "to": "SERVER",
            "type": "inforeq",
            "packet": f"vatatis {icao}",
        }

        self.logger.info(f"Requesting ATIS for {icao}")

        try:
            response = requests.get(api_url, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error(f"ATIS request failed: {exc}")
            raise HoppieError(f"ATIS request failed: {exc}")

        body = response.text.strip()

        if body.startswith("ok "):
            atis_text = body[3:].strip()
            # Response is wrapped as {server info {actual text}} — extract inner content
            import re
            match = re.match(r"^\{server info \{(.+)\}\}$", atis_text, re.DOTALL)
            if match:
                atis_text = match.group(1).strip()
            self.logger.info(f"Received ATIS for {icao}")
            return atis_text
        elif body.startswith("error "):
            error_reason = body[6:].strip()
            self.logger.error(f"ATIS request error: {error_reason}")
            raise HoppieError(f"ATIS request error: {error_reason}")
        else:
            self.logger.error(f"Unexpected ATIS response: {body}")
            raise HoppieError(f"Unexpected response: {body}")
