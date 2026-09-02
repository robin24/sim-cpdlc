"""Message management for the CPDLC client."""

from typing import List, Tuple, Set, Optional, Any

from hoppie_connector import (
    CpdlcMessage,
    CpdlcResponseRequirement as RR,
    HoppieMessage,
)

from src.utils.message_formatting import (
    extract_message_content,
    format_list_text,
    format_message_text,
)
from src.utils.weather_parsing import report_type_label


class WeatherReport:
    """A weather report in the message log, tagged with what it reports on.

    Storing the airport and report type alongside the text lets the message
    list offer to start or stop automatic updates for the report the user has
    selected, rather than making them re-enter it somewhere else.
    """

    def __init__(self, text: str, icao: str, info_type: str):
        """Initialize the weather report record.

        Args:
            text: The report text as received
            icao: Airport ICAO code
            info_type: Report type key (e.g. "metar", "vatatis")
        """
        self.text = text
        self.icao = icao.upper()
        self.info_type = info_type

    @property
    def label(self) -> str:
        """Return the display name of the report type."""
        return report_type_label(self.info_type)

    @property
    def key(self) -> Tuple[str, str]:
        """Return the (icao, info_type) pair identifying this report."""
        return (self.icao, self.info_type)

# The responses a pilot may send for each response requirement, in the order
# they are offered in the context menu. Requirements that need no reply
# (RR.NO, RR.NOT_REQUIRED) are absent by design.
RESPONSES_BY_REQUIREMENT = {
    RR.WILCO_UNABLE: ["WILCO", "UNABLE", "STANDBY"],
    RR.AFFIRM_NEGATIVE: ["AFFIRM", "NEGATIVE", "STANDBY"],
    RR.ROGER: ["ROGER", "STANDBY"],
    RR.YES: ["YES", "NO"],
}

# Every response string the client can send, derived from the table above so
# the two cannot drift. The polling controller imports this rather than
# keeping its own copy.
CPDLC_RESPONSES = frozenset(
    response
    for responses in RESPONSES_BY_REQUIREMENT.values()
    for response in responses
)

# Responses that do NOT answer a message for good. STANDBY tells the controller
# to wait; the pilot must still follow it with WILCO/UNABLE, so it must not
# retire the response options.
NON_TERMINAL_RESPONSES = frozenset({"STANDBY"})


