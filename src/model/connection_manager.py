"""Connection management for the CPDLC client."""

import functools
import re

import requests

from hoppie_connector import HoppieConnector, HoppieError

from src.config import (
    SAYINTENTIONS_API_URL,
    HOPPIE_API_URL,
    MAX_CONNECTION_FAILURES,
    NETWORK_TIMEOUT,
)
from src.utils.weather_parsing import report_type_label, report_type_packet


# Transport failures worth retrying. The builtin ConnectionError is what
# hoppie_connector raises for a non-OK HTTP status; requests' own hierarchy
# covers timeouts and DNS failures. Deliberately narrower than OSError, which
# would also swallow local faults such as a missing CA bundle in a packaged
# build and misreport them as a network outage.
TRANSPORT_ERRORS = (ConnectionError, TimeoutError, requests.RequestException)

# Input and response-parsing failures. hoppie_connector raises these bare, so
# without converting them a too-long telex or a proxy's HTML error page would
# escape every `except HoppieError` and vanish into the wx event loop.
PROTOCOL_ERRORS = (ValueError, TypeError)

_LOGON_PATTERN = re.compile(r"(logon=)[^&\s]+", re.IGNORECASE)
_SERVER_INFO_PATTERN = re.compile(r"^\{server info \{(.+)\}\}$", re.DOTALL)


