"""How the window reports link health: rows and chimes, not just the status bar.

README.md documents the status bar as the surface a screen-reader user queries
by hand, so a lost link that only changed the status bar went unnoticed.
"""

from src.controller.link_state import LinkState
from src.model.connection_manager import UnreadableMessage
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from tests.support import FakeConnectionManager, inline_worker, make_main_window

STATION = "EDYY"


def build(logger):
    connection = FakeConnectionManager()
    session = CpdlcSession(logger, connection, worker=inline_worker(logger))
    session.begin_session("DLH123", "hoppie")
    session.handle_logon_accepted(STATION)
    manager = MessageManager(logger)
    window = make_main_window(logger, session, manager)
    return window, session, connection, manager


def rows(manager):
    return [manager.get_message_display_text(message_id) for message_id in sorted(manager.message_log)]


def test_a_lost_link_gets_a_row_and_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.DEGRADED, LinkState.LOST, "timed out")

    assert rows(manager) == [("SYSTEM", "Connection lost, retrying")]
    assert window.new_message_sound.played == 1
    assert window.weather_monitor.stopped is True


def test_a_link_restored_after_a_loss_gets_a_row_and_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.LOST, LinkState.CONNECTED, None)

    assert rows(manager) == [("SYSTEM", "Connection restored")]
    assert window.new_message_sound.played == 1
    assert window.weather_monitor.started is True


def test_a_brief_blip_only_touches_the_status_bar(logger):
    """One failed poll then a good one is not worth interrupting the pilot."""
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "timed out")
    window._on_link_change(LinkState.DEGRADED, LinkState.CONNECTED, None)

    assert rows(manager) == []
    assert window.new_message_sound.played == 0


def test_a_callsign_already_in_use_is_named_once(logger):
    """The log shows five of these; the pilot was never told which of the two
    clients had the callsign."""
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "callsign already in use")

    assert rows(manager) == [("SYSTEM", "Connection problem: callsign already in use")]
    assert window.new_message_sound.played == 0


def test_a_rejected_logon_code_tears_the_connection_down(logger, message_boxes):
    window, session, connection, manager = build(logger)

    window._on_link_change(LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")

    assert window.polling_controller.stopped is True
    assert (window.weather_monitor.stopped, window.weather_monitor.cleared) == (True, True)
    assert connection.disconnected is True
    assert session.is_logged_on() is False
    assert (window.menu_item_connect.label, window.menu_item_connect.help) == (
        "&Connect", "Connect to the CPDLC network"
    )
    assert window.status_texts[-1] == "Disconnected: logon code rejected."
    assert rows(manager)[-1] == ("SYSTEM", "Disconnected: the server rejected the logon code")
    assert window.new_message_sound.played == 1
    assert message_boxes.captions == ["Logon Code Rejected"]


def test_unreadable_uplinks_become_rows_with_the_chime(logger):
    window, _, _, manager = build(logger)

    window._on_unreadable_messages(
        [UnreadableMessage("EDGG", "/data2/6//R/QNH 1013 / TRL 70")]
    )

    assert rows(manager) == [
        ("SYSTEM", "Unreadable message from EDGG: /data2/6//R/QNH 1013 / TRL 70")
    ]
    assert window.new_message_sound.played == 1


def test_a_callsign_clash_is_named_once_even_when_it_is_not_the_first_failure(logger):
    window, _, _, manager = build(logger)

    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "timed out")
    window._on_link_change(LinkState.DEGRADED, LinkState.LOST, "callsign already in use")
    window._on_link_change(LinkState.LOST, LinkState.CONNECTED, None)
    window._on_link_change(LinkState.CONNECTED, LinkState.DEGRADED, "callsign already in use")

    texts = [text for _, text in rows(manager)]
    assert texts.count("Connection problem: callsign already in use") == 2
    assert texts[0] == "Connection lost, retrying"
