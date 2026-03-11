"""Extract VHF frequencies from CPDLC CONTACT/MONITOR messages."""

import re
from typing import Optional

# Match CONTACT or MONITOR, followed by unit name(s), optional ON, then frequency
_FREQ_PATTERN = re.compile(
    r"(?:CONTACT|MONITOR)\s+"  # CONTACT or MONITOR keyword
    r".+?\s+"  # Unit name (one or more words, non-greedy)
    r"(?:ON\s+)?"  # Optional ON keyword
    r"(\d{3}\.\d{1,3})"  # Frequency: 3 digits, dot, 1-3 digits
    r"(?:\s*MHZ)?",  # Optional MHZ suffix
    re.IGNORECASE | re.DOTALL,  # DOTALL so \s+ matches newlines
)


def extract_contact_frequency(message_text: str) -> Optional[float]:
    """Extract a VHF COM frequency from a CPDLC CONTACT or MONITOR message.

    Args:
        message_text: The CPDLC message text to parse.

    Returns:
        Frequency in MHz as a float, or None if no valid frequency found.
    """
    match = _FREQ_PATTERN.search(message_text)
    if not match:
        return None

    freq = float(match.group(1))

    # Validate VHF COM range: 118.000 - 136.990 MHz
    if freq < 118.0 or freq > 136.990:
        return None

    return freq
