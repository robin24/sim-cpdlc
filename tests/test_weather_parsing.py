"""Tests for the weather report registry and its ATIS letter extraction.

The packet keyword is what goes on the wire, so it is asserted literally: a
mistyped keyword fails here rather than against a live ACARS server.
"""

from src.gui.dialogs.weather_dialog import REPORT_ORDER
from src.utils.weather_parsing import (
    ATIS_TYPES,
    REPORT_TYPES,
    report_type_label,
    report_type_packet,
)


def test_only_the_supported_networks_are_offered():
    """Sim-CPDLC talks to Hoppie and SayIntentions, so an IVAO or PilotEdge
    ATIS could never be answered."""
    assert set(REPORT_TYPES) == {"metar", "taf", "shorttaf", "vatatis"}


def test_the_dialog_offers_every_report_type():
    """REPORT_ORDER indexes the dialog's choice list, so a type missing from it
    is unreachable and a type missing from REPORT_TYPES would crash the lookup."""
    assert set(REPORT_ORDER) == set(REPORT_TYPES)


def test_only_the_plain_atis_carries_an_information_letter():
    assert ATIS_TYPES == ("vatatis",)


def test_each_type_keeps_its_wire_keyword():
    assert [report_type_packet(key) for key in REPORT_ORDER] == [
        "vatatis",
        "metar",
        "taf",
        "shorttaf",
    ]


def test_the_plain_atis_is_labelled_without_a_network():
    """Whichever network is connected answers a plain ATIS request with its
    own, so naming one in the label would be wrong half the time."""
    assert report_type_label("vatatis") == "ATIS"
