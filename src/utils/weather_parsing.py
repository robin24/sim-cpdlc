"""Helpers for comparing weather reports and detecting new issues."""

import re

# Report kinds understood by the Hoppie "inforeq" interface. The key is the
# value stored in a subscription; the packet prefix is what goes on the wire.
REPORT_TYPES = {
    "metar": ("METAR", "metar"),
    "taf": ("TAF", "taf"),
    "shorttaf": ("Short TAF", "shorttaf"),
    # The "vatatis" packet is what every supported network answers a plain
    # ATIS request with: Hoppie serves the VATSIM ATIS, SayIntentions serves
    # its own. Label it plainly, since the source follows whichever network
    # you are using.
    "vatatis": ("ATIS", "vatatis"),
}

# Report kinds that carry an information letter we can compare instead of
# diffing the whole text.
ATIS_TYPES = ("vatatis",)

_WHITESPACE = re.compile(r"\s+")
_NON_REPORT_CHARS = re.compile(r"[^A-Z0-9 ]")

# Words that introduce the ATIS information letter rather than being it.
_LETTER_MARKERS = frozenset({"INFORMATION", "INFO", "ATIS"})

_NATO_ALPHABET = {
    "ALFA": "A",
    "ALPHA": "A",
    "BRAVO": "B",
    "CHARLIE": "C",
    "DELTA": "D",
    "ECHO": "E",
    "FOXTROT": "F",
    "GOLF": "G",
    "HOTEL": "H",
    "INDIA": "I",
    "JULIETT": "J",
    "JULIET": "J",
    "KILO": "K",
    "LIMA": "L",
    "MIKE": "M",
    "NOVEMBER": "N",
    "OSCAR": "O",
    "PAPA": "P",
    "QUEBEC": "Q",
    "ROMEO": "R",
    "SIERRA": "S",
    "TANGO": "T",
    "UNIFORM": "U",
    "VICTOR": "V",
    "WHISKEY": "W",
    "WHISKY": "W",
    "XRAY": "X",
    "YANKEE": "Y",
    "ZULU": "Z",
}


def report_type_label(info_type):
    """Return the human-readable name for a report type key."""
    entry = REPORT_TYPES.get(info_type)
    return entry[0] if entry else info_type.upper()


def report_type_packet(info_type):
    """Return the Hoppie inforeq packet keyword for a report type key."""
    entry = REPORT_TYPES.get(info_type)
    return entry[1] if entry else info_type


def is_atis_type(info_type):
    """Check whether a report type carries an information letter."""
    return info_type in ATIS_TYPES


def normalize_report(text):
    """Collapse whitespace and case so cosmetic differences don't read as new.

    Args:
        text: The raw report text.

    Returns:
        str: A normalized form suitable for equality comparison.
    """
    if not text or not isinstance(text, str):
        return ""
    return _WHITESPACE.sub(" ", text.replace("@", " ").upper()).strip()


def _report_lines(text):
    """Split a report on its separators, dropping empties.

    Args:
        text: The raw report text.

    Returns:
        list: The non-empty lines, each stripped.
    """
    if not text or not isinstance(text, str):
        return []
    return [line.strip() for line in text.split("@") if line.strip()]


def format_report_text(text):
    """Lay a report out over lines for the detail view.

    Hoppie separates the lines of an information report with "@", which a
    screen reader announces as the word "at" if it is left in place. This is
    deliberately not message_formatting.format_message_text: that helper maps
    "@@" to the literal string "N/A" and strips underscores, which are CPDLC
    packet conventions and would corrupt a weather report.

    Args:
        text: The raw report text.

    Returns:
        str: The report with separators turned into line breaks.
    """
    return "\n".join(_report_lines(text))


def format_report_line(text):
    """Flatten a report to one line for the message list.

    Args:
        text: The raw report text.

    Returns:
        str: The report on a single line, with whitespace collapsed.
    """
    return " ".join(" ".join(_report_lines(text)).split())


def extract_atis_letter(text, icao=None):
    """Pull the information letter out of an ATIS report.

    Handles both "INFORMATION K" and "INFORMATION KILO". The airport code is
    deliberately not treated as a marker: a US D-ATIS announces itself as
    "KSFO D ATIS ..." and the designator would be read as the letter, pinning
    the signature to a value that never changes. Returns an empty string when
    no letter is found, which lets the caller fall back to comparing the full
    text.

    Args:
        text: The raw ATIS text.
        icao: Accepted for call-site compatibility and ignored.

    Returns:
        str: A single uppercase letter, or "" if none could be identified.
    """
    if not text or not isinstance(text, str):
        return ""

    words = _NON_REPORT_CHARS.sub(" ", text.upper()).split()
    markers = _LETTER_MARKERS

    for index in range(len(words) - 1):
        if words[index] not in markers:
            continue

        candidate = words[index + 1]
        # "EGLL ATIS INFORMATION K" — step over chained markers.
        if candidate in markers:
            continue
        if len(candidate) == 1 and candidate.isalpha():
            return candidate
        if candidate in _NATO_ALPHABET:
            return _NATO_ALPHABET[candidate]

    return ""


def report_signature(text, info_type, icao=None):
    """Build the value used to decide whether a report has actually changed.

    ATIS reports are compared by information letter so that a re-worded but
    otherwise identical broadcast doesn't announce itself as new. Everything
    else is compared on its normalized text, so a SPECI or an amended TAF is
    correctly treated as a new report.

    Args:
        text: The raw report text.
        info_type: The report type key (e.g. "metar", "vatatis").
        icao: Optional airport ICAO code.

    Returns:
        str: An opaque signature string.
    """
    if is_atis_type(info_type):
        letter = extract_atis_letter(text, icao)
        if letter:
            return f"INFO:{letter}"
    return normalize_report(text)


def describe_report(text, info_type, icao=None):
    """Build a short description of a report for status/announcement text.

    Args:
        text: The raw report text.
        info_type: The report type key.
        icao: Optional airport ICAO code.

    Returns:
        str: e.g. "ATIS (VATSIM) EGLL information K" or "METAR EGLL".
    """
    label = report_type_label(info_type)
    station = f" {icao.upper()}" if icao else ""

    if is_atis_type(info_type):
        letter = extract_atis_letter(text, icao)
        if letter:
            return f"{label}{station} information {letter}"

    return f"{label}{station}"
