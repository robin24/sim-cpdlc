"""Tests for the exact text of the downlinks the client can send.

The wire format is what a controller reads, so each message is asserted
literally rather than by shape: a reworded element shows up here instead of on
the network. Sends are queued on the worker, so each test runs the worker
before looking at what went out.
"""

import pytest
from hoppie_connector import HoppieError

from tests.support import FakeConnectionManager, inline_worker
from src.model.cpdlc_elements import REASON_AIRCRAFT_PERFORMANCE, REASON_WEATHER
from src.model.cpdlc_session import CpdlcSession

STATION = "EGGX"


@pytest.fixture
def make_session(logger):
    def build(connected=True, station=STATION, connection=None):
        if connection is None:
            connection = FakeConnectionManager(connected=connected)
        session = CpdlcSession(logger, connection, worker=inline_worker(logger))
        session.begin_session("BAW123", "hoppie")
        session.current_station = station
        return session

    return build


@pytest.fixture
def session(make_session):
    return make_session()


def sent(session):
    """Run the worker and return the CPDLC frames that went out."""
    session.worker.run_pending()
    return session.connection_manager.sent


def outcomes_of(session, send):
    """Queue a send with a recording callback, run the worker, return (queued, outcomes)."""
    outcomes = []
    queued = send(lambda success, text: outcomes.append((success, text)))
    session.worker.run_pending()
    return queued, outcomes


# --- addressing and preconditions ---------------------------------------------


def test_each_message_advances_the_min_counter(session):
    """A reused MIN makes the station read the second message as the first."""
    session.send_altitude_change_request("FL350")
    session.send_altitude_change_request("FL370")

    assert [frame[1] for frame in sent(session)] == [1, 2]


def test_a_request_without_a_station_is_refused(make_session):
    session = make_session(station="")

    assert session.send_altitude_change_request("FL350") is False
    assert sent(session) == []


def test_a_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.send_altitude_change_request("FL350") is False


def test_a_send_is_queued_not_transmitted_at_once(session):
    """The GUI thread only queues the frame; the worker transmits it."""
    assert session.send_altitude_change_request("FL350") is True
    assert session.connection_manager.sent == []

    session.worker.run_pending()

    assert session.connection_manager.sent == [(STATION, 1, "Y", "REQUEST FL350", None)]


# --- weather ------------------------------------------------------------------


def test_a_weather_request_delivers_the_report_when_it_arrives(session):
    outcomes = []

    assert session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text))) is True
    assert outcomes == []

    session.worker.run_pending()

    assert outcomes == [(True, "EGLL REPORT FOR metar")]
    assert session.connection_manager.info_requests == [("metar", "EGLL")]


def test_a_weather_request_without_a_connection_is_refused(make_session):
    session = make_session(connected=False)

    assert session.request_weather("metar", "EGLL", lambda ok, text: None) is False


def test_a_failed_weather_request_reports_the_error(make_session):
    session = make_session(connection=FakeConnectionManager(raise_with=HoppieError("no data")))
    outcomes = []
    session.request_weather("metar", "EGLL", lambda ok, text: outcomes.append((ok, text)))

    session.worker.run_pending()

    assert outcomes == [(False, "no data")]


# --- reason wording -----------------------------------------------------------


def test_a_performance_reason_uses_the_full_standard_wording(session):
    """DM66 is "DUE TO AIRCRAFT PERFORMANCE". Each dialog used to spell the
    value out for itself, so the short "PERFORMANCE" had spread to all of them.
    """
    _, outcomes = outcomes_of(
        session,
        lambda done: session.send_altitude_change_request("FL350", REASON_AIRCRAFT_PERFORMANCE, done),
    )

    assert outcomes == [(True, "REQUEST FL350 DUE TO AIRCRAFT PERFORMANCE")]


def test_a_weather_reason_is_unchanged(session):
    _, outcomes = outcomes_of(
        session, lambda done: session.send_direct_request("MALOT", REASON_WEATHER, done)
    )

    assert outcomes == [(True, "REQUEST DIRECT TO MALOT DUE TO WEATHER")]


# --- the remaining downlinks --------------------------------------------------


def test_a_logon_request_uses_min_one_and_expects_an_answer(make_session):
    session = make_session(station="")

    queued, outcomes = outcomes_of(session, lambda done: session.logon("EGGX", done))

    assert (queued, outcomes) == (True, [(True, "REQUEST LOGON")])
    assert session.connection_manager.sent == [("EGGX", 1, "Y", "REQUEST LOGON", None)]
    assert (session.pending_logon_station, session.pending_logon_min) == ("EGGX", 1)


