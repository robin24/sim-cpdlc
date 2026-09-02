"""Tests for the exact text of the downlinks the client can send.

The wire format is what a controller reads, so each message is asserted
literally rather than by shape: a reworded element shows up here instead of on
the network.
"""

import pytest

from conftest import FakeConnectionManager
from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER
from src.model.cpdlc_session import CpdlcSession

STATION = "EGGX"


@pytest.fixture
def make_session(logger):
    def build(connected=True, station=STATION):
        session = CpdlcSession(logger, FakeConnectionManager(connected=connected))
        session.set_callsign("BAW123")
        session.current_station = station
        return session

    return build


@pytest.fixture
def session(make_session):
    return make_session()


def last_frame(session):
    """The most recent frame handed to the connection, as (to, min, rr, text)."""
    recipient, min_value, rr, message, _mrn = session.connection_manager.sent[-1]
    return recipient, min_value, rr, message


# --- addressing and response requirements -------------------------------------


def test_a_heading_request_goes_to_the_current_station(session):
    ok, text = session.send_heading_request("270")
    recipient, _, rr, message = last_frame(session)

    assert (ok, text) == (True, "REQUEST HEADING 270")
    assert (recipient, message) == (STATION, "REQUEST HEADING 270")
    assert rr == "Y"


def test_a_confirm_query_asks_for_an_answer(session):
    """CONFIRM ASSIGNED ... is useless without a reply, so RR must not be NO."""
    session.send_query("CONFIRM ASSIGNED LEVEL")
    _, _, rr, message = last_frame(session)

    assert message == "CONFIRM ASSIGNED LEVEL"
    assert rr == "Y"


def test_each_message_advances_the_min_counter(session):
    """A reused MIN makes the station read the second message as the first."""
    session.send_heading_request("270")
    session.send_heading_request("280")

    assert [frame[1] for frame in session.connection_manager.sent] == [1, 2]


# --- preconditions ------------------------------------------------------------


def test_a_request_without_a_station_is_refused(make_session):
    session = make_session(station="")

    assert session.send_heading_request("270") == (False, None)


def test_a_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.send_heading_request("270") == (False, None)


# --- emergency ----------------------------------------------------------------


def test_a_mayday_carries_fuel_souls_and_the_diversion(session):
    _, text = session.send_emergency(
        True, "0230", "212", "BIKF", "DCT", "ENGINE FAILURE"
    )

    assert text == (
        "MAYDAY MAYDAY MAYDAY\n"
        "0230 OF FUEL REMAINING AND 212 SOULS ON BOARD\n"
        "DIVERTING TO BIKF VIA DCT\n"
        "ENGINE FAILURE"
    )


def test_a_pan_pan_with_no_details_carries_nothing_else(session):
    assert session.send_emergency(False)[1] == "PAN PAN PAN"


def test_cancelling_an_emergency_says_so_plainly(session):
    assert session.send_cancel_emergency()[1] == "CANCEL EMERGENCY"


# --- weather ------------------------------------------------------------------


def test_a_weather_request_returns_the_report(session):
    assert session.request_weather("metar", "EGLL") == (True, "EGLL REPORT FOR metar")


def test_a_weather_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.request_weather("metar", "EGLL") == (False, None)


# --- reason wording -----------------------------------------------------------


def test_a_performance_reason_uses_the_full_standard_wording(session):
    """DM66 is "DUE TO AIRCRAFT PERFORMANCE". Each dialog used to spell the
    value out for itself, so the short "PERFORMANCE" had spread to all of them.
    """
    _, text = session.send_altitude_change_request(
        "FL350", REASON_AIRCRAFT_PERFORMANCE
    )

    assert text == "REQUEST FL350 DUE TO AIRCRAFT PERFORMANCE"


def test_a_weather_reason_is_unchanged(session):
    _, text = session.send_direct_request("MALOT", REASON_WEATHER)

    assert text == "REQUEST DIRECT TO MALOT DUE TO WEATHER"
