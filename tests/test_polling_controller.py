"""Tests for polling-rate decisions."""

from conftest import uplink
from hoppie_connector import CpdlcResponseRequirement as RR

from src.controller.polling_controller import PollingController
from src.model.message_manager import CPDLC_RESPONSES


def controller(logger):
    return PollingController(logger, connection_manager=None)


def test_a_bare_acknowledgement_does_not_speed_up_polling(logger):
    """Every response the client can send counts as an acknowledgement."""
    poller = controller(logger)

    for response in sorted(CPDLC_RESPONSES):
        message = uplink("LSAG", 1, response, rr=RR.NO)
        assert poller.should_increase_polling_rate(message) is False, response


def test_a_clearance_speeds_up_polling(logger):
    poller = controller(logger)

    message = uplink("LSAG", 1, "CLIMB TO AND MAINTAIN FL360")

    assert poller.should_increase_polling_rate(message) is True
