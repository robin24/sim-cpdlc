"""Message management for the CPDLC client."""

from typing import Dict, List, Tuple, Set, Optional, Any, Callable
import logging

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
        self.acknowledged_messages = set()  # Set of (sender, message_id) tuples

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

    def get_message(self, message_id: int) -> Optional[Any]:
        """Get a message by ID.

        Args:
            message_id: The message ID

        Returns:
            The message object or None if not found
        """
        return self.message_log.get(message_id)

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

        if isinstance(message, HoppieMessage):
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
                return sender, text
            else:
                return "SYSTEM", message
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

        if isinstance(message, HoppieMessage):
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

    def mark_acknowledged(self, message: CpdlcMessage):
        """Mark a message as acknowledged.

        Args:
            message: The CPDLC message that was acknowledged
        """
        if not isinstance(message, CpdlcMessage):
            return

        sender = message.get_from_name()
        min_value = message.get_min()
        message_key = (sender, min_value)
        self.acknowledged_messages.add(message_key)
        self.logger.debug(f"Marked message as acknowledged: {message_key}")

    def needs_acknowledgement(self, message: HoppieMessage) -> Tuple[bool, List[str]]:
        """Check if a message needs acknowledgement and get valid responses.

        Args:
            message: The message to check

        Returns:
            tuple: (needs_ack, responses)
        """
        if isinstance(message, CpdlcMessage):
            # Create a message identifier tuple
            message_key = (message.get_from_name(), message.get_min())

            # Check if this message has already been acknowledged
            if message_key not in self.acknowledged_messages:
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
            list: Valid response strings
        """
        responses = []
        rr = message.get_rr()
        if rr == RR.W_U:
            responses.append("WILCO")
            responses.append("UNABLE")
        elif rr == RR.A_N:
            responses.append("AFFIRM")
            responses.append("NEGATIVE")
        elif rr == RR.R:
            responses.append("ROGER")
        elif rr == RR.YES:
            responses.append("YES")
        elif rr == RR.NO:
            responses.append("NO")
        else:
            self.logger.debug("No responses needed.")
            return []

        self.logger.debug(f"Valid responses: {responses}")
        return responses
