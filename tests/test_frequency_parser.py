"""What extract_contact_frequency tunes, on the texts the networks send.

Texts are given as the window sees them: after "@" separators have been
turned into spaces and whitespace collapsed.
"""

import pytest

from src.utils.frequency_parser import extract_contact_frequency

CASES = [
    ("CONTACT MAASTRICHT 132.850", 132.85),
    ("CONTACT MARSEILLE CONTROL ON 133.325 .", 133.325),
    ("CONTACT MAASTRICHT ON 132.855 MHZ", 132.855),
    ("MONITOR UNICOM 122.8", 122.8),
    ("AT KONOL CONTACT LONDON CONTROL 127.425", 127.425),
    ("CONTACT MAASTRICHT 132.850 OR 121.500", 132.85),
    ("CONTACT EDDF_TWR 118.700", 118.7),
    ("CONTACT MAASTRICHT\n132.850", 132.85),
    ("CONTACT LOWER LIMIT 118.000", 118.0),
    ("CONTACT UPPER LIMIT 136.990", 136.99),
    ("CLIMB TO FL350 REPORT LEVEL", None),
    ("CONTACT RHEIN RADAR 136.995", None),
    ("CONTACT LANGEN RADAR 117.950", None),
    ("CONTACT UPPER LIMIT 137.000", None),
]


@pytest.mark.parametrize("text, expected", CASES, ids=[case[0][:32] for case in CASES])
def test_the_frequency_read_from_a_contact_or_monitor_instruction(text, expected):
    assert extract_contact_frequency(text) == expected