def install_request_timeout(timeout=NETWORK_TIMEOUT):
    """Give requests a default timeout for callers that omit one.

    hoppie_connector calls requests.get/post with no timeout and offers no hook
    to supply one, so a server that accepts the connection and then goes silent
    would block the GUI thread forever. socket.setdefaulttimeout() does not help
    here: requests explicitly calls sock.settimeout(None) when no timeout is
    given, which overrides the global default.

    Args:
        timeout: Default timeout in seconds for calls that specify none
    """
    for name in ("get", "post"):
        original = getattr(requests, name)
        if getattr(original, "_default_timeout_applied", False):
            continue

        @functools.wraps(original)
        def wrapper(*args, _original=original, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return _original(*args, **kwargs)

        wrapper._default_timeout_applied = True
        setattr(requests, name, wrapper)


def redact(text):
    """Strip logon codes out of text destined for a log file or a dialog.

    requests embeds the full request URL in its exception messages, and that
    URL carries the logon code as a query parameter.

    Args:
        text: The text to scrub

    Returns:
        str: The text with any logon code replaced
    """
    return _LOGON_PATTERN.sub(r"\1<redacted>", str(text))


class ConnectionManager:
    """Manages network connections to the CPDLC service.

    Every call into hoppie_connector goes through _call(), which converts both
    transport failures (TRANSPORT_ERRORS) and input/response failures
    (PROTOCOL_ERRORS) into HoppieError. hoppie_connector raises the builtin
    ConnectionError for a non-OK HTTP status, requests raises its own errors
    for timeouts and DNS failures, and the message and response parsers raise
    bare ValueError/TypeError. None of those is a HoppieError, so without this
    they would escape the `except HoppieError` in every caller and disappear
    into the wx event loop, leaving a request silently doing nothing at all.

    Transport failures are also counted -- polls into connection_failures and
    sends into send_failures -- so a link that is dead for sends but alive for
    polls still reaches the reconnection logic instead of being reset by the
    next successful poll.
    """

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
        # Send failures are tracked separately: a successful poll must not
        # clear them, or a link that passes GETs but blocks POSTs would never
        # accumulate enough failures to trigger a reconnection.
        self.send_failures = 0
        self.max_connection_failures = MAX_CONNECTION_FAILURES
        self.message_callback = message_callback

    def _call(self, operation, is_send=False):
        """Run a hoppie_connector call, normalising its failure modes.

        Args:
            operation: A zero-argument callable performing the request
            is_send: True for outbound message sends, which count towards
                send_failures rather than connection_failures

        Returns:
            Whatever the operation returns

        Raises:
            HoppieError: For transport, protocol and validation failures
        """
        try:
            result = operation()
        except TRANSPORT_ERRORS as exc:
            raise self._transport_failure(exc, is_send) from exc
        except PROTOCOL_ERRORS as exc:
            # Not a link problem: a too-long telex or a bad callsign fails here
            # and must not push the client towards a reconnection.
            error = HoppieError(redact(exc))
            error.is_transport = False
            raise error from exc

        if is_send:
            self.send_failures = 0
        return result

    def _transport_failure(self, exc, is_send=False):
        """Count a transport failure and build the HoppieError for it.

        Args:
            exc: The original transport exception
            is_send: True if the failure was on an outbound send

        Returns:
            HoppieError: The error to raise, tagged as a transport failure
        """
        if is_send:
            self.send_failures += 1
            count = self.send_failures
            kind = "Send failure"
        else:
            self.connection_failures += 1
            count = self.connection_failures
            kind = "Connection failure"
        self.logger.warning(f"{kind} count: {count}/{self.max_connection_failures}")
        error = HoppieError(redact(exc))
        error.is_transport = True
        return error

    def _api_url(self, network_type=None):
        """Return the API URL for a network type.

        Args:
            network_type: Network type, or None to use the stored one

        Returns:
            str: The API URL to use
        """
        if network_type is None:
            network_type = self.network_type
        return HOPPIE_API_URL if network_type == "hoppie" else SAYINTENTIONS_API_URL

    def is_connected(self):
        """Check if currently connected to the network."""
        return self.cnx is not None

    def _open(self, callsign, logon_code, network_type):
        """Build a connector and verify it can reach the server.

        HoppieConnector's constructor performs no I/O, so it alone proves
        nothing. ping() is documented as a connection check, and it also
        validates the callsign and logon code against the server.

        Args:
            callsign: Aircraft callsign
            logon_code: CPDLC logon code
            network_type: Network type ("sayintentions" or "hoppie")

        Returns:
            HoppieConnector: A verified connector

        Raises:
            HoppieError: If the connection could not be established
        """
        api_url = self._api_url(network_type)
        cnx = self._call(lambda: HoppieConnector(callsign, logon_code, url=api_url))
        self._call(cnx.ping)
        return cnx

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

        try:
            self.cnx = self._open(callsign, logon_code, network_type)
        except HoppieError:
            self.cnx = None
            raise

        self.callsign = callsign
        self.logon_code = logon_code
        self.network_type = network_type
        self.connection_failures = 0
        self.send_failures = 0
        self.logger.info(
            f"Successfully connected as {callsign} to {network_type} network"
        )

    def disconnect(self):
        """Disconnect from the CPDLC network."""
        if not self.cnx:
            return

        self.logger.info("Disconnecting from CPDLC network")
        # Mirror connect(): clear every field it set, so a later reconnection
        # cannot resurrect the previous session's callsign or logon code.
        self.cnx = None
        self.callsign = ""
        self.logon_code = ""
        self.network_type = None
        self.connection_failures = 0
        self.send_failures = 0
        self.logger.info("Successfully disconnected")

    def poll(self):
        """Poll for new messages from the network.

        Returns:
            tuple: (messages, poll_status) on success, where messages may be an
                empty list. (None, None) if not connected or if the poll
                failed; poll_failed() distinguishes the two.
        """
        if not self.cnx:
            return None, None

        try:
            self.logger.debug("Polling for new messages")
            messages, poll_status = self._call(self.cnx.poll)

            # Reset connection failures counter on successful poll
            if self.connection_failures > 0:
                self.logger.debug(
                    f"Resetting connection failures from {self.connection_failures} to 0"
                )
            self.connection_failures = 0

            return messages, poll_status
        except Exception as exc:
            # Deliberately broad: anything that escapes here would otherwise
            # skip the counter entirely and disable reconnection for good.
            self.logger.error(f"Poll error: {redact(exc)}")
            if not getattr(exc, "is_transport", False):
                # _call already counted transport failures. A poll carries no
                # user input, so any other failure — an unparseable body from a
                # captive portal, a server-side error — is equally a dead link.
                self.connection_failures += 1
                self.logger.warning(
                    f"Connection failure count: {self.connection_failures}/{self.max_connection_failures}"
                )
            return None, None

    def failure_count(self):
        """Return the worst of the poll and send failure counts."""
        return max(self.connection_failures, self.send_failures)

    def poll_failed(self):
        """Check whether the connection is currently in a failed state."""
        return self.failure_count() > 0

    def should_attempt_reconnection(self):
        """Check if reconnection should be attempted based on failure count."""
        return bool(
            self.cnx
            and self.failure_count() >= self.max_connection_failures
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
            self.cnx = self._open(self.callsign, self.logon_code, self.network_type)

            # Reset connection failures counter
            self.connection_failures = 0
            self.send_failures = 0
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

        self._call(
            lambda: self.cnx.send_cpdlc(
                recipient, min_value, response_type, message, mrn=mrn
            ),
            is_send=True,
        )

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

        self._call(lambda: self.cnx.send_telex(recipient, message), is_send=True)

    def _send_info_request(self, icao, packet, label):
        """Send an inforeq request via a direct HTTP GET.

        hoppie_connector does not support the inforeq message type, so this
        builds the request itself but routes the failure handling through
        _call() so the error contract matches every other outbound call.

        Args:
            icao: Airport ICAO code
            packet: Packet content (e.g. "metar EDDF")
            label: Human-readable request name for logs and errors

        Returns:
            str: The response text

        Raises:
            HoppieError: If not connected or the request fails
        """
        if not self.cnx:
            raise HoppieError("Not connected")

        api_url = self._api_url()
        params = {
            "logon": self.logon_code,
            "from": self.callsign,
            "to": "SERVER",
            "type": "inforeq",
            "packet": packet,
        }

        self.logger.info(f"Requesting {label} for {icao}")

        def _fetch():
            response = requests.get(api_url, params=params, timeout=NETWORK_TIMEOUT)
            response.raise_for_status()
            return response

        try:
            response = self._call(_fetch)
        except HoppieError as exc:
            self.logger.error(f"{label} request failed: {exc}")
            raise HoppieError(f"{label} request failed: {exc}") from exc

        body = response.text.strip()

        if body.startswith("ok "):
            text = body[3:].strip()
            # Response is wrapped as {server info {actual text}} — extract inner content
            match = _SERVER_INFO_PATTERN.match(text)
            if match:
                text = match.group(1).strip()
            self.logger.info(f"Received {label} for {icao}")
            return text
        elif body.startswith("error "):
            error_reason = body[6:].strip()
            self.logger.error(f"{label} request error: {error_reason}")
            raise HoppieError(f"{label} request error: {error_reason}")
        else:
            self.logger.error(f"Unexpected {label} response: {body}")
            raise HoppieError(f"Unexpected response: {body}")

    def send_info_request(self, info_type, icao):
        """Fetch a weather/information report via the Hoppie "inforeq" interface.

        Blocking — callers that run on a timer should invoke this from a
        worker thread.

        Args:
            info_type: Report type key (e.g. "metar", "taf", "vatatis")
            icao: Airport ICAO code

        Returns:
            str: The report text

        Raises:
            HoppieError: If not connected or the request fails
        """
        label = report_type_label(info_type)
        packet = f"{report_type_packet(info_type)} {icao}"

        report_text = self._send_info_request(icao, packet, label)
        if not report_text:
            # A station with nothing to report answers "ok" with an empty
            # envelope, which would otherwise surface as a blank message.
            self.logger.warning(f"Empty {label} response for {icao}")
            raise HoppieError(f"No {label} available for {icao}")

        return report_text

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
