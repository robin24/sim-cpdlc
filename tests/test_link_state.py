"""Tests for the link state machine and its back-off ladder."""

from src.config import LINK_BACKOFF_MS, MAX_CONNECTION_FAILURES
from src.controller.link_state import LinkState
from src.model.connection_manager import PollResult

OK = PollResult(ok=True)


def failed(count, reason="timed out", fatal=False):
    return PollResult(ok=False, reason=reason, fatal=fatal, failures=count)


def make():
    changes = []
    link = LinkState(on_change=lambda old, new, reason: changes.append((old, new, reason)))
    return link, changes


def test_the_link_starts_connected():
    link, changes = make()

    assert (link.state, link.failures, link.next_delay_ms(), changes) == (
        LinkState.CONNECTED, 0, None, []
    )


def test_the_first_failures_degrade_the_link():
    link, changes = make()

    assert link.record_poll(failed(1)) is True
    assert link.record_poll(failed(2)) is False

    assert (link.state, link.failures, link.reason) == (LinkState.DEGRADED, 2, "timed out")
    assert changes == [(LinkState.CONNECTED, LinkState.DEGRADED, "timed out")]
    assert link.next_delay_ms() is None


def test_the_third_failure_loses_the_link_and_starts_the_ladder():
    link, changes = make()

    for count in range(1, MAX_CONNECTION_FAILURES + 1):
        link.record_poll(failed(count))

    assert link.state == LinkState.LOST
    assert link.next_delay_ms() == LINK_BACKOFF_MS[0] == 20000
    assert changes[-1] == (LinkState.DEGRADED, LinkState.LOST, "timed out")


def test_each_further_failure_climbs_the_ladder_to_its_cap():
    link, changes = make()
    for count in range(1, 4):
        link.record_poll(failed(count))

    delays = []
    for count in range(4, 9):
        link.record_poll(failed(count))
        delays.append(link.next_delay_ms())

    assert delays == [60000, 120000, 300000, 300000, 300000]
    assert link.state == LinkState.LOST
    assert len(changes) == 2, "climbing the ladder is not a transition"


def test_a_successful_poll_restores_the_link_and_resets_the_ladder():
    link, changes = make()
    for count in range(1, 6):
        link.record_poll(failed(count))

    assert link.record_poll(OK) is True

    assert (link.state, link.failures, link.reason, link.next_delay_ms()) == (
        LinkState.CONNECTED, 0, None, None
    )
    assert changes[-1] == (LinkState.LOST, LinkState.CONNECTED, None)

    for count in range(1, 4):
        link.record_poll(failed(count))
    assert link.next_delay_ms() == 20000, "the ladder starts over after a recovery"


def test_a_fatal_result_wins_from_any_state():
    link, changes = make()
    link.record_poll(failed(1))

    link.record_poll(failed(2, "invalid logon code", fatal=True))

    assert link.state == LinkState.FATAL
    assert link.next_delay_ms() is None
    assert changes[-1] == (LinkState.DEGRADED, LinkState.FATAL, "invalid logon code")


def test_reset_returns_to_connected_without_announcing_it():
    link, changes = make()
    for count in range(1, 4):
        link.record_poll(failed(count))
    announced = len(changes)

    link.reset()

    assert (link.state, link.failures, link.next_delay_ms()) == (LinkState.CONNECTED, 0, None)
    assert len(changes) == announced


def test_the_threshold_and_ladder_are_configurable():
    link = LinkState(max_failures=2, backoff_ms=(5, 10))

    link.record_poll(failed(1))
    assert link.state == LinkState.DEGRADED
    link.record_poll(failed(2))
    assert (link.state, link.next_delay_ms()) == (LinkState.LOST, 5)
    link.record_poll(failed(3))
    assert link.next_delay_ms() == 10
    link.record_poll(failed(4))
    assert link.next_delay_ms() == 10
