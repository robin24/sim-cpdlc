"""Tests for the exact text of the downlinks the client can send.

The wire format is what a controller reads, so each message is asserted
literally rather than by shape: a reworded element shows up here instead of on
the network.
"""

import pytest
from hoppie_connector import HoppieError

from tests.support import FakeConnectionManager
from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER
from src.model.cpdlc_session import CpdlcSession

STATION = "EGGX"


@pytest.fixture
def make_session(logger):
    def build(connected=True, station=STATION):
        session = CpdlcSession(logger, FakeConnectionManager(connected=connected))
        session.begin_session("BAW123", "hoppie")
        session.current_station = station
        return session

    return build


@pytest.fixture
def session(make_session):
    return make_session()


# --- addressing and preconditions ---------------------------------------------


def test_each_message_advances_the_min_counter(session):
    """A reused MIN makes the station read the second message as the first."""
    session.send_altitude_change_request("FL350")
    session.send_altitude_change_request("FL370")

    assert [frame[1] for frame in session.connection_manager.sent] == [1, 2]


def test_a_request_without_a_station_is_refused(make_session):
    session = make_session(station="")

    assert session.send_altitude_change_request("FL350") == (False, None)


def test_a_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.send_altitude_change_request("FL350") == (False, None)


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


# --- the remaining downlinks --------------------------------------------------


def test_a_logon_request_uses_min_one_and_expects_an_answer(make_session):
    session = make_session(station="")

    assert session.logon("EGGX") == (True, "REQUEST LOGON")
    assert session.connection_manager.sent == [("EGGX", 1, "Y", "REQUEST LOGON", None)]
    assert (session.pending_logon_station, session.pending_logon_min) == ("EGGX", 1)


def test_a_logoff_needs_no_response_and_clears_the_station(session):
    assert session.logoff() == (True, "LOGOFF")
    assert session.connection_manager.sent == [(STATION, 1, "NE", "LOGOFF", None)]
    assert session.get_current_station() == ""


@pytest.mark.parametrize(
    "speed, is_mach, reason, expected",
    [
        ("082", True, None, "REQUEST M082"),
        ("300", False, None, "REQUEST 300K"),
        ("078", True, REASON_WEATHER, "REQUEST M078 DUE TO WEATHER"),
    ],
    ids=["mach", "knots", "mach-with-reason"],
)
def test_a_speed_request_names_mach_or_knots(session, speed, is_mach, reason, expected):
    assert session.send_speed_request(speed, is_mach, reason) == (True, expected)


def test_a_when_can_we_expect_inquiry_is_sent_verbatim(session):
    text = "WHEN CAN WE EXPECT HIGHER LEVEL"

    assert session.send_when_can_we_expect(text) == (True, text)


def test_every_request_goes_to_the_current_station_expecting_an_answer(session):
    session.send_altitude_change_request("FL350")
    session.send_direct_request("MALOT")
    session.send_speed_request("082", True)
    session.send_when_can_we_expect("WHEN CAN WE EXPECT LOWER LEVEL")

    frames = session.connection_manager.sent
    assert [frame[0] for frame in frames] == [STATION] * 4
    assert [frame[2] for frame in frames] == ["Y"] * 4
    assert [frame[1] for frame in frames] == [1, 2, 3, 4]


def test_a_telex_goes_to_its_recipient_unchanged(session):
    assert session.send_telex("EDDF", "HELLO THERE") == (True, "HELLO THERE")
    assert session.connection_manager.telexes == [("EDDF", "HELLO THERE")]


def test_a_pdc_request_is_a_telex_to_the_departure_airport(session):
    ok, text = session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K")

    assert ok is True
    assert text == "REQUEST PREDEP CLEARANCE BAW123 A339 TO LIMC AT EGLL STAND 521 ATIS K"
    assert session.connection_manager.telexes == [("EGLL", text)]


def test_a_pdc_request_needs_a_callsign(make_session):
    session = make_session()
    session.callsign = ""

    assert session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K") == (False, None)


# --- failure paths ------------------------------------------------------------

SENDS = [
    # (name, station logged on before the send, the send)
    ("logon", "", lambda s: s.logon("EGGX")),
    ("logoff", STATION, lambda s: s.logoff()),
    ("altitude", STATION, lambda s: s.send_altitude_change_request("FL350")),
    ("direct", STATION, lambda s: s.send_direct_request("MALOT")),
    ("speed", STATION, lambda s: s.send_speed_request("082", True)),
    ("when-can-we", STATION, lambda s: s.send_when_can_we_expect("WHEN CAN WE EXPECT HIGHER LEVEL")),
    ("acknowledgement", STATION, lambda s: s.send_acknowledgement(STATION, 7, "WILCO")),
    ("telex", STATION, lambda s: s.send_telex("EDDF", "HELLO")),
    ("pdc", STATION, lambda s: s.send_pdc_request("EGLL", "LIMC", "A339", "521", "K")),
]


@pytest.mark.parametrize(
    "station, send", [case[1:] for case in SENDS], ids=[case[0] for case in SENDS]
)
def test_a_transmission_failure_is_reported_and_consumes_no_min(logger, station, send):
    """The error text reaches the dialog, and the MIN is not spent, so the
    next successful send does not leave a gap the station has to explain."""
    session = CpdlcSession(logger, FakeConnectionManager(raise_with=HoppieError("boom")))
    session.begin_session("BAW123", "hoppie")
    session.current_station = station

    assert send(session) == (False, "boom")
    assert session.cpdlc_min_counter == 1