class MessageManager:
    """Manages CPDLC messages and their state."""

    def __init__(self, logger):
        """Initialize the message manager.

        Args:
            logger: Application logger
        """
        self.logger = logger
        self.message_id_counter = 0
        self.message_log = {}  # Maps message_id to message object
        # IDs of messages that have been answered for good. This is not "every
        # message a response was sent for": STANDBY is transmitted but stays
        # out of this set, so the message remains answerable.
        #
        # Keyed on the ID this class assigns, not on (sender, MIN): MIN is the
        # sending station's own counter, which restarts whenever that station
        # re-logs on, so the same pair recurs within a single flight and would
        # suppress the response options for a later, unrelated message.
        self.acknowledged_messages: Set[int] = set()

    def add_message(self, message: HoppieMessage) -> int:
        """Add a HoppieMessage to the message log.

        Args:
            message: The HoppieMessage to add

        Returns:
            int: The assigned message ID, or -1 if invalid message
        """
        if not isinstance(message, HoppieMessage):
            self.logger.warning("Attempted to add non-HoppieMessage object")
            return -1

        message_id = self.message_id_counter
        self.message_id_counter += 1
        self.message_log[message_id] = message

        # Get and clean the raw content for logging
        raw_content = message.get_packet_content()
        clean_content = extract_message_content(raw_content)
        self.logger.debug(
            f"Added message from {message.get_from_name()}: {clean_content}"
        )

        return message_id

    def add_custom_message(self, text: str, sender: str = None) -> int:
        """Add a custom message to the message log.

        Args:
            text: The message text
            sender: The sender name (optional)

        Returns:
            int: The assigned message ID
        """
        message_id = self.message_id_counter
        self.message_id_counter += 1

        # Store as a simple string
        message_text = f"{sender}: {text}" if sender else text
        self.message_log[message_id] = message_text

        self.logger.debug(f"Added custom message: {message_text}")
        return message_id

    def add_weather_message(self, text: str, icao: str, info_type: str) -> int:
        """Add a weather report to the message log.

        Args:
            text: The report text
            icao: Airport ICAO code
            info_type: Report type key

        Returns:
            int: The assigned message ID
        """
        message_id = self.message_id_counter
        self.message_id_counter += 1
        self.message_log[message_id] = WeatherReport(text, icao, info_type)

        self.logger.debug(f"Added {info_type} report for {icao.upper()}")
        return message_id

    def get_weather_key(self, message_id: int) -> Optional[Tuple[str, str]]:
        """Get the (icao, info_type) pair for a weather report.

        Args:
            message_id: The message ID

        Returns:
            tuple: The report key, or None if this is not a weather report
        """
        message = self.message_log.get(message_id)
        return message.key if isinstance(message, WeatherReport) else None

    def get_message(self, message_id: int) -> Optional[Any]:
        """Get a message by ID.

        Args:
            message_id: The message ID

        Returns:
            The message object or None if not found
        """
        return self.message_log.get(message_id)

    def get_cpdlc_addressing(self, message_id: int) -> Optional[Tuple[str, int]]:
        """Get the sender and MIN needed to address a reply to a message.

        Saves the caller from reaching into CpdlcMessage itself, and gives it a
        single check for "this ID cannot be replied to".

        Args:
            message_id: The message ID

        Returns:
            tuple: (sender, min_value), or None if the ID does not name a CPDLC
                message
        """
        message = self.message_log.get(message_id)
        if not isinstance(message, CpdlcMessage):
            return None

        return message.get_from_name(), message.get_min()

    def get_message_display_text(self, message_id: int) -> Tuple[str, str]:
        """Get formatted display text for a message.

        Args:
            message_id: The message ID

        Returns:
            tuple: (sender, display_text) or ("", "") if not found
        """
        message = self.message_log.get(message_id)
        if not message:
            return "", ""

        if isinstance(message, WeatherReport):
            return message.label, f"{message.icao}: {' '.join(message.text.split())}"
        elif isinstance(message, HoppieMessage):
            # For HoppieMessage objects
            sender = message.get_from_name()
            raw_content = message.get_packet_content()
            clean_content = extract_message_content(raw_content)
            display_text = format_list_text(clean_content)
            return sender, display_text
        elif isinstance(message, str):
            # For custom messages
            if ": " in message:
                sender, text = message.split(": ", 1)
                # Multi-line messages (oceanic requests, position reports) get
                # flattened here; the detail view keeps the line breaks.
                return sender, " ".join(text.split())
            else:
                return "SYSTEM", " ".join(message.split())
        else:
            return "", ""

    def get_message_detail_text(self, message_id: int) -> str:
        """Get detailed text for a message.

        Args:
            message_id: The message ID

        Returns:
            str: Formatted message text for detailed view
        """
        message = self.message_log.get(message_id)
        if not message:
            return ""

        if isinstance(message, WeatherReport):
            return f"{message.label} {message.icao}\n\n{message.text}"
        elif isinstance(message, HoppieMessage):
            # For HoppieMessage objects
            raw_content = message.get_packet_content()
            clean_content = extract_message_content(raw_content)
            return format_message_text(clean_content)
        elif isinstance(message, str):
            # For custom messages
            if ": " in message:
                _, text = message.split(": ", 1)
                return text
            else:
                return message
        else:
            return ""

    def mark_acknowledged(self, message_id: int, response: str):
        """Record the response that was sent for a message.

        Non-terminal responses are transmitted but leave the message
        answerable, so they are not recorded here.

        Args:
            message_id: The ID of the CPDLC message that was responded to
            response: The response text that was sent
        """
        if response.strip().upper() in NON_TERMINAL_RESPONSES:
            self.logger.debug(
                f"Response {response} does not retire message ID={message_id}"
            )
            return

        self.acknowledged_messages.add(message_id)
        self.logger.debug(f"Marked message as acknowledged: ID={message_id}")

    def needs_acknowledgement(
        self, message_id: int, current_station: str
    ) -> Tuple[bool, List[str]]:
        """Check if a message needs acknowledgement and get valid responses.

        Args:
            message_id: The ID of the message to check
            current_station: The station currently logged on. Messages from any
                other station are no longer part of the live dialogue and
                cannot be answered.

        Returns:
            tuple: (needs_ack, responses)
        """
        message = self.message_log.get(message_id)

        if isinstance(message, CpdlcMessage):
            sender = message.get_from_name()
            if sender != current_station:
                self.logger.debug(
                    f"Message ID={message_id} is from {sender}, not the current "
                    f"station {current_station or '(none)'}; not answerable."
                )
                return False, []

            # Check if this message has already been acknowledged
            if message_id not in self.acknowledged_messages:
                responses = self._get_cpdlc_responses(message)
                if responses:
                    self.logger.debug("Message needs acknowledgement.")
                    return True, responses

        self.logger.debug("Message does not need acknowledgement.")
        return False, []

    def _get_cpdlc_responses(self, message: CpdlcMessage) -> List[str]:
        """Get valid response options for a CPDLC message.

        Args:
            message: The CPDLC message

        Returns:
            list: Valid response strings, empty if the message needs no reply
        """
        responses = RESPONSES_BY_REQUIREMENT.get(message.get_rr())
        if not responses:
            self.logger.debug("No responses needed.")
            return []

        self.logger.debug(f"Valid responses: {responses}")
        return list(responses)
