"""Tests for the weather report registry and its ATIS letter extraction.

The packet keyword is what goes on the wire, so it is asserted literally: a
mistyped keyword fails here rather than against a live ACARS server.
"""

from src.gui.dialogs.weather_dialog import REPORT_ORDER
from src.utils.weather_parsing import (
    ATIS_TYPES,
    REPORT_TYPES,
    extract_atis_letter,
    format_report_line,
    format_report_text,
    report_signature,
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


# --- ATIS information letter ---------------------------------------------------


def test_the_letter_is_read_from_the_information_marker():
    assert extract_atis_letter("EGLL ATIS INFORMATION K RWY 27R", "EGLL") == "K"


def test_a_spelled_out_letter_is_understood():
    assert extract_atis_letter("EGLL ATIS INFO KILO RWY 27R", "EGLL") == "K"


def test_a_datis_designator_is_not_mistaken_for_the_letter():
    """A US D-ATIS names itself "KSFO D ATIS" before giving the letter. Reading
    the D as the letter pins the signature to a value that never changes, so
    the report would silently stop announcing for the rest of the flight."""
    assert extract_atis_letter("KSFO D ATIS INFO Q 1156Z 28010KT", "KSFO") == "Q"


def test_a_datis_that_advances_reads_as_a_change():
    first = report_signature("KSFO D ATIS INFO Q 1156Z 28010KT", "vatatis", "KSFO")
    second = report_signature("KSFO D ATIS INFO R 1256Z 28012KT", "vatatis", "KSFO")

    assert (first, second) == ("INFO:Q", "INFO:R")


def test_an_unreadable_letter_falls_back_to_the_whole_report():
    """Better to compare the full text than to guess at a letter."""
    assert extract_atis_letter("FRANKFURT ARRIVAL RWY 25L", "EDDF") == ""


# --- report formatting ---------------------------------------------------------

ATIS_WITH_SEPARATORS = "EGLL ATIS INFO K AT 1150Z@RWY IN USE 27R@TRL 60@@WIND 240/10"


def test_the_detail_view_turns_separators_into_line_breaks():
    assert format_report_text(ATIS_WITH_SEPARATORS) == (
        "EGLL ATIS INFO K AT 1150Z\n"
        "RWY IN USE 27R\n"
        "TRL 60\n"
        "WIND 240/10"
    )


def test_the_list_row_is_a_single_line():
    assert format_report_line(ATIS_WITH_SEPARATORS) == (
        "EGLL ATIS INFO K AT 1150Z RWY IN USE 27R TRL 60 WIND 240/10"
    )


def test_a_report_with_no_separators_is_left_alone():
    metar = "EGLL 261150Z 24010KT 9999 FEW035 18/11 Q1013"

    assert format_report_text(metar) == metar
    assert format_report_line(metar) == metar


def test_formatting_survives_an_empty_report():
    assert format_report_text("") == ""
    assert format_report_line(None) == ""