def test_a_logoff_needs_no_response_and_clears_the_station_at_once(session):
    assert session.logoff() is True
    assert session.get_current_station() == ""

    assert sent(session) == [(STATION, 1, "NE", "LOGOFF", None)]


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
    _, outcomes = outcomes_of(
        session, lambda done: session.send_speed_request(speed, is_mach, reason, done)
    )

    assert outcomes == [(True, expected)]


def test_a_when_can_we_expect_inquiry_is_sent_verbatim(session):
    text = "WHEN CAN WE EXPECT HIGHER LEVEL"

    _, outcomes = outcomes_of(session, lambda done: session.send_when_can_we_expect(text, done))

    assert outcomes == [(True, text)]


def test_every_request_goes_to_the_current_station_expecting_an_answer(session):
    session.send_altitude_change_request("FL350")
    session.send_direct_request("MALOT")
    session.send_speed_request("082", True)
    session.send_when_can_we_expect("WHEN CAN WE EXPECT LOWER LEVEL")

    frames = sent(session)
    assert [frame[0] for frame in frames] == [STATION] * 4
    assert [frame[2] for frame in frames] == ["Y"] * 4
    assert [frame[1] for frame in frames] == [1, 2, 3, 4]


def test_a_telex_goes_to_its_recipient_unchanged(session):
    _, outcomes = outcomes_of(session, lambda done: session.send_telex("EDDF", "HELLO THERE", done))

    assert outcomes == [(True, "HELLO THERE")]
    assert session.connection_manager.telexes == [("EDDF", "HELLO THERE")]


def test_a_pdc_request_is_a_telex_to_the_departure_airport(session):
    _, outcomes = outcomes_of(
        session, lambda done: session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K", done)
    )

    text = "REQUEST PREDEP CLEARANCE BAW123 A339 TO LIMC AT EGLL STAND 521 ATIS K"
    assert outcomes == [(True, text)]
    assert session.connection_manager.telexes == [("EGLL", text)]


def test_a_pdc_request_needs_a_callsign(make_session):
    session = make_session()
    session.callsign = ""

    assert session.send_pdc_request("EGLL", "LIMC", "A339", "521", "K") is False


# --- failure paths ------------------------------------------------------------

SENDS = [
    # (name, station logged on before the send, the send taking on_done)
    ("logon", "", lambda s, done: s.logon("EGGX", done)),
    ("logoff", STATION, lambda s, done: s.logoff(done)),
    ("altitude", STATION, lambda s, done: s.send_altitude_change_request("FL350", on_done=done)),
    ("direct", STATION, lambda s, done: s.send_direct_request("MALOT", on_done=done)),
    ("speed", STATION, lambda s, done: s.send_speed_request("082", True, on_done=done)),
    ("when-can-we", STATION, lambda s, done: s.send_when_can_we_expect("WHEN CAN WE EXPECT HIGHER LEVEL", done)),
    ("acknowledgement", STATION, lambda s, done: s.send_acknowledgement(STATION, 7, "WILCO", done)),
    ("telex", STATION, lambda s, done: s.send_telex("EDDF", "HELLO", done)),
    ("pdc", STATION, lambda s, done: s.send_pdc_request("EGLL", "LIMC", "A339", "521", "K", done)),
]


@pytest.mark.parametrize(
    "station, send", [case[1:] for case in SENDS], ids=[case[0] for case in SENDS]
)
def test_a_transmission_failure_reaches_the_callback(make_session, station, send):
    """The error text reaches the dialog through on_done; nothing was recorded as sent."""
    session = make_session(
        station=station, connection=FakeConnectionManager(raise_with=HoppieError("boom"))
    )
    outcomes = []

    assert send(session, lambda success, text: outcomes.append((success, text))) is True
    session.worker.run_pending()

    assert outcomes == [(False, "boom")]
    assert (session.connection_manager.sent, session.connection_manager.telexes) == ([], [])


def test_a_failed_send_leaves_a_gap_in_the_min_sequence_rather_than_a_reused_number(make_session):
    """The MIN is spent when the frame is queued. A station does not mind a
    gap; it does mind seeing a number twice."""
    session = make_session(connection=FakeConnectionManager(raise_with=HoppieError("boom")))
    session.send_altitude_change_request("FL350")
    session.worker.run_pending()

    session.connection_manager.raise_with = None
    session.send_altitude_change_request("FL370")

    assert sent(session) == [(STATION, 2, "Y", "REQUEST FL370", None)]
