"""End-to-end tests for the acknowledgement path through MainWindow."""

from hoppie_connector import CpdlcResponseRequirement as RR

from tests.support import FakeConnectionManager, make_main_window, uplink

from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

STATION = "LSAG"


def build(logger):
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection)
    session.set_callsign("DLH123")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager, connection


def test_wilco_is_a_complete_response_frame(logger):
    """Recipient, own MIN, response requirement "N", text and the uplink's MIN
    as MRN. TODOS item 21: acknowledgements once went out as "NE", which some
    ATC clients ignore, and nothing asserted the requirement."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]


def test_each_acknowledgement_uses_the_next_own_min(logger):
    window, manager, connection = build(logger)
    first = manager.add_message(uplink(STATION, 53))
    second = manager.add_message(uplink(STATION, 54, "DESCEND TO AND MAINTAIN FL240"))

    window._on_acknowledge_message(first, "WILCO")
    window._on_acknowledge_message(second, "UNABLE")

    assert [(frame[1], frame[3], frame[4]) for frame in connection.sent] == [
        (1, "WILCO", 53),
        (2, "UNABLE", 54),
    ]


def test_wilco_retires_the_message(logger):
    window, manager, _ = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert manager.needs_acknowledgement(message_id, STATION) == (False, [])


def test_standby_is_sent_but_leaves_the_message_answerable(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "STANDBY")

    assert connection.sent[-1][3] == "STANDBY"
    assert manager.needs_acknowledgement(message_id, STATION)[0] is True


def test_an_unknown_id_sends_nothing_and_tells_the_user(logger):
    window, _manager, connection = build(logger)

    window._on_acknowledge_message(4242, "WILCO")

    assert connection.sent == []
    assert window.status_texts != []


def test_a_custom_message_id_sends_nothing_and_does_not_raise(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == []
