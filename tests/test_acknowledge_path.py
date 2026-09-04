"""End-to-end tests for the acknowledgement path through MainWindow.

A response is queued on the worker; the message is retired and echoed only
once the frame has gone out.
"""

from hoppie_connector import CpdlcResponseRequirement as RR, HoppieError

from tests.support import FakeConnectionManager, answerable, inline_worker, make_main_window, uplink

from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager

STATION = "LSAG"


def build(logger, connection=None):
    connection = connection if connection is not None else FakeConnectionManager()
    session = CpdlcSession(logger, connection, worker=inline_worker(logger))
    session.begin_session("DLH123", "hoppie")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, manager, connection


def acknowledge(window, message_id, response):
    window._on_acknowledge_message(message_id, response)
    window.worker.run_pending()


def test_wilco_is_a_complete_response_frame(logger):
    """Recipient, own MIN, response requirement "N", text and the uplink's MIN
    as MRN. TODOS item 21: acknowledgements once went out as "NE", which some
    ATC clients ignore, and nothing asserted the requirement."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]


def test_each_acknowledgement_uses_the_next_own_min(logger):
    window, manager, connection = build(logger)
    first = manager.add_message(uplink(STATION, 53))
    second = manager.add_message(uplink(STATION, 54, "DESCEND TO AND MAINTAIN FL240"))

    acknowledge(window, first, "WILCO")
    acknowledge(window, second, "UNABLE")

    assert [(frame[1], frame[3], frame[4]) for frame in connection.sent] == [
        (1, "WILCO", 53),
        (2, "UNABLE", 54),
    ]


def test_an_acknowledgement_is_queued_and_the_status_bar_says_so(logger):
    """The GUI thread queues the response and carries on; the echo, the status
    and the retirement follow once it has gone out."""
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    window._on_acknowledge_message(message_id, "WILCO")

    assert connection.sent == []
    assert window.status_texts[-1] == "Sending WILCO..."
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True

    window.worker.run_pending()

    assert connection.sent == [(STATION, 1, RR.NO.value, "WILCO", 53)]
    assert window.status_texts[-1] == "Sent WILCO."
    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (False, [])
    assert window.polling_controller.active_calls == 1


def test_wilco_retires_the_message(logger):
    window, manager, _ = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert manager.needs_acknowledgement(message_id, answerable(STATION)) == (False, [])


def test_standby_is_sent_but_leaves_the_message_answerable(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "STANDBY")

    assert connection.sent[-1][3] == "STANDBY"
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True


def test_an_unknown_id_sends_nothing_and_tells_the_user(logger):
    window, _manager, connection = build(logger)

    acknowledge(window, 4242, "WILCO")

    assert connection.sent == []
    assert window.status_texts != []


def test_a_custom_message_id_sends_nothing_and_does_not_raise(logger):
    window, manager, connection = build(logger)
    message_id = manager.add_custom_message("Connected as DLH123", "SYSTEM")

    acknowledge(window, message_id, "WILCO")

    assert connection.sent == []


def test_a_failed_acknowledgement_is_reported_and_stays_answerable(logger, message_boxes):
    """The worker paces sends, so SayIntentions' rate_limit should not recur;
    if it does, it is reported like any other failure and the message keeps
    its response menu."""
    connection = FakeConnectionManager(raise_with=HoppieError("rate_limit"))
    window, manager, _ = build(logger, connection)
    message_id = manager.add_message(uplink(STATION, 53))

    acknowledge(window, message_id, "WILCO")

    assert message_boxes.captions == ["Error"]
    assert "rate_limit" in message_boxes.calls[0][0]
    assert manager.needs_acknowledgement(message_id, answerable(STATION))[0] is True
    assert window.status_texts[-1] == "Could not send WILCO."
