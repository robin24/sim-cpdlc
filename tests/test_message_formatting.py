"""The CPDLC packet-to-text helpers the list and the detail pane rely on."""

import pytest
from hoppie_connector import CpdlcResponseRequirement as RR

from src.utils.message_formatting import (
    extract_message_content,
    format_list_text,
    format_message_text,
)


@pytest.mark.parametrize("rr", list(RR), ids=[rr.name for rr in RR])
def test_the_packet_prefix_is_stripped_with_and_without_an_mrn(rr):
    assert extract_message_content(f"/data2/12//{rr.value}/CLIMB TO FL350") == "CLIMB TO FL350"
    assert extract_message_content(f"/data2/12/3/{rr.value}/WILCO") == "WILCO"


@pytest.mark.parametrize("text", ["CLIMB TO FL350", "", None], ids=["plain", "empty", "none"])
def test_text_without_a_prefix_is_returned_unchanged(text):
    assert extract_message_content(text) == text


def test_the_detail_pane_puts_each_field_on_its_own_line():
    assert format_message_text("CONTACT CLEVELAND CENTER ON @123.450@.") == (
        "CONTACT CLEVELAND CENTER ON\n123.450."
    )
    assert format_message_text("CURRENT ATC UNIT@_@EDUU@_@RHEIN RADAR") == (
        "CURRENT ATC UNIT\nEDUU\nRHEIN RADAR"
    )


def test_the_list_row_carries_no_separators():
    row = format_list_text("CONTACT CLEVELAND CENTER ON @123.450@.")

    assert "@" not in row
    assert "123.450" in row
    assert format_list_text("CURRENT ATC UNIT@_@EDUU@_@RHEIN RADAR").split() == [
        "CURRENT", "ATC", "UNIT", "EDUU", "RHEIN", "RADAR",
    ]
