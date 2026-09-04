"""The SimConnect manager's tune path: it never connects on its own, and it
believes the simulator's answer (audit M-9)."""

from src.utils.simconnect_manager import SimConnectManager


class FakeSim:
    """Stands in for the upstream SimConnect object."""

    def __init__(self, accept=True, raise_with=None):
        self.accept = accept
        self.raise_with = raise_with
        self.events = []
        self.exited = False

    def send_event(self, event_id, value):
        if self.raise_with is not None:
            raise self.raise_with
        self.events.append((event_id, value))
        return self.accept

    def exit(self):
        self.exited = True


def connected(sim):
    manager = SimConnectManager()
    manager._sm = sim
    manager._event_id = 7
    return manager


def test_tuning_without_a_connection_fails_without_connecting():
    manager = SimConnectManager()

    assert manager.set_com1_standby_mhz(133.325) is False
    assert manager.is_connected() is False


def test_an_accepted_event_tunes_the_standby():
    sim = FakeSim()
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is True
    assert sim.events == [(7, 133325000)]


def test_a_refused_event_is_a_failure_and_drops_the_connection():
    """Upstream returns False instead of raising when the simulator is gone;
    the old code reported success and never retuned anything."""
    sim = FakeSim(accept=False)
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is False
    assert sim.exited is True
    assert manager.is_connected() is False


def test_an_event_that_raises_drops_the_connection():
    sim = FakeSim(raise_with=OSError("pipe closed"))
    manager = connected(sim)

    assert manager.set_com1_standby_mhz(133.325) is False
    assert sim.exited is True
    assert manager.is_connected() is False
