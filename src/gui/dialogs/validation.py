"""Input rules shared by the request dialogs.

Every rule is ASCII-only: str.isdigit() and a bare \\d accept digits from other
scripts, and int() accepts "3_50" and "+350", all of which hoppie_connector
rejects at send time with a message the pilot cannot act on. Matching here
makes the OK button the only gate, and the getters return the very text that
was matched.
"""

import re

# A CPDLC station: four letters or digits.
STATION = r"[A-Z0-9]{4}"
# A flight level typed without the FL prefix; two digits are zero-padded.
FLIGHT_LEVEL = r"\d{2,3}"
# A Mach number typed without the decimal point; two digits are zero-padded.
MACH = r"\d{2,3}"
# An indicated airspeed in knots.
KNOTS = r"\d{3}"
# A fix, waypoint or navaid, including lat/long forms such as 55N020W.
FIX = r"[A-Z0-9]{2,7}"


def matches(rule, text):
    """Return True when text is ASCII and matches the rule in full."""
    return text.isascii() and re.fullmatch(rule, text, re.ASCII) is not None


def pad_three(text):
    """Zero-pad a validated number to three digits (50 -> 050)."""
    return text.zfill(3)
